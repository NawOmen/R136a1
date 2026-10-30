"""Подготовка и восстановление отдельного синтетического стенда для записи.

Не использует рабочую .env, не удаляет Docker volumes и не печатает пароли.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import secrets
import subprocess

ROOT = Path(__file__).resolve().parents[1]
PROJECT = "r136-recording"
ENV = ROOT / ".env.recording"
STATE = ROOT / ".cache/recording-demo"
DATABASE = "porukam_recording"


def private_write(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as stream:
        stream.write(content)


def initialize() -> None:
    values = {key: secrets.token_urlsafe(48) for key in (
        "JWT_SECRET", "OPTIMIZER_TOKEN", "POSTGRES_PASSWORD", "MINIO_ROOT_PASSWORD",
        "PGADMIN_DEFAULT_PASSWORD", "SEED_ADMIN_PASSWORD", "SEED_DEMO_PASSWORD", "SEED_SELLER_PASSWORD",
        "SEED_SELLER2_PASSWORD")}
    values.update(POSTGRES_USER="sborka", POSTGRES_DB=DATABASE, ENABLE_DEMO_SEED="true",
                  SEED_DEMO_EMAIL="buyer@show.porukam.ru", SEED_SELLER_EMAIL="seller@show.porukam.ru",
                  SEED_SELLER2_EMAIL="supplier@demo.ru",
                  SEED_ADMIN_EMAIL="admin@show.porukam.ru", BUYER_TRIAL_ENABLED="false",
                  SEED_SELLER_STORIES="false",
                  MINIO_ROOT_USER="porukam", MINIO_ACCESS_KEY="porukam",
                  LOCAL_LLM_BACKEND="mlx", ASSISTANT_LLM_BACKEND="ollama",
                  MLX_BASE_URL="http://host.docker.internal:8080", TRAINED_MODEL_VERSION="porukam-buyer-qwen3.5",
                  OLLAMA_DOCKER_BASE_URL="http://host.docker.internal:11434", OLLAMA_MODEL="qwen3.5:9b",
                  OLLAMA_VISION_MODEL="qwen3.5:9b")
    values["MINIO_SECRET_KEY"] = values["MINIO_ROOT_PASSWORD"]
    private_write(ENV, ("# Только отдельный стенд записи. Секреты не публиковать.\n" +
                              "".join(f"{key}={value}\n" for key, value in values.items())).encode())
    print("Создана .env.recording (0600). Два аккаунта показа: buyer@show.porukam.ru и seller@show.porukam.ru.")
    print("Пароли: SEED_DEMO_PASSWORD и SEED_SELLER_PASSWORD в этом локальном файле.")


def configuration() -> dict[str, str]:
    values = dict(line.split("=", 1) for line in ENV.read_text().splitlines()
                  if line and not line.startswith("#") and "=" in line)
    if values.get("POSTGRES_DB") != DATABASE or values.get("ENABLE_DEMO_SEED") != "true":
        raise ValueError("Нужна отдельная синтетическая база porukam_recording в .env.recording")
    for key, expected in (("SEED_DEMO_EMAIL", "buyer@show.porukam.ru"), ("SEED_SELLER_EMAIL", "seller@show.porukam.ru")):
        if values.get(key) != expected:
            raise ValueError("Аккаунты записи не совпадают с конфигурацией отдельного стенда")
    return values


def compose(*args: str, **kwargs):
    # Переменные shell не должны переопределить отдельную конфигурацию через Compose.
    values = configuration()
    env = {key: value for key, value in os.environ.items()
           if key not in values and not key.startswith("COMPOSE_")}
    prefix = ["sudo"] if values.get("LOCAL_DOCKER_SUDO") == "true" and os.geteuid() != 0 else []
    return subprocess.run([*prefix, "docker", "compose", "--project-name", PROJECT, "--env-file", str(ENV),
                           "-f", str(ROOT / "infra/docker-compose.yml"), *args],
                          cwd=ROOT, env=env, check=True, **kwargs)


def assert_owned_database() -> None:
    identity = compose("exec", "-T", "postgres", "sh", "-c", 'printf "%s" "$POSTGRES_DB"',
                       capture_output=True, text=True).stdout
    if identity != DATABASE:
        raise ValueError("Контейнер не обслуживает отдельную базу записи; операция остановлена")


def snapshot() -> None:
    assert_owned_database()
    # Не перезаписываем исходную точку случайной второй репетицией.
    if (STATE / "baseline.dump").exists() or (STATE / "baseline.json").exists():
        raise ValueError("Начальная точка уже сохранена. Используйте reset, а не новую копию поверх неё.")
    compose("stop", "web", "gateway-auth", "marketplace", "llm-gateway")
    try:
        dump = compose("exec", "-T", "postgres", "sh", "-c",
                       'exec pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" --format=custom', capture_output=True).stdout
        sha = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
        private_write(STATE / "baseline.dump", dump)
        private_write(STATE / "baseline.json", json.dumps({"project": PROJECT, "database": DATABASE, "commit": sha}).encode())
    finally:
        compose("up", "-d", "--wait", "gateway-auth", "marketplace", "llm-gateway", "web")
    print("Начальная точка сохранена локально. Входы и товар сохранятся после reset.")


def reset() -> None:
    assert_owned_database()
    metadata = json.loads((STATE / "baseline.json").read_text())
    if metadata.get("project") != PROJECT or metadata.get("database") != DATABASE:
        raise ValueError("Копия относится к другому стенду")
    sha = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    if metadata.get("commit") != sha:
        raise ValueError("Версия кода изменилась после сохранения. Не восстанавливаем несовместимую схему автоматически.")
    dump = (STATE / "baseline.dump").read_bytes()
    compose("stop", "web", "gateway-auth", "marketplace", "llm-gateway")
    # При ошибке оставляем приложение остановленным: частичный сброс не выдаётся за успех.
    compose("exec", "-T", "postgres", "sh", "-c",
            'exec pg_restore -U "$POSTGRES_USER" -d "$POSTGRES_DB" --clean --if-exists --no-owner --single-transaction', input=dump)
    compose("up", "-d", "--wait", "gateway-auth", "marketplace", "llm-gateway", "web")
    print("Восстановлено начальное состояние: аккаунты и товар готовы, результаты репетиции убраны.")
    print("Закройте сеансы браузера и войдите заново: браузерные черновики в базу не входят.")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["init", "start", "prepare", "snapshot", "reset", "rehearse", "rehearse-manual"])
    action = parser.parse_args().action
    if action == "init":
        initialize()
    elif action == "start":
        compose("up", "-d", "--build", "--wait")
    elif action == "prepare":
        assert_owned_database()
        compose("exec", "-T", "marketplace", "python", "prepare_recording.py")
    elif action == "snapshot":
        snapshot()
    elif action.startswith("rehearse"):
        values = configuration()
        env = dict(os.environ, E2E_TEST_PROJECT=PROJECT, E2E_RECORDING_SCENARIO="bolt-20000",
                   RUN_LIVE_CORE_FLOW="1" if action == "rehearse" else "0")
        for role, prefix in (("BUYER", "DEMO"), ("SELLER", "SELLER"), ("ADMIN", "ADMIN")):
            env[f"E2E_{role}_EMAIL"] = values[f"SEED_{prefix}_EMAIL"]
            env[f"E2E_{role}_PASSWORD"] = values[f"SEED_{prefix}_PASSWORD"]
        subprocess.run(["pnpm", "exec", "playwright", "test", "--config", "recording-core-flow.config.ts"],
                       cwd=ROOT / "tests/e2e", env=env, check=True)
    else:
        reset()


if __name__ == "__main__":
    try:
        main()
    except (ValueError, FileNotFoundError, subprocess.CalledProcessError) as exc:
        raise SystemExit(f"Подготовка записи остановлена: {exc}") from exc
