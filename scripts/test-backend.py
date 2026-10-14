#!/usr/bin/env python3
"""Run backend pytest suites in isolated Linux containers and disposable PostgreSQL.

Docker mode (default) builds Linux test images from existing requirements.lock.
Native mode requires Linux, cached PostgreSQL and each selected service's .venv.
Never reads .env or connects to the application's database; no persistent volumes.
"""
import argparse
from contextlib import contextmanager
import os
from pathlib import Path
import secrets
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from urllib.parse import quote
import uuid

ROOT = Path(__file__).resolve().parents[1]
SERVICES = ("gateway-auth", "marketplace", "llm-gateway", "optimizer")
IMAGE = "postgres:16.4-alpine"


@contextmanager
def temporary_postgres(network=None):
    name = "porukam-tests-" + uuid.uuid4().hex
    password = secrets.token_urlsafe(32)
    environment = {**os.environ, "POSTGRES_PASSWORD": password}
    started = False
    try:
        connection = ["--network", network, "--network-alias", "postgres"] if network else ["-p", "127.0.0.1::5432"]
        subprocess.run([
            "docker", "run", "--pull=never", "--rm", "-d", "--name", name,
            "--memory", "512m", "--cpus", "1", "--pids-limit", "256",
            "--tmpfs", "/var/lib/postgresql/data", *connection,
            "-e", "POSTGRES_USER=porukam_test", "-e", "POSTGRES_DB=porukam_test",
            "-e", "POSTGRES_PASSWORD", IMAGE,
        ], env=environment, check=True, stdout=subprocess.DEVNULL)
        started = True
        port = "5432" if network else subprocess.check_output(
            ["docker", "port", name, "5432/tcp"], text=True
        ).strip().rsplit(":", 1)[1]
        deadline = time.monotonic() + 60
        while subprocess.run([
            "docker", "exec", name, "pg_isready", "-U", "porukam_test", "-d", "porukam_test",
        ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode:
            if time.monotonic() >= deadline:
                raise RuntimeError("Временная PostgreSQL не запустилась за 60 секунд")
            time.sleep(0.5)
        host = "postgres" if network else "127.0.0.1"
        yield f"postgresql+asyncpg://porukam_test:{quote(password, safe='')}@{host}:{port}/porukam_test"
    finally:
        if started:
            subprocess.run(["docker", "rm", "-f", name], check=True, stdout=subprocess.DEVNULL)
            print("Временная PostgreSQL удалена", flush=True)


def test_environment(database_url=None):
    environment = os.environ.copy()
    for key in ("JWT_SECRET", "OPTIMIZER_TOKEN", "MINIO_SECRET_KEY"):
        environment[key] = secrets.token_urlsafe(48)
    if database_url:
        # Settings and test fixtures must both use the disposable database.
        environment["DATABASE_URL"] = database_url
        environment["TEST_DATABASE_URL"] = database_url
    environment.pop("RUN_OLLAMA_SMOKE", None)
    environment["ENABLE_DEMO_SEED"] = "false"
    return environment


@contextmanager
def test_network():
    name = "porukam-tests-" + uuid.uuid4().hex
    try:
        subprocess.run(["docker", "network", "create", "--internal", name], check=True, stdout=subprocess.DEVNULL)
        yield name
    finally:
        subprocess.run(["docker", "network", "rm", name], check=False,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def build_test_image(service):
    with tempfile.TemporaryDirectory(prefix="porukam-test-image-") as directory:
        identity = Path(directory) / "image-id"
        subprocess.run(["docker", "build", "--file", str(ROOT / "infra/Dockerfile.backend-tests"),
                        "--build-arg", "SERVICE=" + service, "--tag", "porukam-tests-" + service + ":local",
                        "--iidfile", str(identity), str(ROOT)], check=True)
        return identity.read_text().strip()


def run_container(service, pytest_args, image, network, url=None):
    # Do not forward parent credentials, service endpoints, smoke flags or .env.
    safe = {key: secrets.token_urlsafe(48) for key in ("JWT_SECRET", "OPTIMIZER_TOKEN", "MINIO_SECRET_KEY")}
    safe["ENABLE_DEMO_SEED"] = "false"
    if url:
        safe.update(DATABASE_URL=url, TEST_DATABASE_URL=url)
    environment = {**os.environ, **safe}
    name = "porukam-tests-" + uuid.uuid4().hex
    command = ["docker", "run", "--rm", "--pull=never", "--name", name, "--network", network,
               "--memory", "3g", "--cpus", "2", "--pids-limit", "512",
               "--mount", f"type=bind,source={ROOT},target=/repo,readonly",
               "--workdir", "/repo/services/" + service]
    for key in safe:
        command.extend(["--env", key])
    with tempfile.TemporaryDirectory(prefix="porukam-test-env-") as directory:
        empty = Path(directory) / "empty.env"
        empty.write_text("")
        # Settings can read a service-local .env even when no host env is forwarded.
        # Mask known dotenv paths in the read-only checkout without altering them.
        for path in [ROOT / ".env", *(ROOT / "services" / item / ".env" for item in SERVICES)]:
            if path.is_file():
                command.extend(["--mount", f"type=bind,source={empty},target=/repo/{path.relative_to(ROOT)},readonly"])
        command.extend([image, "python", "-m", "pytest", "-p", "no:cacheprovider", *pytest_args])
        try:
            return subprocess.call(command, env=environment)
        finally:
            # Also handle interruption or a failed Docker start; --rm may already have removed it.
            subprocess.run(["docker", "rm", "-f", name], check=False,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def run_suite(service, pytest_args, runtime="docker"):
    print(f"Проверка: {service} ({runtime})", flush=True)
    if runtime == "docker":
        image = build_test_image(service)
        with test_network() as network:
            if service == "optimizer":
                return run_container(service, pytest_args, image, network)
            with temporary_postgres(network) as url:
                return run_container(service, pytest_args, image, network, url)
    directory = ROOT / "services" / service
    python = directory / ".venv" / "bin" / "python"
    command = [str(python), "-m", "pytest", *pytest_args]
    if service == "optimizer":
        return subprocess.call(command, cwd=directory, env=test_environment())
    with temporary_postgres() as url:
        return subprocess.call(command, cwd=directory, env=test_environment(url))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--service", choices=(*SERVICES, "all"), default="all")
    parser.add_argument("--runtime", choices=("docker", "native"), default="docker")
    parser.add_argument("pytest_args", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    selected = SERVICES if args.service == "all" else (args.service,)
    if args.runtime == "native" and sys.platform != "linux":
        parser.error("Нативные декодеры требуют Linux; на macOS используйте --runtime docker (по умолчанию)")
    for service in selected if args.runtime == "native" else ():
        python = ROOT / "services" / service / ".venv" / "bin" / "python"
        if not python.is_file():
            parser.error(f"Нет окружения services/{service}/.venv; подготовьте его по README.md")
        compatible = subprocess.run([
            str(python), "-c",
            "from importlib.metadata import version; from packaging.version import Version; "
            "raise SystemExit(not (Version('9.1.1') <= Version(version('pytest')) < Version('10') "
            "and Version('1.4.0') <= Version(version('pytest-asyncio')) < Version('2')))"
        ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if compatible.returncode:
            parser.error(f"Обновите pytest и pytest-asyncio в services/{service}/.venv по README.md (версии CI)")
    if (args.runtime == "docker" or any(service != "optimizer" for service in selected)) and not shutil.which("docker"):
        parser.error("Нужен Docker для тестового окружения")
    pytest_args = args.pytest_args
    if pytest_args[:1] == ["--"]:
        pytest_args = pytest_args[1:]
    failures = [run_suite(service, pytest_args or ["-q"], args.runtime) for service in selected]
    return int(any(failures))


def interrupt(signum, frame):
    raise KeyboardInterrupt


if __name__ == "__main__":
    signal.signal(signal.SIGTERM, interrupt)
    try:
        sys.exit(main())
    except (OSError, subprocess.CalledProcessError, RuntimeError) as error:
        print(f"Не удалось выполнить проверку: {error}", file=sys.stderr)
        sys.exit(1)
    except KeyboardInterrupt:
        sys.exit(130)
