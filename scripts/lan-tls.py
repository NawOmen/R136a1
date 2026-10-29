"""Локальный удостоверяющий центр и сертификат для доступа с других устройств.

Сайт открывается в локальной сети только по HTTPS: браузер другого устройства должен
доверять сертификату. Скрипт один раз создаёт свой CA вне Git, выпускает сертификат
на текущий адрес машины и печатает, что установить на телефоне или ноутбуке.

Пример:
    python3 scripts/lan-tls.py --directory "$HOME/Library/Application Support/PoRukam-LLM/tls"

Ключи и сертификаты не попадают в репозиторий: каталог задаётся оператором и должен
лежать вне Git. Частный ключ CA не покидает машину; на устройства переносится только
`ca.pem`.
"""
from __future__ import annotations

import argparse
import ipaddress
import os
import shutil
import socket
import subprocess
import sys
import tempfile
from pathlib import Path

DEFAULT_HOSTNAME = "porukam.local"
RENEW_BEFORE_DAYS = 30


def private_ipv4(values: list[str]) -> list[str]:
    """Оставить только приватные IPv4 без дублей, сохранив порядок."""
    result: list[str] = []
    for value in values:
        try:
            address = ipaddress.IPv4Address(value.strip())
        except ValueError:
            continue
        if address.is_private and not address.is_loopback and str(address) not in result:
            result.append(str(address))
    return result


def detect_addresses() -> list[str]:
    """Адреса машины в локальной сети: маршрут по умолчанию и имя хоста."""
    found: list[str] = []
    try:
        probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            probe.connect(("8.8.8.8", 80))  # пакеты не отправляются, только выбор маршрута
            found.append(probe.getsockname()[0])
        finally:
            probe.close()
    except OSError:
        pass
    try:
        found.extend(info[4][0] for info in socket.getaddrinfo(socket.gethostname(), None)
                     if info[0] == socket.AF_INET)
    except OSError:
        pass
    return private_ipv4(found)


def san_entries(addresses: list[str], hostname: str) -> list[str]:
    """SAN: адреса сети плюс loopback и локальное имя, чтобы сертификат работал везде."""
    entries = [f"IP:{address}" for address in private_ipv4(addresses)]
    entries += ["IP:127.0.0.1", "DNS:localhost", f"DNS:{hostname}"]
    seen: list[str] = []
    for entry in entries:
        if entry not in seen:
            seen.append(entry)
    return seen


def certificate_fresh(certificate: Path) -> bool:
    """Действует ли сертификат ещё хотя бы RENEW_BEFORE_DAYS дней."""
    if not certificate.is_file():
        return False
    result = subprocess.run(["openssl", "x509", "-checkend", str(RENEW_BEFORE_DAYS * 86_400),
                             "-noout", "-in", str(certificate)], capture_output=True, text=True, check=False)
    return result.returncode == 0


def current_sans(certificate: Path) -> set[str]:
    if not certificate.is_file() or not shutil.which("openssl"):
        return set()
    result = subprocess.run(["openssl", "x509", "-noout", "-ext", "subjectAltName", "-in", str(certificate)],
                            capture_output=True, text=True, check=False)
    if result.returncode != 0:
        return set()
    # Первая строка — заголовок расширения; openssl печатает "IP Address:1.2.3.4".
    body = " ".join(result.stdout.splitlines()[1:]).replace("IP Address:", "IP:")
    return {part.strip() for part in body.split(",") if part.strip()}


def run(command: list[str], **kwargs) -> None:
    result = subprocess.run(command, capture_output=True, text=True, check=False, **kwargs)
    if result.returncode != 0:
        raise SystemExit(f"Не удалось выполнить {' '.join(command[:3])}…: {result.stderr.strip()}")


