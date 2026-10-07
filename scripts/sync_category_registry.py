"""Generate the web catalogue snapshot from the backend's canonical registry.

Run with --check in CI. Both applications keep self-contained Docker contexts;
no network, dependency installation or database is needed.
"""
import argparse
import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "services/marketplace/app/category_registry.py"
TARGET = ROOT / "apps/web/app/lib/category-registry.generated.json"


def expected_snapshot() -> str:
    spec = importlib.util.spec_from_file_location("catalog_registry_generator", SOURCE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    registry = module.registry_snapshot()
    # Only identity is needed by current forms; operational readiness stays on
    # the server and must not be confused with permission to publish a product.
    snapshot = {
        "schema_version": registry["schema_version"],
        "registry_version": registry["registry_version"],
        "tree": module.catalogue_tree(),
        "leaf_ids": {group["label"]: {leaf["label"]: leaf["id"] for leaf in group["leaves"]} for group in registry["groups"]},
    }
    return json.dumps(snapshot, ensure_ascii=False, indent=2) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    content = expected_snapshot()
    if args.check:
        if not TARGET.exists() or TARGET.read_text(encoding="utf-8") != content:
            print("Каталог интерфейса устарел: выполните python3 scripts/sync_category_registry.py")
            return 1
        print("Реестры категорий сервера и интерфейса согласованы")
    else:
        TARGET.write_text(content, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
