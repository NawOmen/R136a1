"""Локальная обученная модель вне Docker: проверка, запуск и автозапуск.

Модель не работает в контейнере: MLX-сервер с LoRA-адаптером поднимается на хосте
и слушает только loopback. LLM Gateway из Compose обращается к нему по
`MLX_BASE_URL=http://host.docker.internal:8080`.

Команды:
  verify          проверить базу и адаптер по контрольным суммам
  start           поднять агент автозапуска (или фоновый процесс без него)
  stop            остановить сервер, не удаляя агент автозапуска
  restart         перезапустить сервер
  status          показать состояние: процесс, адрес, модель, автозапуск
  logs            показать последние строки журнала
  install-agent   включить автозапуск при входе в систему (launchd, macOS)
  uninstall-agent выключить автозапуск
  serve           работать в переднем плане (для launchd и других супервизоров)
"""
from __future__ import annotations

import argparse
import json
import os
import plistlib
import re
import signal
import subprocess
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Mapping

LABEL = "ru.porukam.mlx-server"
SUPPORT_DIR = Path.home() / "Library" / "Application Support" / "PoRukam-LLM"
AGENTS_DIR = Path.home() / "Library" / "LaunchAgents"
LOG_DIR = Path.home() / "Library" / "Logs" / "PoRukam-LLM"
LOOPBACK = {"127.0.0.1", "localhost", "::1"}
EX_CONFIG = 2


class ConfigError(Exception):
    """Настройки не дают запустить модель; текст пригоден для оператора."""


@dataclass(frozen=True)
class Settings:
    repo: Path
    python: Path
    model_dir: Path
    adapter_dir: Path
    host: str
    port: int

    @property
    def build_script(self) -> Path:
        return self.repo / "infra" / "build_local_model.py"

    @property
    def base_url(self) -> str:
        return f"http://{self.host}:{self.port}"

    @property
    def log_file(self) -> Path:
        return LOG_DIR / f"{LABEL}.log"

    @property
    def error_log_file(self) -> Path:
        return LOG_DIR / f"{LABEL}.error.log"

    @property
    def pid_file(self) -> Path:
        return SUPPORT_DIR / "mlx-server.pid"

    @property
    def plist_file(self) -> Path:
        return AGENTS_DIR / f"{LABEL}.plist"


def read_dotenv(path: Path) -> dict[str, str]:
    """Прочитать KEY=VALUE из .env, не выполняя содержимое файла."""
    values: dict[str, str] = {}
    if not path.is_file():
        return values
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        entry = line.strip()
        if not entry or entry.startswith("#") or "=" not in entry:
            continue
        key, _, value = entry.partition("=")
        key = key.strip().removeprefix("export ").strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        if key:
            values[key] = value
    return values


def settings_from(env: Mapping[str, str], repo: Path) -> Settings:
    """Собрать настройки: окружение важнее .env, неизвестные пути — ошибка оператора."""
    try:
        port = int(env.get("MLX_PORT") or 8080)
    except ValueError as exc:
        raise ConfigError("MLX_PORT должен быть числом") from exc
    if not 1 <= port <= 65535:
        raise ConfigError("MLX_PORT должен быть в диапазоне 1–65535")
    host = (env.get("MLX_HOST") or "127.0.0.1").strip()
    if host not in LOOPBACK:
        raise ConfigError(
            "MLX_HOST должен быть loopback (127.0.0.1): модель не публикуется в сеть, "
            "контейнеры обращаются к ней через host.docker.internal"
        )
    missing = [name for name in ("MLX_MODEL_DIR", "MLX_ADAPTER_DIR") if not (env.get(name) or "").strip()]
    if missing:
        raise ConfigError(
            f"Задайте {', '.join(missing)} в .env: путь к базовым весам и к каталогу адаптера"
        )
    python = Path(env.get("MLX_SERVE_PYTHON") or "").expanduser()
    if not python.is_file():
        default = SUPPORT_DIR / "mlx-venv" / "bin" / "python"
        python = default if default.is_file() else Path(sys.executable)
    return Settings(
        repo=repo,
        python=python,
        model_dir=Path(env["MLX_MODEL_DIR"]).expanduser(),
        adapter_dir=Path(env["MLX_ADAPTER_DIR"]).expanduser(),
        host=host,
        port=port,
    )


