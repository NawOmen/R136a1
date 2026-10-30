"""Полное локальное развёртывание ПоРукам одной командой на macOS и Linux.

Приложение — Docker Compose, обученная MLX/LoRA и Ollama — процессы хоста.
Рабочая .env не меняется. Повторный запуск не сбрасывает данные или пароли.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
import hashlib
import importlib.util
import ipaddress
import json
import os
from pathlib import Path, PurePosixPath
import platform
import select
import signal
import shutil
import socket
import socketserver
import subprocess
import sys
import tarfile
import tempfile
import time
import threading
import urllib.error
import urllib.parse
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
STATE = ROOT / ".cache/local-deploy"
SUPPORT = (Path.home() / "Library/Application Support/PoRukam-LLM" if sys.platform == "darwin"
           else Path.home() / ".local/share/PoRukam-LLM")
RELEASE = "https://github.com/NawOmen/R136a1/releases/download/ml-trained-current-20261022/"
DOCKER_DMG = "https://desktop.docker.com/mac/main/arm64/Docker.dmg"
OLLAMA_ZIP = "https://ollama.com/download/Ollama-darwin.zip"
UV_VERSION = "0.13.6"
MODEL = "qwen3.5:9b"
DOCKER_SUDO = False
SUDO_REFRESH = False
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
    if args[0] == "docker" and DOCKER_SUDO:
        args = ["sudo", *args]
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
    system, machine = platform.system(), platform.machine()
    if system == "Linux" and machine in {"x86_64", "aarch64", "arm64"}:
        libc, version = platform.libc_ver()
        if libc != "glibc" or tuple(map(int, version.split(".")[:2])) < (2, 35):
            raise DeployError("Нужен Linux с glibc 2.35+ (например, Ubuntu 22.04+ или Debian 12+)")
        return
    if system != "Darwin" or machine != "arm64":
        raise DeployError("Поддерживаются macOS на Apple Silicon и Linux x86_64/arm64")
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


def as_root(args):
    global SUDO_REFRESH
    if os.geteuid() == 0:
        return run(args)
    if not shutil.which("sudo"):
        raise DeployError("Для установки Docker нужен sudo или запуск с правами администратора")
    result = run(["sudo", *args])
    if not SUDO_REFRESH:
        def refresh():
            while True:
                time.sleep(45)
                subprocess.run(["sudo", "-n", "-v"], stdin=subprocess.DEVNULL,
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        threading.Thread(target=refresh, daemon=True).start()
        SUDO_REFRESH = True
    return result


def ensure_linux_docker():
    global DOCKER_SUDO
    if os.environ.get("DOCKER_HOST"):
        raise DeployError("Уберите DOCKER_HOST: установщик работает только с локальным Docker")
    if not shutil.which("docker"):
        installer = STATE / "docker-install.sh"
        download("https://get.docker.com", installer)
        as_root(["sh", installer])
    if run(["docker", "info"], check=False, capture_output=True, timeout=20).returncode:
        print("Запускаю Docker Engine. Linux может запросить пароль sudo.", flush=True)
        as_root(["systemctl", "start", "docker"] if Path("/run/systemd/system").is_dir()
                else ["service", "docker", "start"])
        if run(["docker", "info"], check=False, capture_output=True, timeout=20).returncode:
            as_root(["docker", "info"])
            DOCKER_SUDO = os.geteuid() != 0
    run(["docker", "info"], capture_output=True)
    if run(["docker", "compose", "version"], check=False, capture_output=True).returncode:
        # Не переустанавливаем существующий движок из другого дистрибутивного пакета.
        with urllib.request.urlopen("https://api.github.com/repos/docker/compose/releases/latest", timeout=30) as r:
            release = json.load(r)
        arch = "aarch64" if platform.machine() in {"arm64", "aarch64"} else "x86_64"
        asset = next(a for a in release["assets"] if a["name"] == "docker-compose-linux-" + arch)
        plugin = STATE / "docker-compose"
        download(asset["browser_download_url"], plugin, sha256=(asset.get("digest") or "").removeprefix("sha256:"))
        # Системный каталог нужен также для sudo docker, если группа docker ещё не применена.
        as_root(["install", "-D", "-m", "0755", plugin, "/usr/local/lib/docker/cli-plugins/docker-compose"])
    run(["docker", "compose", "version"], capture_output=True)
    endpoint = run(["docker", "context", "inspect", "--format", '{{(index .Endpoints "docker").Host}}'],
                   capture_output=True, text=True).stdout.strip()
    if not endpoint.startswith("unix://"):
        raise DeployError("Нужен локальный Docker context с unix-сокетом")


def ensure_docker():
    if platform.system() == "Linux":
        return ensure_linux_docker()
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
    values["LOCAL_DOCKER_SUDO"] = "true" if DOCKER_SUDO else "false"
    if platform.system() == "Linux":
        values["MLX_TIMEOUT_SECONDS"] = "1800"
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
        uv = install_uv()
        env = dict(os.environ, UV_PYTHON_INSTALL_DIR=str(SUPPORT / "python"), UV_PYTHON_BIN_DIR=str(SUPPORT / "bin"))
        run([uv, "venv", "--python", "3.13", "--seed", destination], env=env)
    requirements = ROOT / "ml/training/porukam-trained-current/requirements-serving.txt"
    packages = (["mlx[cpu]==0.32.3", "mlx-lm==0.32.0"] if platform.system() == "Linux" else None)
    stamp = destination / ".porukam-requirements.sha256"
    fingerprint = hashlib.sha256("\n".join(packages).encode()).hexdigest() if packages else digest(requirements)
    if not stamp.exists() or stamp.read_text().strip() != fingerprint:
        run([python, "-m", "pip", "install", "--disable-pip-version-check", *(packages or ["-r", requirements])])
        run([python, "-m", "pip", "check"])
        atomic_private(stamp, fingerprint.encode())
    run([python, "-c", "import mlx.core, mlx_lm.server"])
    return python


def install_uv():
    """Готовый uv работает и без системных pip/ensurepip/python3-venv."""
    binary = STATE / "uv" / "uv"
    if binary.is_file():
        return binary
    arch = "aarch64" if platform.machine() in {"arm64", "aarch64"} else "x86_64"
    target = arch + ("-apple-darwin" if platform.system() == "Darwin" else "-unknown-linux-gnu")
    name = "uv-" + target
    url = f"https://github.com/astral-sh/uv/releases/download/{UV_VERSION}/{name}.tar.gz"
    archive = STATE / (name + ".tar.gz")
    checksum = STATE / (name + ".sha256")
    download(url + ".sha256", checksum)
    expected = checksum.read_text().split()[0]
    if len(expected) != 64 or any(c not in "0123456789abcdef" for c in expected):
        raise DeployError("Не получена контрольная сумма uv")
    download(url, archive, sha256=expected)
    with tarfile.open(archive, "r:gz") as tar:
        member = tar.getmember(name + "/uv")
        if not member.isfile():
            raise DeployError("Недопустимый файл uv в архиве")
        with tar.extractfile(member) as stream:
            atomic_private(binary, stream.read())
    binary.chmod(0o700)
    return binary


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


def install_linux_ollama():
    destination = SUPPORT / "ollama-native"
    binary = destination / "bin/ollama"
    if binary.is_file():
        return binary
    with urllib.request.urlopen("https://api.github.com/repos/ollama/ollama/releases/latest", timeout=30) as r:
        release = json.load(r)
    arch = "arm64" if platform.machine() in {"arm64", "aarch64"} else "amd64"
    asset = next(a for a in release["assets"] if a["name"] == f"ollama-linux-{arch}.tar.zst")
    archive = STATE / asset["name"]
    download(asset["browser_download_url"], archive, size=asset["size"],
             sha256=(asset.get("digest") or "").removeprefix("sha256:"))
    python = SUPPORT / "mlx-venv/bin/python"
    run([python, "-m", "pip", "install", "zstandard==0.25.0"])
    with tempfile.TemporaryDirectory(dir=STATE) as tmp:
        run([python, "-c", 'import sys,tarfile,zstandard; '
             's=zstandard.ZstdDecompressor().stream_reader(open(sys.argv[1],"rb")); '
             't=tarfile.open(fileobj=s,mode="r|"); t.extractall(sys.argv[2],filter="data")', archive, tmp])
        shutil.copytree(tmp, destination, symlinks=True, dirs_exist_ok=True)
    if not binary.is_file():
        raise DeployError("В комплекте Ollama не найден bin/ollama")
    return binary


def ensure_ollama():
    candidates = [Path("/Applications/Ollama.app/Contents/Resources/ollama"),
                  Path.home() / "Applications/Ollama.app/Contents/Resources/ollama",
                  SUPPORT / "Ollama.app/Contents/Resources/ollama"]
    found = shutil.which("ollama")
    binary = Path(found) if found else next((p for p in candidates if p.is_file()), None)
    if platform.system() == "Linux" and not found:
        binary = install_linux_ollama()
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
    tags = local_json("http://127.0.0.1:11434/api/tags")
    if MODEL not in {m.get("name") for m in tags.get("models", [])}:
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


class ModelRelay(socketserver.BaseRequestHandler):
    def handle(self):
        try:
            with socket.create_connection(("127.0.0.1", self.server.server_address[1]), timeout=10) as upstream:
                peers = [self.request, upstream]
                while True:
                    readable, _, _ = select.select(peers, [], [], 1900)
                    if not readable:
                        return
                    for source in readable:
                        data = source.recv(65536)
                        if not data:
                            return
                        (upstream if source is self.request else self.request).sendall(data)
        except OSError:
            return
class ModelProxyServer(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True


def host_proxy(address):
    """Приватный Docker bridge -> loopback. Обе модели остаются процессами хоста."""
    ip = ipaddress.ip_address(address)
    if not ip.is_private or ip.is_loopback or ip.is_multicast or ip.is_unspecified or ip.version != 4:
        raise DeployError("Для связи моделей нужен приватный IPv4 Docker bridge")
    with ModelProxyServer((address, 8080), ModelRelay) as mlx, ModelProxyServer((address, 11434), ModelRelay) as ollama:
        threading.Thread(target=mlx.serve_forever, daemon=True).start()
        ollama.serve_forever()


def ensure_host_bridge():
    if platform.system() != "Linux":
        return
    operating_system = run(["docker", "info", "--format", "{{.OperatingSystem}}"],
                           capture_output=True, text=True).stdout
    if "Docker Desktop" in operating_system:
        return  # Desktop сам связывает host.docker.internal с хостом, как на macOS.
    bridge = run(["docker", "network", "inspect", "bridge", "--format", '{{(index .IPAM.Config 0).Gateway}}'],
                 capture_output=True, text=True).stdout.strip()
    marker = STATE / "host-proxy.json"
    if marker.exists():
        saved = json.loads(marker.read_text())
        pid = int(saved["pid"])
        command = run(["ps", "-p", str(pid), "-o", "command="], check=False, capture_output=True, text=True).stdout
        owned = str(Path(__file__).resolve()) in command and "--host-proxy " + saved["bridge"] in command
        if owned and saved["bridge"] == bridge:
            return
        if owned:
            os.kill(pid, signal.SIGTERM)
    with (STATE / "host-proxy.log").open("a") as log:
        child = subprocess.Popen([sys.executable, str(Path(__file__).resolve()), "--host-proxy", bridge],
                                 stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
    def ready():
        if child.poll() is not None:
            raise DeployError("Не удалось связать модели с Docker: .cache/local-deploy/host-proxy.log")
        for port in (8080, 11434):
            with socket.create_connection((bridge, port), timeout=2):
                pass
        return True
    wait_for("Связь моделей с Docker", ready, seconds=15)
    atomic_private(marker, json.dumps({"pid": child.pid, "bridge": bridge}).encode())


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
    print("Полный запуск: приложение в Docker, MLX/LoRA и Ollama на хосте.\n"
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
    ensure_host_bridge()
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
    parser.add_argument("--host-proxy", help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.host_proxy:
        host_proxy(args.host_proxy)
        return
    if args.check:
        supported_host()
        print("Платформа подходит. Установка: python3 scripts/deploy-local.py")
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
