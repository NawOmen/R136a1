"""Проверить последнюю MLX-модель; --serve запускает её только по команде оператора.

Не выполняет обучение, fuse, конвертацию в GGUF или ollama create.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import sys

ADAPTER_SHA256 = "b2cf30b111109ee10439b4308cb97058ab00a85115eedd36118bbc534e52b665"
ADAPTER_CONFIG_SHA256 = "f715c2cac7c67a67b59f3bc0d178df986bd766d34aa9e68d809d2cd2d6b01262"
BASE_REVISION = "8b2b98c00a6b4d291155e4890773ca8f769aee53"

def digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(8 * 1024**2), b""):
            h.update(block)
    return h.hexdigest()

def verify(base: Path, adapter: Path) -> None:
    if digest(adapter / "adapters.safetensors") != ADAPTER_SHA256:
        raise ValueError("SHA256 адаптера не совпадает с последней версией PR")
    if digest(adapter / "adapter_config.json") != ADAPTER_CONFIG_SHA256:
        raise ValueError("SHA256 конфигурации адаптера не совпадает")
    manifest = json.loads((base / "download-manifest.json").read_text())
    if manifest["sha"] != BASE_REVISION:
        raise ValueError("Не совпадает ревизия базовой модели")
    if not (adapter / "adapter_config.json").is_file():
        raise ValueError("Не найден adapter_config.json")
    count = 0
    for entry in manifest["siblings"]:
        if entry.get("lfs"):
            path = base / entry["rfilename"]
            if path.stat().st_size != entry["lfs"]["size"] or digest(path) != entry["lfs"]["sha256"]:
                raise ValueError(f"Повреждён базовый файл {entry['rfilename']}")
            count += 1
    if not count:
        raise ValueError("Пустой манифест базовых весов")

def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--base", type=Path, required=True)
    p.add_argument("--adapter", type=Path, required=True)
    p.add_argument("--host", default="127.0.0.1", help="Для Docker доступ через приватный интерфейс хоста; не публичный интернет")
    p.add_argument("--port", type=int, default=8080)
    p.add_argument("--serve", action="store_true", help="Явно запустить MLX server после проверки")
    a = p.parse_args()
    try:
        verify(a.base, a.adapter)
    except (ValueError, KeyError, OSError) as exc:
        p.exit(1, f"Проверка модели не пройдена: {exc}\n")
    print("База и последний адаптер проверены. Фиксированная проверка:404/412exact; автономное применение не принято.")
    if not a.serve:
        print("Сервер не запущен. Для запуска оператором добавьте --serve.")
        return
    os.environ["MLX_MAX_OPS_PER_BUFFER"] = "1"
    os.environ["MLX_MAX_MB_PER_BUFFER"] = "10"
    import mlx.core as mx
    mx.set_memory_limit(9 * 1024**3)
    mx.disable_compile()
    from mlx_lm.server import main as serve
    sys.argv = ["mlx_lm.server", "--model", str(a.base.resolve()),
                "--adapter-path", str(a.adapter.resolve()), "--host", a.host,
                "--port", str(a.port), "--chat-template-args", '{"enable_thinking":false}']
    serve()

if __name__ == "__main__":
    main()