def load_settings(repo: Path, env: Mapping[str, str] | None = None) -> Settings:
    merged = read_dotenv(repo / ".env")
    merged.update({key: value for key, value in (env if env is not None else os.environ).items()})
    return settings_from(merged, repo)


def probe(settings: Settings, timeout: float = 5.0) -> list[str] | None:
    """Спросить у MLX-сервера список моделей; None — сервер не отвечает."""
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(settings.base_url + "/v1/models", timeout=timeout) as response:
            payload = json.loads(response.read(1024 * 1024))
    except (OSError, ValueError, urllib.error.URLError):
        return None
    data = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(data, list):
        return None
    return [str(item.get("id")) for item in data if isinstance(item, dict) and item.get("id")]


def memory_hint(settings: Settings) -> None:
    """Проверить то, без чего сервер поднимается, но отвечает неполноценно."""
    if not settings.python.is_file():
        raise ConfigError(f"Не найден интерпретатор {settings.python}; задайте MLX_SERVE_PYTHON")
    if not settings.model_dir.is_dir():
        raise ConfigError(f"Нет каталога базовых весов {settings.model_dir} (MLX_MODEL_DIR)")
    if not settings.adapter_dir.is_dir():
        raise ConfigError(f"Нет каталога адаптера {settings.adapter_dir} (MLX_ADAPTER_DIR)")
    if not settings.build_script.is_file():
        raise ConfigError(f"Нет скрипта проверки модели {settings.build_script}")


def check_mlx_runtime(settings: Settings, runner: Callable[..., subprocess.CompletedProcess] = subprocess.run) -> None:
    """MLX-LM живёт в отдельном окружении на хосте, а не в контейнере и не в системе."""
    result = runner(
        [str(settings.python), "-c", "import mlx_lm.server"],
        capture_output=True, text=True, check=False,
    )
    if result.returncode != 0:
        raise ConfigError(
            f"{settings.python} не содержит MLX-LM. Создайте окружение по "
            "ml/training/porukam-trained-current/requirements-serving.txt и укажите "
            "MLX_SERVE_PYTHON в .env"
        )


def verify(
    settings: Settings,
    runner: Callable[..., subprocess.CompletedProcess] = subprocess.run,
) -> tuple[bool, str]:
    """Сверить SHA256 адаптера, конфигурации и базовых весов через infra/build_local_model.py."""
    result = runner(
        [str(settings.python), str(settings.build_script),
         "--base", str(settings.model_dir), "--adapter", str(settings.adapter_dir)],
        capture_output=True, text=True, check=False,
    )
    output = (result.stdout + result.stderr).strip()
    return result.returncode == 0, output


def ensure_cache_dir(out: Callable[[str], None]) -> None:
    """Кеш Hugging Face нужен для GET /v1/models; без него сервер отдаёт CacheNotFound."""
    cache = Path.home() / ".cache" / "huggingface" / "hub"
    if cache.is_dir():
        return
    cache.mkdir(parents=True, exist_ok=True)
    out(f"Создан каталог кеша Hugging Face: {cache}")


def read_pid(settings: Settings) -> int | None:
    try:
        return int(settings.pid_file.read_text().strip())
    except (OSError, ValueError):
        return None


def pid_alive(pid: int | None) -> bool:
    if not pid:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def server_command(settings: Settings) -> list[str]:
    return [
        str(settings.python), str(settings.build_script),
        "--base", str(settings.model_dir),
        "--adapter", str(settings.adapter_dir),
        "--host", settings.host, "--port", str(settings.port), "--serve",
    ]


def wait_ready(settings: Settings, seconds: float, out: Callable[[str], None]) -> bool:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        ids = probe(settings, timeout=5.0)
        if ids is not None:
            out(f"Модель отвечает: {settings.base_url}/v1/models → {', '.join(ids) or 'пустой список'}")
            return True
        time.sleep(2.0)
    return False


