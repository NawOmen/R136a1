#!/usr/bin/env python3
"""Run backend pytest suites against disposable, loopback-only PostgreSQL.

Requires Docker, the cached postgres image and each selected service's .venv.
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
import time
from urllib.parse import quote
import uuid

ROOT = Path(__file__).resolve().parents[1]
SERVICES = ("gateway-auth", "marketplace", "llm-gateway", "optimizer")
IMAGE = "postgres:16.4-alpine"


@contextmanager
def temporary_postgres():
    name = "porukam-tests-" + uuid.uuid4().hex
    password = secrets.token_urlsafe(32)
    environment = {**os.environ, "POSTGRES_PASSWORD": password}
    started = False
    try:
        subprocess.run([
            "docker", "run", "--pull=never", "--rm", "-d", "--name", name,
            "--memory", "512m", "--cpus", "1", "--pids-limit", "256",
            "--tmpfs", "/var/lib/postgresql/data", "-p", "127.0.0.1::5432",
            "-e", "POSTGRES_USER=porukam_test", "-e", "POSTGRES_DB=porukam_test",
            "-e", "POSTGRES_PASSWORD", IMAGE,
        ], env=environment, check=True, stdout=subprocess.DEVNULL)
        started = True
        port = subprocess.check_output(
            ["docker", "port", name, "5432/tcp"], text=True
        ).strip().rsplit(":", 1)[1]
        deadline = time.monotonic() + 60
        while subprocess.run([
            "docker", "exec", name, "pg_isready", "-U", "porukam_test", "-d", "porukam_test",
        ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode:
            if time.monotonic() >= deadline:
                raise RuntimeError("Временная PostgreSQL не запустилась за 60 секунд")
            time.sleep(0.5)
        yield f"postgresql+asyncpg://porukam_test:{quote(password, safe='')}@127.0.0.1:{port}/porukam_test"
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


def run_suite(service, pytest_args):
    directory = ROOT / "services" / service
    python = directory / ".venv" / "bin" / "python"
    command = [str(python), "-m", "pytest", *pytest_args]
    print(f"Проверка: {service}", flush=True)
    if service == "optimizer":
        return subprocess.call(command, cwd=directory, env=test_environment())
    with temporary_postgres() as url:
        return subprocess.call(command, cwd=directory, env=test_environment(url))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--service", choices=(*SERVICES, "all"), default="all")
    parser.add_argument("pytest_args", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    selected = SERVICES if args.service == "all" else (args.service,)
    for service in selected:
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
    if any(service != "optimizer" for service in selected) and not shutil.which("docker"):
        parser.error("Нужен Docker для временной PostgreSQL")
    pytest_args = args.pytest_args
    if pytest_args[:1] == ["--"]:
        pytest_args = pytest_args[1:]
    failures = [run_suite(service, pytest_args or ["-q"]) for service in selected]
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
