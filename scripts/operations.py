"""Offline, consistent Docker backup and restore into fresh isolated volumes.

Never prints environment variables. Writers and MinIO must be stopped by the
operator; PostgreSQL stays running for pg_dump. Restore never targets an existing
volume or a running application. Requires Python stdlib and Docker only.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tarfile

ROOT = Path(__file__).resolve().parents[1]
WRITERS = {'gateway-auth', 'marketplace', 'llm-gateway', 'minio'}

def run(*argv, **kwargs):
    return subprocess.run(argv, check=True, **kwargs)

def output(*argv):
    return subprocess.check_output(argv, text=True).strip()

def inspect(identifier):
    return json.loads(output('docker', 'inspect', identifier))[0]

def digest(path):
    h = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()

def containers(project):
    ids = output('docker', 'ps', '-aq', '--filter', f'label=com.docker.compose.project={project}').split()
    return [inspect(i) for i in ids]

def validate_archive(path):
    # Only data files/directories; reject traversal and links before any write.
    with tarfile.open(path) as archive:
        for entry in archive:
            parts = Path(entry.name).parts
            if Path(entry.name).is_absolute() or '..' in parts or not (entry.isfile() or entry.isdir()):
                raise ValueError('Недопустимый путь или тип объекта в архиве MinIO')

def application_versions(cs, revision):
    versions = {}
    for container in cs:
        service = container['Config']['Labels'].get('com.docker.compose.service')
        if service not in {'gateway-auth', 'marketplace', 'llm-gateway', 'optimizer', 'web'}:
            continue
        labels = inspect(container['Image'])['Config'].get('Labels') or {}
        bound = any(m['Type'] == 'bind' and m['Destination'] == '/app'
                    and Path(m['Source']).resolve() == ROOT / 'services' / service
                    for m in container['Mounts'])
        versions[service] = {'image_revision': labels.get('org.opencontainers.image.revision'),
                             'bound_source_revision': revision if bound else None}
    return versions


def backup(args):
    if subprocess.run(['git','-C',str(ROOT),'diff','--quiet','HEAD']).returncode:
        raise ValueError('Зафиксируйте изменения checkout до снимка; HEAD не описывает незакоммиченный код')
    pending = output('git','-C',str(ROOT),'ls-files','--others','--exclude-standard','--','apps','services','packages','scripts')
    if pending:
        raise ValueError('В checkout есть незакоммиченные файлы исходников')
    revision = output('git','-C',str(ROOT),'rev-parse','HEAD')
    cs = containers(args.project)
    if not cs:
        raise ValueError('Проект не найден')
    for c in cs:
        service = c['Config']['Labels'].get('com.docker.compose.service')
        if service in WRITERS and c['State']['Running']:
            raise ValueError(f'Перед снимком остановите {service}; автоматическая остановка не выполняется')
    pg = next(c for c in cs if c['Config']['Labels'].get('com.docker.compose.service') == 'postgres')
    storage = next(c for c in cs if c['Config']['Labels'].get('com.docker.compose.service') == 'minio')
    volume = next(m['Name'] for m in storage['Mounts'] if m['Destination'] == '/data' and m['Type'] == 'volume')
    if not pg['State']['Running']:
        raise ValueError('PostgreSQL должен работать для pg_dump')
    env = dict(v.split('=', 1) for v in pg['Config']['Env'] if '=' in v)
    directory = args.directory.resolve()
    directory.mkdir(mode=0o700, parents=True, exist_ok=False)
    os.chmod(directory, 0o700)
    try:
        with (directory / 'postgres.dump').open('wb') as stream:
            run('docker', 'exec', pg['Id'], 'pg_dump', '-Fc', '--no-owner', '--no-acl',
                '-U', env.get('POSTGRES_USER', 'sborka'), '-d', env.get('POSTGRES_DB', 'sborka'), stdout=stream)
        run('docker', 'run', '--rm', '--network', 'none', '-v', f'{volume}:/snapshot:ro',
            '-v', f'{directory}:/backup', '--entrypoint', 'tar', pg['Image'],
            '-cf', '/backup/minio.tar', '-C', '/snapshot', '.')
        validate_archive(directory / 'minio.tar')
        manifest = {'format': 1, 'source_project': args.project,
                    'checkout_revision': revision,
                    'applications': application_versions(cs, revision),
                    'models': json.loads((ROOT / 'infra/models.lock.json').read_text()),
                    'images': {c['Config']['Labels']['com.docker.compose.service']: c['Image'] for c in cs},
                    'files': {name: digest(directory / name) for name in ('postgres.dump', 'minio.tar')}}
        (directory / 'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + '\n')
        for path in directory.iterdir():
            os.chmod(path, 0o600)
    except Exception:
        # Incomplete snapshots have no trusted completion marker.
        (directory / 'manifest.json').unlink(missing_ok=True)
        raise
    print('Согласованный снимок создан. Каталог содержит приватные данные: храните вне Git.')

def restore(args):
    manifest = json.loads((args.directory / 'manifest.json').read_text())
    if manifest.get('format') != 1 or set(manifest.get('files', {})) != {'postgres.dump', 'minio.tar'}:
        raise ValueError('Неизвестный формат снимка')
    if args.project == manifest['source_project'] or containers(args.project):
        raise ValueError('Восстановление разрешено только в новый отдельный проект')
    for name, expected in manifest['files'].items():
        if digest(args.directory / name) != expected:
            raise ValueError(f'Контрольная сумма {name} не совпадает')
    validate_archive(args.directory / 'minio.tar')
    volumes = [f'{args.project}_{name}' for name in ('postgres_data', 'minio_data')]
    existing = set(output('docker', 'volume', 'ls', '-q').splitlines())
    if any(v in existing for v in volumes):
        raise ValueError('Целевые тома уже существуют; перезапись запрещена')
    image = manifest['images']['postgres']
    # Image must be local and is addressed by immutable ID, never a new download.
    if not re.fullmatch(r'sha256:[0-9a-f]{64}',image):
        raise ValueError('В manifest нужен неизменяемый ID PostgreSQL-образа')
    inspect(image)
    password = os.environ.get('RESTORE_POSTGRES_PASSWORD')
    if not password:
        raise ValueError('Задайте RESTORE_POSTGRES_PASSWORD вне Git')
    # Docker container names are an atomic reservation across CLI processes/hosts.
    # Reserve before creating or writing any volume, so concurrent restores of
    # the same project cannot both pass the initial existence check.
    lock = args.project + '-restore-lock'
    run('docker', 'create', '--name', lock, '--label', f'com.docker.compose.project={args.project}',
        '--network', 'none', '--entrypoint', 'true', image, stdout=subprocess.DEVNULL)
    for volume in volumes:
        run('docker', 'volume', 'create', '--label', f'com.docker.compose.project={args.project}', volume, stdout=subprocess.DEVNULL)
    run('docker', 'run', '--rm', '--network', 'none', '-v', f'{volumes[1]}:/snapshot',
        '-v', f'{args.directory.resolve()}:/backup:ro', '--entrypoint', 'tar', image,
        '-xf', '/backup/minio.tar', '-C', '/snapshot')
    name = args.project + '-restore-postgres'
    env = os.environ.copy(); env['POSTGRES_PASSWORD'] = password
    run('docker', 'run', '-d', '--name', name, '--label', f'com.docker.compose.project={args.project}',
        '--network', 'none', '-e', 'POSTGRES_PASSWORD', '-e', 'POSTGRES_USER=sborka', '-e', 'POSTGRES_DB=sborka',
        '-v', f'{volumes[0]}:/var/lib/postgresql/data', '--health-cmd', 'pg_isready -U sborka -d sborka',
        '--health-interval', '1s', '--health-retries', '60', image, env=env, stdout=subprocess.DEVNULL)
    import time
    for _ in range(60):
        state = inspect(name)['State']
        if state.get('Health', {}).get('Status') == 'healthy':
            break
        if not state['Running']:
            raise ValueError('PostgreSQL не запустился; сохранены тома для диагностики')
        time.sleep(1)
    else:
        raise ValueError('Истекло ожидание PostgreSQL; сохранены тома для диагностики')
    with (args.directory / 'postgres.dump').open('rb') as stream:
        run('docker', 'exec', '-i', name, 'pg_restore', '--exit-on-error', '--single-transaction',
            '--no-owner', '--no-acl', '-U', 'sborka', '-d', 'sborka', stdin=stream)
    run('docker', 'rm', lock, stdout=subprocess.DEVNULL)
    print(f'Восстановлено в {args.project}. Проверьте историю и файлы до подключения приложения. Секреты и модели восстанавливаются отдельно.')

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['backup', 'restore'])
    parser.add_argument('--project', required=True)
    parser.add_argument('--directory', type=Path, required=True)
    args = parser.parse_args()
    if not re.fullmatch(r'[a-z][a-z0-9-]{1,50}', args.project):
        parser.error('Нужен явный безопасный идентификатор проекта')
    # Dumps and private object data must never enter the checkout.
    if args.directory.resolve().is_relative_to(ROOT):
        parser.error('Каталог снимка должен находиться вне репозитория')
    try:
        (backup if args.action == 'backup' else restore)(args)
    except (ValueError, StopIteration, subprocess.CalledProcessError, OSError, KeyError) as error:
        print(f'Операция не завершена: {error}', file=sys.stderr)
        return 1
    return 0

if __name__ == '__main__':
    raise SystemExit(main())