def start(
    settings: Settings,
    out: Callable[[str], None] = print,
    *,
    wait: float = 240.0,
    runner: Callable[..., subprocess.CompletedProcess] = subprocess.run,
    spawn: Callable[..., subprocess.Popen] = subprocess.Popen,
) -> int:
    """Поднять модель: агентом launchd, если он установлен, иначе фоновым процессом."""
    memory_hint(settings)
    ensure_cache_dir(out)
    if probe(settings):
        out(f"MLX-сервер уже работает на {settings.base_url}.")
        return 0
    out("Проверяю базу и адаптер (SHA256)…")
    ok, output = verify(settings, runner)
    if not ok:
        out(output or "Проверка модели не пройдена.")
        return 1
    check_mlx_runtime(settings, runner)
    if agent_bootstrapped(settings):
        out("Поднимаю агент автозапуска launchd…")
        if not bootstrap_agent(settings):
            return 1
        if wait_ready(settings, wait, out):
            return 0
        out("Агент загружен, но модель пока не ответила. Журнал: " + str(settings.log_file))
        return 1
    SUPPORT_DIR.mkdir(parents=True, exist_ok=True)
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    with settings.log_file.open("a", encoding="utf-8") as log:
        log.write(f"\n=== {time.strftime('%Y-%m-%d %H:%M:%S')} запуск {settings.base_url} ===\n")
        log.flush()
        process = spawn(
            server_command(settings),
            stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT,
            start_new_session=True, cwd=str(settings.repo), close_fds=True,
        )
    settings.pid_file.write_text(str(process.pid))
    out(f"MLX-сервер запущен (PID {process.pid}), журнал {settings.log_file}.")
    out("Загрузка весов занимает десятки секунд; жду ответа /v1/models…")
    if wait_ready(settings, wait, out):
        return 0
    out("Модель не ответила за отведённое время. Последние строки журнала:")
    out(tail(settings.log_file, 20))
    return 1


def stop(settings: Settings, out: Callable[[str], None] = print) -> int:
    """Остановить сервер. Агент автозапуска остаётся в системе до следующего входа."""
    if agent_loaded():
        subprocess.run(["launchctl", "bootout", f"gui/{os.getuid()}/{LABEL}"], check=False)
        settings.pid_file.unlink(missing_ok=True)
        for _ in range(40):
            if not probe(settings, timeout=1.0):
                out("MLX-сервер остановлен. Автозапуск снова поднимет его при входе в систему; "
                    "отключить совсем: scripts/local_model.py uninstall-agent")
                return 0
            time.sleep(0.5)
        out(f"Сервер не остановился: порт {settings.port} всё ещё отвечает.")
        return 1
    pid = read_pid(settings)
    if not pid_alive(pid):
        settings.pid_file.unlink(missing_ok=True)
        if probe(settings, timeout=1.0):
            out(f"Порт {settings.port} занят процессом без файла состояния. Остановите его: "
                f"lsof -nP -iTCP:{settings.port} -sTCP:LISTEN")
            return 1
        out("MLX-сервер уже остановлен.")
        return 0
    assert pid is not None
    os.kill(pid, signal.SIGTERM)
    for _ in range(60):
        if not pid_alive(pid):
            break
        time.sleep(0.5)
    else:
        os.kill(pid, signal.SIGKILL)
    settings.pid_file.unlink(missing_ok=True)
    out(f"MLX-сервер остановлен (PID {pid}).")
    return 0


def tail(path: Path, lines: int) -> str:
    try:
        content = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return f"Журнал {path} не найден."
    return "\n".join(content[-lines:]) if content else "Журнал пуст."


def agent_loaded(label: str = LABEL) -> bool:
    result = subprocess.run(["launchctl", "print", f"gui/{os.getuid()}/{label}"],
                            capture_output=True, text=True, check=False)
    return result.returncode == 0


