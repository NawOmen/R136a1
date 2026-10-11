"""Destructive restore guards must fail before any Docker mutation."""
import argparse
import importlib.util
import io
from pathlib import Path
import tarfile
import tempfile
import unittest
from unittest.mock import patch
import json
import os
import subprocess
import shlex

spec=importlib.util.spec_from_file_location('operations',Path(__file__).with_name('operations.py'))
ops=importlib.util.module_from_spec(spec);spec.loader.exec_module(ops)

class RestoreSafety(unittest.TestCase):
    def test_rejects_traversal_links_and_devices(self):
        for name,kind in [('../escape',tarfile.REGTYPE),('/escape',tarfile.REGTYPE),('link',tarfile.SYMTYPE),('device',tarfile.CHRTYPE)]:
            with self.subTest(name=name), tempfile.TemporaryDirectory() as tmp:
                path=Path(tmp)/'minio.tar'
                with tarfile.open(path,'w') as archive:
                    item=tarfile.TarInfo(name);item.type=kind;item.size=0
                    archive.addfile(item,io.BytesIO())
                with self.assertRaises(ValueError):ops.validate_archive(path)

    def test_same_project_or_existing_container_cannot_restore(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp);(path/'manifest.json').write_text(json.dumps({'format':1,'source_project':'source','files':{'postgres.dump':'','minio.tar':''}}))
            for project,existing in [('source',[]),('separate',[{}])]:
                with self.subTest(project=project),patch.object(ops,'containers',return_value=existing),patch.object(ops,'run') as mutation:
                    with self.assertRaises(ValueError):ops.restore(argparse.Namespace(directory=path,project=project))
                    mutation.assert_not_called()

    def test_corrupt_dump_cannot_create_volume(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp);(path/'postgres.dump').write_bytes(b'changed')
            (path/'manifest.json').write_text(json.dumps({'format':1,'source_project':'source','files':{'postgres.dump':'invalid','minio.tar':'invalid'}}))
            with patch.object(ops,'containers',return_value=[]),patch.object(ops,'run') as mutation:
                with self.assertRaises(ValueError):ops.restore(argparse.Namespace(directory=path,project='separate'))
                mutation.assert_not_called()

    def test_existing_volume_never_overwritten(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp);(path/'postgres.dump').write_bytes(b'archive')
            with tarfile.open(path/'minio.tar','w'):pass
            (path/'manifest.json').write_text(json.dumps({'format':1,'source_project':'source',
                'files':{name:ops.digest(path/name) for name in ('postgres.dump','minio.tar')}}))
            with patch.object(ops,'containers',return_value=[]),patch.object(ops,'output',return_value='target_postgres_data'),patch.object(ops,'run') as mutation:
                with self.assertRaises(ValueError):ops.restore(argparse.Namespace(directory=path,project='target'))
                mutation.assert_not_called()

    def test_dirty_checkout_cannot_claim_head_version(self):
        from types import SimpleNamespace
        with patch.object(ops.subprocess,'run',return_value=SimpleNamespace(returncode=1)),patch.object(ops,'containers') as read,patch.object(ops,'run') as mutation:
            with self.assertRaises(ValueError):ops.backup(argparse.Namespace(project='source',directory=Path('/tmp/unused')))
            read.assert_not_called();mutation.assert_not_called()

    def test_bound_source_revision_does_not_relabel_image(self):
        container={'Config':{'Labels':{'com.docker.compose.service':'marketplace'}},'Image':'sha256:old',
                   'Mounts':[{'Type':'bind','Destination':'/app','Source':str(ops.ROOT/'services/marketplace')}]}
        with patch.object(ops,'inspect',return_value={'Config':{'Labels':{'org.opencontainers.image.revision':'old-commit'}}}):
            version=ops.application_versions([container],'current-commit')['marketplace']
            self.assertEqual(version,{'image_revision':'old-commit','bound_source_revision':'current-commit'})


    def test_snapshot_rejects_other_checkout_and_symlink_before_mutation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = root / 'other-repository'
            subprocess.run(['git', 'init', '-q', str(repo)], check=True)
            link = root / 'alias'
            link.symlink_to(repo, target_is_directory=True)
            for directory in (repo / 'private' / 'snapshot', link / 'private' / 'snapshot'):
                with self.subTest(directory=directory):
                    with self.assertRaises(ValueError):
                        ops.validate_snapshot_directory(directory)
            ops.validate_snapshot_directory(root / 'outside' / 'snapshot')
            bare = root / 'bare.git'
            subprocess.run(['git', 'init', '--bare', '-q', str(bare)], check=True)
            with self.assertRaises(ValueError):
                ops.validate_snapshot_directory(bare / 'private')

    def test_restore_preserves_coordinates_and_legacy_override(self):
        for version, coordinates, override, expected in [
            (2, {'user': 'synthetic_operator', 'database': 'synthetic_product'}, {}, ('synthetic_operator', 'synthetic_product')),
            (1, None, {}, ('sborka', 'sborka')),
            (1, None, {'postgres_user': 'custom_operator', 'postgres_db': 'custom_product'}, ('custom_operator', 'custom_product')),
            (2, {'user': "operator'quoted", 'database': "product'quoted"}, {}, ("operator'quoted", "product'quoted")),
        ]:
            with self.subTest(version=version, expected=expected), tempfile.TemporaryDirectory() as tmp:
                path = Path(tmp)
                (path / 'postgres.dump').write_bytes(b'synthetic archive')
                with tarfile.open(path / 'minio.tar', 'w'):
                    pass
                manifest = {'format': version, 'source_project': 'source',
                    'images': {'postgres': 'sha256:' + 'a' * 64},
                    'files': {name: ops.digest(path / name) for name in ('postgres.dump', 'minio.tar')}}
                if coordinates:
                    manifest['postgres'] = coordinates
                (path / 'manifest.json').write_text(json.dumps(manifest))
                with patch.object(ops, 'containers', return_value=[]), patch.object(ops, 'output', return_value=''), \
                     patch.object(ops, 'inspect', return_value={'State': {'Running': True, 'Health': {'Status': 'healthy'}}}), \
                     patch.object(ops, 'run') as mutation, patch.dict(os.environ, {'RESTORE_POSTGRES_PASSWORD': 'synthetic-only'}):
                    ops.restore(argparse.Namespace(directory=path, project='target', **override))
                calls = mutation.call_args_list
                start = next(c for c in calls if '-d' in c.args and c.args[:2] == ('docker', 'run'))
                self.assertEqual((start.kwargs['env']['POSTGRES_USER'], start.kwargs['env']['POSTGRES_DB']), expected)
                health = shlex.split(start.args[start.args.index('--health-cmd') + 1])
                self.assertEqual(health[health.index('-U') + 1], expected[0])
                self.assertEqual(health[health.index('-d') + 1], ops.database_connection(expected[1]))
                restore = next(c for c in calls if 'pg_restore' in c.args)
                self.assertEqual(restore.args[restore.args.index('-U') + 1], expected[0])
                self.assertEqual(restore.args[restore.args.index('-d') + 1], ops.database_connection(expected[1]))

    def test_backup_records_source_coordinates_without_password(self):
        from types import SimpleNamespace
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'snapshot'
            cs = [{'Id': 'pg', 'Image': 'sha256:' + 'a' * 64, 'State': {'Running': True},
                'Config': {'Labels': {'com.docker.compose.service': 'postgres'}, 'Env': [
                    'POSTGRES_USER=synthetic_operator', 'POSTGRES_DB=synthetic_product', 'POSTGRES_PASSWORD=synthetic-only']}},
                {'Id': 'minio', 'Image': 'minio-image', 'State': {'Running': False},
                 'Config': {'Labels': {'com.docker.compose.service': 'minio'}},
                 'Mounts': [{'Name': 'synthetic-volume', 'Destination': '/data', 'Type': 'volume'}]}]
            def mutation(*args, **kwargs):
                if 'pg_dump' in args:
                    kwargs['stdout'].write(b'synthetic archive')
                if '-cf' in args:
                    with tarfile.open(path / 'minio.tar', 'w'):
                        pass
            with patch.object(ops.subprocess, 'run', return_value=SimpleNamespace(returncode=0)), \
                 patch.object(ops, 'output', side_effect=['', 'synthetic-revision']), patch.object(ops, 'containers', return_value=cs), \
                 patch.object(ops, 'application_versions', return_value={}), patch.object(ops, 'run', side_effect=mutation):
                ops.backup(argparse.Namespace(project='source', directory=path))
            manifest = json.loads((path / 'manifest.json').read_text())
            self.assertEqual(manifest['format'], 2)
            self.assertEqual(manifest['postgres'], {'user': 'synthetic_operator', 'database': 'synthetic_product'})
            self.assertNotIn('synthetic-only', (path / 'manifest.json').read_text())


if __name__=='__main__':unittest.main()
