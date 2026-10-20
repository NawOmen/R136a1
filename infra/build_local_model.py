"""Сборка локальной обученной модели Ollama из MLX-базы и LoRA-адаптера.

Модель собирается на машине с `mlx-lm` и Ollama:

1. `mlx_lm fuse` переносит LoRA-адаптер в веса базовой MLX-модели;
2. `ollama create` импортирует safetensors-каталог как модель Ollama.

Скрипт не обучает модель, не меняет исходные каталоги и не добавляет
зависимостей в приложение. Обученный кандидат предназначен для тестового
контура: семантическая приёмка независимым экспертом не пройдена.

Пример:

    python3 infra/build_local_model.py \
      --base /path/to/model-9b-4bit \
      --adapter /path/to/adapter-2144 \
      --name porukam-buyer-9b:latest
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path


def run(command: list[str]) -> None:
    print("+", " ".join(command))
    try:
        subprocess.run(command, check=True)
    except subprocess.CalledProcessError as error:
        raise SystemExit(
            f"Команда завершилась с кодом {error.returncode}: {' '.join(command)}"
        ) from None


def resolve_adapter(path: Path) -> Path:
    """mlx-lm ожидает каталог с adapters.safetensors и adapter_config.json."""
    path = path.expanduser().resolve()
    if path.is_file():
        return path.parent
    return path


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Собрать модель Ollama из MLX-базы и LoRA-адаптера."
    )
    parser.add_argument("--base", type=Path, required=True, help="каталог базовой MLX-модели")
    parser.add_argument("--adapter", type=Path, required=True, help="каталог LoRA-адаптера")
    parser.add_argument(
        "--name", default="porukam-buyer-9b:latest", help="тег модели Ollama"
    )
    parser.add_argument(
        "--workdir",
        type=Path,
        default=Path(".build/porukam-buyer-9b"),
        help="каталог сборки (по умолчанию .build/porukam-buyer-9b)",
    )
    parser.add_argument(
        "--python",
        default=sys.executable,
        help="интерпретатор с установленным mlx-lm (по умолчанию текущий)",
    )
    parser.add_argument(
        "--quantize",
        help="необязательный уровень квантования safetensors для `ollama create`",
    )
    parser.add_argument(
        "--skip-fuse", action="store_true", help="не запускать fuse, использовать --fused"
    )
    parser.add_argument("--fused", type=Path, help="готовый каталог слитой модели")
    args = parser.parse_args()

    base = args.base.expanduser().resolve()
    adapter = resolve_adapter(args.adapter)
    workdir = args.workdir.expanduser().resolve()

    if not (base / "config.json").is_file():
        raise SystemExit(f"Не найден каталог MLX-модели: {base}")
    if not (adapter / "adapters.safetensors").is_file():
        raise SystemExit(f"Не найден LoRA-адаптер: {adapter}")
    if shutil.which("ollama") is None:
        raise SystemExit("Команда ollama не найдена в PATH")

    if args.skip_fuse:
        fused = (args.fused or workdir / "fused").expanduser().resolve()
        if not fused.is_dir():
            raise SystemExit(f"Не найден каталог --fused: {fused}")
    else:
        probe = subprocess.run(
            [args.python, "-c", "import mlx_lm"], capture_output=True, text=True
        )
        if probe.returncode != 0:
            raise SystemExit(
                f"В интерпретаторе {args.python} нет mlx-lm; укажите --python "
                "с установленным mlx-lm"
            )
        fused = workdir / "fused"
        workdir.mkdir(parents=True, exist_ok=True)
        run(
            [
                args.python,
                "-m",
                "mlx_lm",
                "fuse",
                "--model",
                str(base),
                "--adapter-path",
                str(adapter),
                "--save-path",
                str(fused),
            ]
        )

    modelfile = workdir / "Modelfile"
    modelfile.write_text(f"FROM {fused}\n", encoding="utf-8")
    command = ["ollama", "create", args.name, "-f", str(modelfile)]
    if args.quantize:
        command.extend(["--quantize", args.quantize])
    run(command)

    print(f"\nГотово: {args.name}")
    print(f"Проверка: ollama show {args.name}")
    print("Модель текстовая; для изображений используется OLLAMA_VISION_MODEL.")


if __name__ == "__main__":
    main()