def agent_pid(label: str = LABEL) -> int | None:
    """PID процесса, которым управляет launchd; None — агент не держит процесс."""
    result = subprocess.run(["launchctl", "print", f"gui/{os.getuid()}/{label}"],
                            capture_output=True, text=True, check=False)
    if result.returncode != 0:
        return None
    match = re.search(r"^\s*pid = (\d+)$", result.stdout, re.MULTILINE)
    return int(match.group(1)) if match else None


def agent_bootstrapped(settings: Settings) -> bool:
    return sys.platform == "darwin" and settings.plist_file.is_file()


def bootstrap_agent(settings: Settings) -> bool:
    """Поднять агент, не трогая уже загруженный: bootstrap дважды возвращает ошибку."""
    if not agent_loaded():
        result = subprocess.run(["launchctl", "bootstrap", f"gui/{os.getuid()}", str(settings.plist_file)],
                                capture_output=True, text=True, check=False)
        if result.returncode != 0:
            print(f"launchctl bootstrap: {(result.stderr or result.stdout).strip()}", file=sys.stderr)
            return False
    subprocess.run(["launchctl", "kickstart", f"gui/{os.getuid()}/{LABEL}"], check=False)
    return True


def render_plist(settings: Settings) -> bytes:
    """Описание агента launchd: модель поднимается при входе в систему на хосте.

    `ProcessType` намеренно не задан. С `Background` launchd понижает приоритет
    потоков, и металлическое ядро отдаёт 7–8 токенов/с вместо 19–21: замер на
    одном и том же запросе — 28,1 с и 9,6 с на 200 токенов. Языковая модель
    обслуживает интерфейс в реальном времени, поэтому приоритет обычный.
    """
    return plistlib.dumps({
        "Label": LABEL,
        "ProgramArguments": [str(settings.python), str(settings.repo / "scripts" / "local_model.py"), "serve"],
        "WorkingDirectory": str(settings.repo),
        "RunAtLoad": True,
        # Перезапуск только после сбоя: штатная остановка оператором не поднимает сервер снова.
        "KeepAlive": {"SuccessfulExit": False},
        "ThrottleInterval": 30,
        "EnvironmentVariables": {
            "MLX_MODEL_DIR": str(settings.model_dir),
            "MLX_ADAPTER_DIR": str(settings.adapter_dir),
            "MLX_SERVE_PYTHON": str(settings.python),
            "MLX_HOST": settings.host,
            "MLX_PORT": str(settings.port),
        },
        "StandardOutPath": str(settings.log_file),
        "StandardErrorPath": str(settings.error_log_file),
    })


def install_agent(settings: Settings, out: Callable[[str], None] = print) -> int:
    memory_hint(settings)
    if sys.platform != "darwin":
        out("Автозапуск описан для macOS (launchd). На других системах запустите "
            "`scripts/local_model.py serve` под systemd или другим супервизором.")
        return EX_CONFIG
    ok, output = verify(settings)
    if not ok:
        out(output or "Проверка модели не пройдена; автозапуск не включён.")
        return 1
    check_mlx_runtime(settings)
    ensure_cache_dir(out)
    AGENTS_DIR.mkdir(parents=True, exist_ok=True)
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    if agent_loaded():
        subprocess.run(["launchctl", "bootout", f"gui/{os.getuid()}/{LABEL}"], check=False)
    settings.plist_file.write_bytes(render_plist(settings))
    result = subprocess.run(["launchctl", "bootstrap", f"gui/{os.getuid()}", str(settings.plist_file)],
                            capture_output=True, text=True, check=False)
    if result.returncode != 0:
        out(f"launchctl bootstrap не сработал: {(result.stderr or result.stdout).strip()}")
        return 1
    out(f"Автозапуск включён: {settings.plist_file}")
    out("Сервер поднимается при входе в систему и после сбоя; журнал: " + str(settings.log_file))
    if wait_ready(settings, 240.0, out):
        return 0
    out("Агент загружен, но модель пока не ответила. Смотрите журнал: " + str(settings.log_file))
    return 1


