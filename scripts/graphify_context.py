"""Lazy local Graphify refresh and bounded queries; no API keys or daemon."""
from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "graphify-out"
PYTHON = Path.home() / ".local/share/codex-tools/graphify/bin/python"
SUFFIXES = {".py", ".js", ".jsx", ".mjs", ".cjs", ".ts", ".tsx", ".sql", ".sh", ".json", ".toml", ".yaml", ".yml"}


def fingerprint() -> str:
    files = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
        cwd=ROOT, capture_output=True, check=True,
    ).stdout.split(b"\0")
    digest = hashlib.sha256(b"porukam-graphify-local-v1")
    for raw in sorted(set(files)):
        if not raw:
            continue
        relative = Path(os.fsdecode(raw))
        if relative.suffix not in SUFFIXES and relative.name not in {".gitignore", ".graphifyignore"}:
            continue
        path = ROOT / relative
        if not path.is_file() or path.is_symlink() or not path.resolve().is_relative_to(ROOT):
            continue
        digest.update(raw + b"\0" + path.read_bytes() + b"\0")
    return digest.hexdigest()


def run_graphify(*args: str, capture: bool = True) -> subprocess.CompletedProcess:
    env = os.environ.copy()
    # Keep both output resolution and optional provider discovery local/deterministic.
    env["GRAPHIFY_OUT"] = str(OUTPUT)
    env["GRAPHIFY_NO_TIPS"] = "1"
    # Sequential AST extraction avoids sandbox IPC restrictions and CPU bursts.
    env["GRAPHIFY_MAX_WORKERS"] = "1"
    for key in list(env):
        if key.endswith(("_API_KEY", "_API_TOKEN")):
            env.pop(key)
    return subprocess.run(
        [str(PYTHON), "-m", "graphify", *args], cwd=ROOT, env=env,
        text=True, capture_output=capture, timeout=180,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--query")
    parser.add_argument("--budget", type=int, default=1200)
    args = parser.parse_args()
    if not 200 <= args.budget <= 4000:
        parser.error("budget must be between 200 and 4000")
    if not PYTHON.is_file():
        print("Graphify не установлен на этой машине; используйте rg и чтение файлов.", file=sys.stderr)
        return 2
    OUTPUT.mkdir(exist_ok=True)
    with (OUTPUT / ".porukam.lock").open("w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        stamp = OUTPUT / ".porukam-fingerprint"
        current = fingerprint()
        graph = OUTPUT / "graph.json"
        cached = stamp.read_text().strip() if stamp.exists() else ""
        if not graph.exists() or cached != current:
            command = ("update", str(ROOT), "--no-cluster") if graph.exists() else (
                "extract", str(ROOT), "--code-only", "--no-cluster", "--no-dedup",
            )
            result = run_graphify(*command)
            if result.returncode or not graph.exists():
                print("Graphify не обновлён; используйте исходники и rg.", file=sys.stderr)
                print((result.stderr or result.stdout)[-2500:], file=sys.stderr)
                return 1
            if fingerprint() != current:
                print("Исходники изменились во время индексации; повторите запрос.", file=sys.stderr)
                return 1
            data = json.loads(graph.read_text())
            stamp.write_text(current + "\n")
            print(f"Graphify: индекс обновлён, {len(data.get('nodes', []))} узлов; локальный AST, без LLM.")
        else:
            print("Graphify: индекс актуален, повторная индексация не нужна.")
        if args.query:
            return run_graphify("query", args.query, "--budget", str(args.budget), capture=False).returncode
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, subprocess.SubprocessError, ValueError) as exc:
        print(f"Graphify недоступен ({type(exc).__name__}); используйте rg и исходники.", file=sys.stderr)
        raise SystemExit(1)
