"""Полное локальное развёртывание ПоРукам одной командой на Mac с Apple Silicon.

Приложение — Docker Compose, обученная MLX/LoRA и Ollama — процессы хоста.
Рабочая .env не меняется. Повторный запуск не сбрасывает данные или пароли.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
import hashlib
import importlib.util
import json
import os
from pathlib import Path, PurePosixPath
import platform
import shutil
import socket
import subprocess
import sys
import tarfile
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
import venv

ROOT = Path(__file__).resolve().parents[1]
STATE = ROOT / ".cache/local-deploy"
SUPPORT = Path.home() / "Library/Application Support/PoRukam-LLM"
RELEASE = "https://github.com/NawOmen/R136a1/releases/download/ml-trained-current-20261022/"
DOCKER_DMG = "https://desktop.docker.com/mac/main/arm64/Docker.dmg"
OLLAMA_ZIP = "https://ollama.com/download/Ollama-darwin.zip"
UV_VERSION = "0.13.6"
MODEL = "qwen3.5:9b"
ACCOUNTS = (("Покупатель", "DEMO", "buyer@show.porukam.ru"),
            ("Поставщик", "SELLER", "seller@show.porukam.ru"),
            ("Второй поставщик", "SELLER2", "supplier@demo.ru"),
            ("Администратор", "ADMIN", "admin@show.porukam.ru"))


def load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


recording = load("porukam_recording_deploy", ROOT / "scripts/recording-demo.py")
local_model = load("porukam_local_deploy", ROOT / "scripts/local_model.py")


class DeployError(Exception):
    """Понятная причина остановки установки без ложного сообщения об успехе."""


def run(args, **kwargs):
    kwargs.setdefault("check", True)
    return subprocess.run([str(a) for a in args], cwd=ROOT, **kwargs)


def digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(8 * 1024**2), b""):
            h.update(chunk)
    return h.hexdigest()


def atomic_private(path: Path, content: bytes):
    if path.is_symlink():
        raise DeployError(f"Отказ записи через символическую ссылку: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".deploy-")
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(content)
        os.replace(tmp, path)
    finally:
        Path(tmp).unlink(missing_ok=True)


@contextmanager
def install_lock():
    import fcntl
    STATE.mkdir(parents=True, exist_ok=True)
    with (STATE / "install.lock").open("a") as stream:
        try:
            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise DeployError("Другой экземпляр установщика уже работает") from exc
        yield


def supported_host():
    if platform.system() != "Darwin" or platform.machine() != "arm64":
        raise DeployError("Полный запуск обученной LoRA требует Mac с Apple Silicon (arm64). "
                          "Linux, Windows и Intel Mac не поддерживают текущие MLX-веса. "
                          "Базовая модель не подставляется вместо обученной.")
    if int(platform.mac_ver()[0].split(".")[0]) < 14:
        raise DeployError("Для локальных моделей нужна macOS 14 или новее")


def download(url: str, path: Path, *, sha256: str = "", size: int = 0):
    if path.is_file() and sha256 and digest(path) == sha256 and (not size or path.stat().st_size == size):
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    part = path.with_name(path.name + ".part")
    print(f"Загрузка: {path.name}", flush=True)
    # Ни пароли стенда, ни исходные пользовательские материалы в запрос не входят.
    req = urllib.request.Request(url, headers={"User-Agent": "PoRukam-local-deploy/1"})
    try:
        with urllib.request.urlopen(req, timeout=60) as source, part.open("wb") as target:
            received, notice = 0, time.monotonic()
            for block in iter(lambda: source.read(1024**2), b""):
                target.write(block)
                received += len(block)
                if time.monotonic() - notice >= 20:
                    print(f"{path.name}: загружено {received // 1024**2} МБ", flush=True)
                    notice = time.monotonic()
        if size and part.stat().st_size != size:
            raise DeployError(f"Неполная загрузка: {path.name}; запустите команду повторно")
        if sha256 and digest(part) != sha256:
            raise DeployError(f"SHA256 не совпадает: {path.name}; файл не будет использован")
        os.replace(part, path)
    finally:
        part.unlink(missing_ok=True)


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise DeployError("Локальная проверка получила перенаправление на другой адрес")


def local_json(url: str, body=None, *, timeout=10):
    parsed = urllib.parse.urlsplit(url)
    if parsed.hostname not in {"127.0.0.1", "localhost"} or parsed.scheme != "http" or parsed.username:
        raise DeployError("Проверки и пароли разрешено отправлять только на локальный стенд")
    request = urllib.request.Request(url, data=None if body is None else json.dumps(body).encode(),
                                     headers={"Content-Type": "application/json"})
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
    with opener.open(request, timeout=timeout) as response:
        return json.loads(response.read(2 * 1024**2))


def wait_for(label, probe, *, seconds=300):
    deadline = time.monotonic() + seconds
    last_notice = 0
    while time.monotonic() < deadline:
        try:
            if probe():
                return
        except (OSError, ValueError):
            pass
        if time.monotonic() - last_notice >= 20:
            print(f"Ожидаю: {label}…", flush=True)
            last_notice = time.monotonic()
        time.sleep(2)
    raise DeployError(f"Не готово: {label}. Исправьте причину и повторите ту же команду.")


def ensure_docker():
    apps = [Path("/Applications/Docker.app"), Path.home() / "Applications/Docker.app"]
    binary = shutil.which("docker")
    app = next((p for p in apps if p.is_dir()), None)
    daemon_ready = bool(binary and run([binary, "info"], check=False, capture_output=True, timeout=15).returncode == 0)
    if not daemon_ready and not app:
        dmg = STATE / "Docker.dmg"
        download(DOCKER_DMG, dmg)
        mount = STATE / "docker-mount"
        mount.mkdir(exist_ok=True)
        run(["hdiutil", "attach", dmg, "-nobrowse", "-mountpoint", mount])
        try:
            app = apps[1]
            app.parent.mkdir(parents=True, exist_ok=True)
            run(["ditto", mount / "Docker.app", app])
            # Проверка подписи без отключения Gatekeeper и без принятия лицензии за пользователя.
            run(["codesign", "--verify", "--deep", "--strict", app])
        finally:
            run(["hdiutil", "detach", mount])
    if app:
        binary = str(app / "Contents/Resources/bin/docker")
    if not binary:
        raise DeployError("Не найден Docker CLI")
    os.environ["PATH"] = str(Path(binary).parent) + os.pathsep + os.environ.get("PATH", "")
    if app:
        print("Открываю Docker Desktop. При первом запуске подтвердите его лицензию в системном окне.", flush=True)
        run(["open", "-a", app])
    wait_for("Docker Desktop", lambda: run([binary, "info"], capture_output=True, check=False, timeout=15).returncode == 0)
    run([binary, "compose", "version"], capture_output=True)
    # Не допускаем случайного развёртывания через удалённый DOCKER_HOST/context.
    endpoint = run([binary, "context", "inspect", "--format", '{{(index .Endpoints "docker").Host}}'],
                   capture_output=True, text=True).stdout.strip()
    if os.environ.get("DOCKER_HOST") or not endpoint.startswith("unix://"):
        raise DeployError("Нужен локальный Docker context с unix-сокетом, без DOCKER_HOST")


def configuration():
    if recording.ENV.is_symlink():
        raise DeployError(".env.recording не должна быть символической ссылкой")
    if not recording.ENV.exists():
        # Потерянный .env не заменяем новыми паролями поверх существующего тома БД.
        volumes = run(["docker", "volume", "ls", "--filter", "label=com.docker.compose.project=" + recording.PROJECT,
                       "--format", "{{.Name}}"], capture_output=True, text=True).stdout
        if volumes.strip():
            raise DeployError("Есть тома r136-recording, но нет .env.recording. Восстановите исходный файл "
                              "с паролями. Данные и пароль PostgreSQL не менялись.")
        recording.initialize()
    recording.ENV.chmod(0o600)
    values = local_model.read_dotenv(recording.ENV)
    recording.configuration()  # Проверяет принадлежность базы и идентичности покупателя/продавца.
    if values.get("LOCAL_LLM_BACKEND") != "mlx" or values.get("ASSISTANT_LLM_BACKEND") != "ollama":
        raise DeployError("В .env.recording нужны LOCAL_LLM_BACKEND=mlx и ASSISTANT_LLM_BACKEND=ollama")
    for key, port in (("WEB_PORT", 3000), ("GATEWAY_AUTH_PORT", 8001), ("MARKETPLACE_PORT", 8002),
                      ("LLM_GATEWAY_PORT", 8003), ("POSTGRES_PORT", 5433), ("PGADMIN_PORT", 5050), ("MINIO_PORT", 9000)):
        if values.get(key, str(port)) != str(port):
            raise DeployError(f"Для этого установщика нужен стандартный {key}={port}")
    values["DEEPSEEK_API_KEY"] = ""  # Полный локальный режим, без внешнего провайдера из shell.
    for _, prefix, default in ACCOUNTS:
        key = "SEED_" + prefix
        if not values.get(key + "_EMAIL"):
            values[key + "_EMAIL"] = default
        # Старый seed использовал пароль первого поставщика и фиксированный второй email.
        if prefix == "SELLER2" and not values.get(key + "_PASSWORD"):
            values[key + "_PASSWORD"] = values["SEED_SELLER_PASSWORD"]
        if len(values.get(key + "_PASSWORD", "")) < 16:
            raise DeployError("Не задан пароль аккаунта: " + key)
    return values


def save_configuration(values):
    for key, value in values.items():
        if any(c in value for c in "\r\n$"):
            raise DeployError(f"Недопустимый перевод строки или $ в настройке {key}")
    atomic_private(recording.ENV, ("# Локальный синтетический стенд. Секреты не публиковать.\n" +
                                   "".join(f"{k}={v}\n" for k, v in values.items())).encode())


def ensure_mlx_python():
    destination = SUPPORT / "mlx-venv"
    python = destination / "bin/python"
    if not python.exists():
        # uv — только инструмент установки, не зависимость приложения. Системный Python не меняем.
        bootstrap = STATE / "bootstrap-python"
        if not (bootstrap / "bin/python").exists():
            venv.create(bootstrap, with_pip=True)
        bootstrap_python = bootstrap / "bin/python"
        run([bootstrap_python, "-m", "pip", "install", "--disable-pip-version-check", "uv==" + UV_VERSION])
        uv = bootstrap / "bin/uv"
        env = dict(os.environ, UV_PYTHON_INSTALL_DIR=str(SUPPORT / "python"), UV_PYTHON_BIN_DIR=str(SUPPORT / "bin"))
        run([uv, "venv", "--python", "3.13", "--seed", destination], env=env)
    requirements = ROOT / "ml/training/porukam-trained-current/requirements-serving.txt"
    stamp = destination / ".porukam-requirements.sha256"
    fingerprint = digest(requirements)
    if not stamp.exists() or stamp.read_text().strip() != fingerprint:
        run([python, "-m", "pip", "install", "--disable-pip-version-check", "-r", requirements])
        run([python, "-m", "pip", "check"])
        atomic_private(stamp, fingerprint.encode())
    run([python, "-c", "import mlx.core, mlx_lm.server"])
    return python


def safe_name(name):
    path = PurePosixPath(name)
    if path.is_absolute() or ".." in path.parts or "\\" in name:
        raise DeployError("Недопустимый путь в комплекте модели")
    return path


def install_adapter(destination):
    metadata = json.loads((ROOT / "docs/research/ml-current/archive.json").read_text())
    files = json.loads((ROOT / "docs/research/ml-current/files.json").read_text())["files"]
    if all((destination / f["path"]).is_file() and digest(destination / f["path"]) == f["sha256"] for f in files):
        return
    archive = STATE / metadata["asset"]
    download(RELEASE + metadata["asset"], archive, sha256=metadata["sha256"], size=metadata["bytes"])
    with tempfile.TemporaryDirectory(dir=STATE) as tmp, tarfile.open(archive, "r:gz") as tar:
        # Только ожидаемые обычные файлы, без extractall, ссылок, устройств и выхода из каталога.
        by_name = {}
        for member in tar.getmembers():
            name = str(safe_name(member.name))
            if member.isfile():
                by_name[name] = member
            elif not member.isdir():
                raise DeployError("Комплект модели содержит недопустимую ссылку или устройство")
        for f in files:
            name = str(safe_name(f["path"]))
            matches = [m for k, m in by_name.items() if k == name or k.endswith("/" + name)]
            if len(matches) != 1 or matches[0].size != f["bytes"]:
                raise DeployError("Состав комплекта модели не совпал: " + name)
            target = Path(tmp) / name
            target.parent.mkdir(parents=True, exist_ok=True)
            with tar.extractfile(matches[0]) as source, target.open("wb") as stream:
                shutil.copyfileobj(source, stream)
            if digest(target) != f["sha256"]:
                raise DeployError("SHA256 файла адаптера не совпал: " + name)
        destination.mkdir(parents=True, exist_ok=True)
        for f in files:
            name = safe_name(f["path"])
            atomic_private(destination / name, (Path(tmp) / name).read_bytes())


def install_base(destination):
    manifest_path = ROOT / "ml/training/porukam-trained-current/base-download-manifest.json"
    manifest = json.loads(manifest_path.read_text())
    lock = json.loads((ROOT / "infra/models.lock.json").read_text())["local_llm"]
    if manifest["sha"] != lock["base_revision"]:
        raise DeployError("Ревизия манифеста базовой модели не совпадает с models.lock.json")
    cached = destination / "download-manifest.json"
    same_revision = cached.is_file() and json.loads(cached.read_text()).get("sha") == manifest["sha"]
    for item in manifest["siblings"]:
        name = safe_name(item["rfilename"])
        path = destination / name
        lfs = item.get("lfs", {})
        if path.is_file() and not lfs and same_revision:
            continue
        url = ("https://huggingface.co/" + lock["base_model"] + "/resolve/" +
               lock["base_revision"] + "/" + urllib.parse.quote(str(name), safe="/"))
        download(url, path, sha256=lfs.get("sha256", ""), size=lfs.get("size", 0))
    atomic_private(destination / "download-manifest.json", manifest_path.read_bytes())


def ensure_ollama():
    candidates = [Path("/Applications/Ollama.app/Contents/Resources/ollama"),
                  Path.home() / "Applications/Ollama.app/Contents/Resources/ollama",
                  SUPPORT / "Ollama.app/Contents/Resources/ollama"]
    found = shutil.which("ollama")
    binary = Path(found) if found else next((p for p in candidates if p.is_file()), None)
    if binary is None:
        archive = STATE / "Ollama-darwin.zip"
        download(OLLAMA_ZIP, archive)
        with tempfile.TemporaryDirectory(dir=STATE) as tmp:
            run(["ditto", "-x", "-k", archive, tmp])
            app = Path(tmp) / "Ollama.app"
            run(["codesign", "--verify", "--deep", "--strict", app])
            run(["ditto", app, SUPPORT / "Ollama.app"])
        binary = candidates[-1]
    try:
        local_json("http://127.0.0.1:11434/api/tags")
    except OSError:
        SUPPORT.mkdir(parents=True, exist_ok=True)
        env = dict(os.environ, OLLAMA_HOST="127.0.0.1:11434", OLLAMA_NO_CLOUD="1")
        with (SUPPORT / "ollama.log").open("a") as log:
            process = subprocess.Popen([str(binary), "serve"], env=env, stdin=subprocess.DEVNULL,
                                       stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
        atomic_private(STATE / "ollama.pid", str(process.pid).encode())
    wait_for("Ollama на хосте", lambda: bool(local_json("http://127.0.0.1:11434/api/version")))
    env = dict(os.environ, OLLAMA_HOST="127.0.0.1:11434", OLLAMA_NO_CLOUD="1")
    run([binary, "pull", MODEL], env=env)
    tags = local_json("http://127.0.0.1:11434/api/tags")
    if MODEL not in {m.get("name") for m in tags.get("models", [])}:
        raise DeployError("Ollama не подтвердила загрузку qwen3.5:9b")
    # Проверяем генерацию, а не только наличие имени модели. Освобождаем память перед MLX.
    result = local_json("http://127.0.0.1:11434/api/chat", {"model": MODEL, "stream": False,
                        "messages": [{"role": "user", "content": "Ответь одним словом: готово"}],
                        "think": False, "keep_alive": 0, "options": {"num_predict": 16}}, timeout=300)
    if not str(result.get("message", {}).get("content", "")).strip():
        raise DeployError("Ollama доступна, но проверка генерации не дала ответа")


def model_environment(values):
    # Shell/.env рабочего стенда не должны подменить настройки модели отдельного проекта.
    return dict(os.environ, **{k: values[k] for k in ("MLX_MODEL_DIR", "MLX_ADAPTER_DIR", "MLX_SERVE_PYTHON")},
                MLX_HOST="127.0.0.1", MLX_PORT="8080")


def ensure_mlx(values):
    settings = local_model.settings_from(model_environment(values), ROOT)
    ok, output = local_model.verify(settings)
    if not ok:
        raise DeployError("Проверка базы и LoRA не прошла: " + output)
    if local_model.probe(settings):
        pid = local_model.read_pid(settings) or local_model.agent_pid()
        cmd = (run(["ps", "-p", str(pid), "-o", "command="], capture_output=True, text=True, check=False).stdout
               if pid else "")
        expected = [str(settings.build_script), str(settings.model_dir), str(settings.adapter_dir)]
        if not pid or not all(item in cmd for item in expected):
            raise DeployError("Порт MLX 8080 занят моделью, происхождение которой установщик не подтвердил. "
                              "Остановите этот процесс и повторите команду; чужой процесс не завершён.")
    run([sys.executable, ROOT / "scripts/local_model.py", "start"], env=model_environment(values))
    run([sys.executable, ROOT / "scripts/local_model.py", "status"], env=model_environment(values))


def check_ports():
    owned = recording.compose("ps", "--status", "running", "--services", capture_output=True, text=True).stdout.split()
    services = {3000: "web", 8001: "gateway-auth", 8002: "marketplace", 8003: "llm-gateway",
                5433: "postgres", 5050: "pgadmin", 9000: "minio", 9001: "minio"}
    for port, service in services.items():
        with socket.socket() as sock:
            if sock.connect_ex(("127.0.0.1", port)) == 0 and service not in owned:
                raise DeployError(f"Порт {port} занят другим приложением. Остановите его с сохранением данных.")


def verify_accounts(values, *, show=False):
    address = recording.compose("port", "gateway-auth", "8001", capture_output=True, text=True).stdout.strip()
    if address != "127.0.0.1:8001":
        raise DeployError("Не подтверждено, что localhost:8001 обслуживает Auth проекта r136-recording")
    for role, prefix, default in ACCOUNTS:
        email = values.get("SEED_" + prefix + "_EMAIL", default)
        password = values.get("SEED_" + prefix + "_PASSWORD", values["SEED_SELLER_PASSWORD"])
        try:
            data = local_json("http://127.0.0.1:8001/api/v1/auth/login", {"email": email, "password": password})
            if not data.get("access_token"):
                raise ValueError("Нет токена")
        except (OSError, ValueError) as exc:
            raise DeployError(f"Не подтверждён вход {email}. Пароль существующего аккаунта мог быть изменён. "
                              "Установщик не сбрасывает его автоматически.") from exc
    if show:
        print("\nСайт: http://localhost:3000/login\nЛокальные учётные данные (не публикуйте вывод терминала):")
        for role, prefix, default in ACCOUNTS:
            print(f"{role}: {values.get('SEED_' + prefix + '_EMAIL', default)}")
            print("Пароль: " + values.get("SEED_" + prefix + "_PASSWORD", values["SEED_SELLER_PASSWORD"]))
        print("Пароли сохранены в .env.recording (0600). Инструкция записи: docs/contest/final-demo.md")


def prepare_once():
    recording.assert_owned_database()
    # Подготовка один раз: повторный запуск не обновляет остаток/цену поверх начатой закупки.
    marker = STATE / "prepared.json"
    instance = recording.compose("exec", "-T", "postgres", "sh", "-c",
                                 'exec psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Atc "SELECT system_identifier FROM pg_control_system()"',
                                 capture_output=True, text=True).stdout.strip()
    if not instance.isdigit():
        raise DeployError("PostgreSQL не подтвердил идентификатор локального экземпляра")
    if marker.exists() and json.loads(marker.read_text()).get("instance") == instance:
        return
    count = recording.compose("exec", "-T", "postgres", "sh", "-c",
                              'exec psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Atc "SELECT count(*) FROM marketplace.needs"',
                              capture_output=True, text=True).stdout.strip()
    if count != "0":
        print("В базе есть потребности: сохраняю их, начальные условия повторно не загружаю.")
        return
    recording.compose("exec", "-T", "marketplace", "python", "prepare_recording.py")
    atomic_private(marker, json.dumps({"project": recording.PROJECT, "database": recording.DATABASE, "instance": instance}).encode())


def deploy():
    supported_host()
    print("Полный запуск: приложение в Docker, MLX/LoRA и Ollama на Mac.\n"
          "Нужны интернет, место для моделей и образов (рекомендуем 40 ГБ) и запас памяти для двух моделей.", flush=True)
    ensure_docker()
    values = configuration()
    save_configuration(values)
    # До больших скачиваний проверяем свободные порты, рабочую базу не останавливаем.
    check_ports()
    python = ensure_mlx_python()
    previous = local_model.read_dotenv(ROOT / ".env")
    base = Path(values.get("MLX_MODEL_DIR") or previous.get("MLX_MODEL_DIR") or SUPPORT / "model-9b-4bit").expanduser()
    adapter = Path(values.get("MLX_ADAPTER_DIR") or previous.get("MLX_ADAPTER_DIR") or SUPPORT / "porukam-trained-current").expanduser()
    install_base(base)
    install_adapter(adapter)
    values.update(MLX_MODEL_DIR=str(base.resolve()), MLX_ADAPTER_DIR=str(adapter.resolve()), MLX_SERVE_PYTHON=str(python),
                  MLX_BASE_URL="http://host.docker.internal:8080", OLLAMA_DOCKER_BASE_URL="http://host.docker.internal:11434")
    save_configuration(values)
    ensure_ollama()
    ensure_mlx(values)
    print("Сборка и запуск сервисов, миграции и синтетический каталог…", flush=True)
    recording.compose("up", "-d", "--build", "--wait", "--wait-timeout", "600")
    prepare_once()
    print("Подготовка локального распознавания аудио Whisper small…", flush=True)
    recording.compose("exec", "-T", "llm-gateway", "python", "-c",
                      'from faster_whisper.utils import download_model; download_model("small")')
    # Проверяем модели по тем адресам, которые реально использует контейнер Gateway.
    recording.compose("exec", "-T", "llm-gateway", "python", "-c",
                      'import urllib.request; '
                      'urllib.request.urlopen("http://host.docker.internal:8080/v1/models", timeout=20).read(); '
                      'urllib.request.urlopen("http://host.docker.internal:11434/api/tags", timeout=20).read()')
    run([sys.executable, ROOT / "scripts/check-final-demo.py"])
    verify_accounts(values, show=True)
    print("\nСервисы, каталог, входы и генерация моделей проверены. Сквозная закупка автоматически не создавалась.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--credentials", action="store_true", help="Повторно проверить входы и вывести пароли локального стенда")
    group.add_argument("--check", action="store_true", help="Только проверить совместимость платформы, без установки")
    args = parser.parse_args()
    if args.check:
        supported_host()
        print("Mac с Apple Silicon подходит. Установка: python3 scripts/deploy-local.py")
        return
    supported_host()  # В том числе до fcntl: Windows получает понятную причину отказа.
    os.umask(0o077)
    with install_lock():
        if args.credentials:
            values = local_model.read_dotenv(recording.ENV)
            recording.configuration()
            verify_accounts(values, show=True)
        else:
            deploy()


if __name__ == "__main__":
    try:
        main()
    except (DeployError, OSError, ValueError, subprocess.SubprocessError) as exc:
        # CalledProcessError не содержит пароли: их не передаём в аргументах команд.
        raise SystemExit(f"Развёртывание остановлено: {exc}") from exc