def uninstall_agent(settings: Settings, out: Callable[[str], None] = print) -> int:
    if agent_loaded():
        subprocess.run(["launchctl", "bootout", f"gui/{os.getuid()}/{LABEL}"], check=False)
    settings.plist_file.unlink(missing_ok=True)
    settings.pid_file.unlink(missing_ok=True)
    out("Автозапуск выключен. Запуск вручную: scripts/local_model.py start")
    return 0


def serve(settings: Settings) -> int:
    """Передний план: проверка и `exec` сервера, чтобы супервизор видел один процесс."""
    memory_hint(settings)
    ok, output = verify(settings)
    if not ok:
        # Ошибка настройки не является сбоем сервера: код 0 не даёт launchd
        # перезапускать заведомо нерабочий запуск каждые полминуты.
        print(output or "Проверка модели не пройдена.", file=sys.stderr, flush=True)
        return 0
    print(f"Старт MLX: {settings.model_dir} + {settings.adapter_dir} на {settings.base_url}",
          flush=True)
    os.execv(str(settings.python), server_command(settings))
    return 1


def report_status(settings: Settings, out: Callable[[str], None] = print) -> int:
    ids = probe(settings, timeout=2.0)
    pid = read_pid(settings) or agent_pid()
    out(f"Адрес:       {settings.base_url}")
    out(f"Модель:      {', '.join(ids) if ids else 'не отвечает'}")
    if pid_alive(pid):
        process = str(pid)
    elif pid:
        process = f"не запущен (PID {pid} устарел)"
    else:
        process = "не запущен"
    out(f"Процесс:     {process}")
    out(f"Интерпретатор: {settings.python}")
    out(f"База:        {settings.model_dir}")
    out(f"Адаптер:     {settings.adapter_dir}")
    if agent_loaded():
        autostart = f"включён (launchd {LABEL})"
    elif agent_bootstrapped(settings):
        autostart = "включён в системе, но агент не загружен (сервер остановлен вручную)"
    else:
        autostart = "выключен"
    out(f"Автозапуск:  {autostart}")
    out(f"Журнал:      {settings.log_file}")
    return 0 if ids else 1


def run(argv: list[str], env: Mapping[str, str] | None = None,
        out: Callable[[str], None] = print) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--repo", type=Path, default=Path(__file__).resolve().parent.parent,
                        help="Корень репозитория (по умолчанию — каталог скрипта)")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("status", help="состояние сервера")
    start_cmd = commands.add_parser("start", help="запустить в фоне")
    start_cmd.add_argument("--wait", type=float, default=240.0, help="Сколько ждать ответа модели, с")
    commands.add_parser("stop", help="остановить")
    restart_cmd = commands.add_parser("restart", help="перезапустить")
    restart_cmd.add_argument("--wait", type=float, default=240.0)
    logs = commands.add_parser("logs", help="журнал")
    logs.add_argument("--lines", type=int, default=40)
    commands.add_parser("verify", help="проверить базу и адаптер")
    commands.add_parser("serve", help="работать в переднем плане")
    commands.add_parser("install-agent", help="включить автозапуск (launchd)")
    commands.add_parser("uninstall-agent", help="выключить автозапуск")
    args = parser.parse_args(argv)
    try:
        settings = load_settings(args.repo.resolve(), env)
        if args.command == "status":
            return report_status(settings, out)
        if args.command == "verify":
            ok, output = verify(settings)
            out(output or "Проверка модели не пройдена.")
            return 0 if ok else 1
        if args.command == "start":
            return start(settings, out, wait=args.wait)
        if args.command == "stop":
            return stop(settings, out)
        if args.command == "restart":
            stop(settings, out)
            return start(settings, out, wait=args.wait)
        if args.command == "logs":
            out(tail(settings.log_file, args.lines))
            return 0
        if args.command == "serve":
            return serve(settings)
        if args.command == "install-agent":
            return install_agent(settings, out)
        if args.command == "uninstall-agent":
            return uninstall_agent(settings, out)
    except ConfigError as exc:
        out(f"Настройка модели: {exc}")
        return EX_CONFIG
    return EX_CONFIG


def main() -> int:
    return run(sys.argv[1:])


if __name__ == "__main__":
    raise SystemExit(main())