def ensure_ca(directory: Path, days: int) -> tuple[Path, Path]:
    key, certificate = directory / "ca.key", directory / "ca.pem"
    if key.is_file() and certificate.is_file():
        return key, certificate
    run(["openssl", "req", "-x509", "-newkey", "rsa:3072", "-nodes", "-days", str(days),
         "-keyout", str(key), "-out", str(certificate),
         "-subj", "/CN=ПоРукам локальный CA/O=ПоРукам",
         "-addext", "basicConstraints=critical,CA:TRUE",
         "-addext", "keyUsage=critical,keyCertSign,cRLSign"])
    os.chmod(key, 0o600)
    os.chmod(certificate, 0o644)
    return key, certificate


def ensure_certificate(directory: Path, ca_key: Path, ca_pem: Path, entries: list[str], days: int) -> bool:
    """Выпустить серверный сертификат. True — файлы обновлены."""
    key, certificate, chain = directory / "privkey.pem", directory / "leaf.pem", directory / "fullchain.pem"
    if key.is_file() and chain.is_file() and set(entries) <= current_sans(certificate) \
            and certificate_fresh(certificate):
        return False
    if not key.is_file():
        run(["openssl", "genrsa", "-out", str(key), "2048"])
        os.chmod(key, 0o600)
    with tempfile.NamedTemporaryFile("w", suffix=".ext", delete=False) as extensions:
        extensions.write("basicConstraints=CA:FALSE\n")
        extensions.write("keyUsage=digitalSignature,keyEncipherment\n")
        extensions.write("extendedKeyUsage=serverAuth\n")
        extensions.write("subjectAltName=" + ",".join(entries) + "\n")
        extension_path = Path(extensions.name)
    csr = directory / "leaf.csr"
    try:
        run(["openssl", "req", "-new", "-key", str(key), "-out", str(csr),
             "-subj", f"/CN={DEFAULT_HOSTNAME}/O=ПоРукам"])
        run(["openssl", "x509", "-req", "-in", str(csr), "-CA", str(ca_pem), "-CAkey", str(ca_key),
             "-CAcreateserial", "-out", str(certificate), "-days", str(days),
             "-extfile", str(extension_path)])
    finally:
        extension_path.unlink(missing_ok=True)
        csr.unlink(missing_ok=True)
    chain.write_bytes(certificate.read_bytes() + ca_pem.read_bytes())
    os.chmod(chain, 0o644)
    os.chmod(certificate, 0o644)
    return True


def prepare(directory: Path, addresses: list[str], hostname: str = DEFAULT_HOSTNAME,
            days: int = 397, ca_days: int = 3650, out=print) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    os.chmod(directory, 0o700)
    entries = san_entries(addresses, hostname)
    ca_key, ca_pem = ensure_ca(directory, ca_days)
    updated = ensure_certificate(directory, ca_key, ca_pem, entries, days)
    out(("Сертификат обновлён." if updated else "Сертификат актуален.") + f" Адреса: {', '.join(entries)}")
    out(f"Каталог для TLS_CERT_DIR: {directory}")
    return directory


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--directory", type=Path, help="Каталог вне Git для ключей и сертификатов")
    parser.add_argument("--ip", action="append", default=[], help="Дополнительный адрес сети (можно несколько)")
    parser.add_argument("--hostname", default=DEFAULT_HOSTNAME, help="Локальное имя для SAN")
    parser.add_argument("--days", type=int, default=397, help="Срок серверного сертификата, дней")
    parser.add_argument("--ca-days", type=int, default=3650, help="Срок локального CA, дней")
    args = parser.parse_args(argv)
    if not shutil.which("openssl"):
        print("Нужен openssl в PATH", file=sys.stderr)
        return 1
    addresses = private_ipv4(args.ip) or detect_addresses()
    if not addresses:
        print("Не найдено ни одного адреса локальной сети. Укажите его через --ip.", file=sys.stderr)
        return 1
    directory = args.directory or Path.home() / "Library/Application Support/PoRukam-LLM/tls"
    prepare(directory.resolve(), addresses, args.hostname, args.days, args.ca_days)
    print(f"На другие устройства перенесите только {directory / 'ca.pem'} и включите доверие этому CA.")
    print("Адрес сайта: https://" + addresses[0] + " (TLS_CERT_DIR в .env указывает на этот каталог).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
