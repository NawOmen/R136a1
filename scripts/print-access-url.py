"""Показать адрес, по которому сайт доступен с других устройств в локальной сети.

Пример:
    python scripts/print-access-url.py

Скрипт определяет IPv4-адрес текущей машины в локальной сети и печатает адрес
http://<IP>:3000 — его можно открыть на телефоне/планшете, подключённых к той же
сети. CORS сервисов разрешает любые приватные подсети (10.x, 172.16-31.x,
192.168.x), поэтому IP можно свободно менять без перенастройки.
"""
from __future__ import annotations

import socket
import subprocess
import sys

WEB_PORT = 3000


def _via_udp() -> str | None:
    """IP маршрута по умолчанию (работает и на macOS, и на Linux)."""
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            sock.connect(("8.8.8.8", 80))  # пакеты не отправляются, только выбор маршрута
            return sock.getsockname()[0]
        finally:
            sock.close()
    except OSError:
        return None


def _via_hostname() -> list[str]:
    try:
        return [info[4][0] for info in socket.getaddrinfo(socket.gethostname(), None)
                if info[0] is socket.AF_INET]
    except OSError:
        return []


def _via_command() -> list[str]:
    commands = (
        (["ipconfig", "getifaddr", "en0"], "Darwin"),
        (["hostname", "-I"], "Linux"),
    )
    found: list[str] = []
    for argv, platform_name in commands:
        if sys.platform != platform_name:
            continue
        try:
            output = subprocess.check_output(argv, text=True, timeout=5).strip()
        except (OSError, subprocess.SubprocessError):
            continue
        for token in output.replace(",", " ").split():
            if _is_private(token) and token not in found:
                found.append(token)
    return found


def _is_private(ip: str) -> bool:
    try:
        parts = [int(part) for part in ip.split(".")]
    except ValueError:
        return False
    if len(parts) != 4:
        return False
    a, b, *_ = parts
    return a == 10 or (a == 172 and 16 <= b <= 31) or (a == 192 and b == 168)


def main() -> int:
    candidates: list[str] = []
    via_udp = _via_udp()
    if via_udp and _is_private(via_udp):
        candidates.append(via_udp)
    for ip in _via_hostname() + _via_command():
        if _is_private(ip) and ip not in candidates:
            candidates.append(ip)

    if not candidates:
        print(
            "Не удалось определить IP локальной сети.\n"
            "Проверьте, что машина подключена к Wi-Fi/роутеру, и укажите адрес вручную,\n"
            "например: http://192.168.1.50:3000",
            file=sys.stderr,
        )
        return 1

    ip = candidates[0]
    print(f"Сайт доступен с других устройств в той же сети: http://{ip}:{WEB_PORT}")
    if len(candidates) > 1:
        print("Другие сетевые адреса: " + ", ".join(
            f"http://{other}:{WEB_PORT}" for other in candidates[1:]
        ))
    print(
        "Откройте этот адрес на телефоне/планшете, подключённом к той же сети.\n"
        "API и CORS настраивать не нужно: приватные подсети разрешены автоматически."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
