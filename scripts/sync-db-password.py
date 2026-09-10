"""Синхронизировать пароль роли PostgreSQL с POSTGRES_PASSWORD из .env.

PostgreSQL применяет POSTGRES_PASSWORD только при первой инициализации тома.
Если стенд уже запускался, смена .env пароль роли не меняет, и сервисы падают с
`password authentication failed for user "...".` Этот скрипт выставляет пароль из
.env через локальный unix-сокет контейнера postgres (local trust), не удаляя данные.

Пример:
    python3 scripts/sync-db-password.py
    python3 scripts/sync-db-password.py --env-file .env --project infra

Если тома PostgreSQL ещё нет, скрипт ничего не меняет: пароль применится при
первой инициализации базы.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_COMPOSE = ROOT / "infra" / "docker-compose.yml"


def read_env(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.is_file():
        raise SystemExit(f"Файл {path} не найден. Создайте его: python3 scripts/init-local-env.py")
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip()
    return values


def docker(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["docker", *args], text=True, capture_output=True, check=False)


def volumes_matching(suffix: str) -> list[str]:
    result = docker("volume", "ls", "--format", "{{.Name}}")
    if result.returncode != 0:
        raise SystemExit("Docker недоступен. Запустите Docker Desktop/Engine и повторите.")
    return [name for name in result.stdout.split() if name.endswith(suffix)]


def compose(compose_file: Path, project: str, env_file: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return docker("compose", "--project-name", project, "--env-file", str(env_file),
                  "-f", str(compose_file), *args)


def wait_for_postgres(compose_file: Path, project: str, env_file: Path, timeout: float) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        result = compose(compose_file, project, env_file, "ps", "--format", "json", "postgres")
        if result.returncode == 0:
            for line in result.stdout.splitlines():
                try:
                    service = json.loads(line)
                except json.JSONDecodeError:
                    continue
                state = (service.get("State") or "").lower()
                health = (service.get("Health") or "").lower()
                if state == "running" and health in ("", "healthy"):
                    return
        time.sleep(2)
    raise SystemExit("PostgreSQL не стал healthy за отведённое время. Проверьте: docker compose logs postgres")


def quote_sql(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def main() -> int:
    parser = argparse.ArgumentParser(description="Синхронизировать пароль роли PostgreSQL с .env")
    parser.add_argument("--env-file", default=str(ROOT / ".env"), help="путь к .env (по умолчанию ./.env)")
    parser.add_argument("--compose-file", default=str(DEFAULT_COMPOSE), help="путь к docker-compose.yml")
    parser.add_argument("--project", default="infra", help="имя compose-проекта (по умолчанию infra)")
    parser.add_argument("--timeout", type=float, default=90.0, help="ожидание готовности PostgreSQL, секунд")
    arguments = parser.parse_args()

    env_file = Path(arguments.env_file).resolve()
    compose_file = Path(arguments.compose_file).resolve()
    values = read_env(env_file)
    user = values.get("POSTGRES_USER", "sborka")
    database = values.get("POSTGRES_DB", "sborka")
    password = values.get("POSTGRES_PASSWORD", "")
    if not password:
        raise SystemExit("POSTGRES_PASSWORD пуст. Создайте .env через python3 scripts/init-local-env.py")

    volume_name = f"{arguments.project}_postgres_data"
    suffix = "postgres_data"
    existing = volumes_matching(suffix)
    if volume_name not in existing:
        print(f"Том {volume_name} не найден — пароль применится при первой инициализации базы. Изменения не нужны.")
        if existing:
            print("Найдены другие тома PostgreSQL: " + ", ".join(sorted(existing)))
            print("Если стенд использует один из них, повторите с --project <имя-проекта>.")
        return 0

    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", user):
        raise SystemExit("POSTGRES_USER содержит недопустимые символы")

    print(f"Найден существующий том {volume_name}: выставляю пароль роли {user} из {env_file.name}.")
    result = compose(compose_file, arguments.project, env_file, "up", "-d", "postgres")
    if result.returncode != 0:
        sys.stderr.write(result.stdout + result.stderr)
        raise SystemExit("Не удалось запустить контейнер postgres")
    wait_for_postgres(compose_file, arguments.project, env_file, arguments.timeout)

    statement = f"ALTER USER {user} WITH PASSWORD {quote_sql(password)};"
    result = compose(compose_file, arguments.project, env_file, "exec", "-T", "postgres",
                     "psql", "-U", user, "-d", database, "-v", "ON_ERROR_STOP=1", "-c", statement)
    if result.returncode != 0:
        sys.stderr.write(result.stdout + result.stderr)
        raise SystemExit("Не удалось изменить пароль роли. Проверьте, что PostgreSQL запущен именно этим проектом.")
    print("Пароль роли обновлён. Данные не удалялись.")
    print("Запустите сервисы: docker compose --env-file "
          f"{env_file.name} -f {compose_file.relative_to(ROOT)} up -d --build")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
