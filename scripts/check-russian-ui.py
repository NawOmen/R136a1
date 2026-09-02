from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
forbidden = ("Сборка B2B", ">Capability Passport<", ">Loading<", ">Settings<", ">Support<")
violations: list[str] = []
for path in (ROOT / "apps" / "web" / "app").rglob("*.tsx"):
    text = path.read_text(encoding="utf-8")
    for phrase in forbidden:
        if phrase in text:
            violations.append(f"{path.relative_to(ROOT)}: найдено «{phrase}»")
if violations:
    raise SystemExit("\n".join(violations))
print("Проверка русского интерфейса пройдена")
