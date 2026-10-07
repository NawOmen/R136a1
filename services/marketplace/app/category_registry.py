"""Versioned catalogue identity, independent of legal document admission.

Display labels remain the v1 wire contract; IDs are stable metadata for future
profile revisions. Registry entries never grant publication or deal approval.
"""
import json
import re
from copy import deepcopy
from pathlib import Path


def normalize_label(value: str | None) -> str:
    return (value or "").strip().lower().replace("ё", "е")


def validate_registry(data: dict) -> None:
    if data.get("schema_version") != 1 or not data.get("registry_version"):
        raise ValueError("Неподдерживаемая версия реестра категорий")
    groups = data.get("groups")
    if not isinstance(groups, list) or not groups:
        raise ValueError("В реестре отсутствуют категории")
    ids: set[str] = set()
    group_labels: set[str] = set()
    for group in groups:
        labels: set[str] = set()
        for entry, scope in [(group, group_labels), *[(leaf, labels) for leaf in group.get("leaves", [])]]:
            identifier = entry.get("id", "")
            if not isinstance(identifier, str) or not re.fullmatch(r"[a-z][a-z0-9.-]*", identifier) or identifier in ids:
                raise ValueError("Повторяющийся или некорректный ID категории")
            ids.add(identifier)
            aliases = entry.get("aliases")
            if not isinstance(aliases, list) or not isinstance(entry.get("label"), str):
                raise ValueError("Некорректные метка или синонимы категории")
            for label in [entry["label"], *aliases]:
                if not isinstance(label, str) or not normalize_label(label) or normalize_label(label) in scope:
                    raise ValueError("Пустая или неоднозначная метка категории")
                scope.add(normalize_label(label))
        if not group.get("leaves"):
            raise ValueError("Категория должна содержать хотя бы один лист")
        for leaf in group["leaves"]:
            if leaf.get("parent_id") != group["id"] or not leaf["id"].startswith(group["id"] + "."):
                raise ValueError("Некорректный родитель листа категории")
            if type(leaf.get("revision")) is not int or leaf["revision"] < 1:
                raise ValueError("Некорректная версия листа категории")
            if leaf.get("functional_state") not in {"classification_only", "profile_ready", "accepted"}:
                raise ValueError("Неизвестное состояние функциональности категории")
            if leaf.get("admission_state") not in {"not_configured", "existing_rules", "unsupported"}:
                raise ValueError("Неизвестное состояние правил допуска")
            key = leaf.get("admission_profile_key")
            if (leaf["admission_state"] == "not_configured") != (key is None):
                raise ValueError("Состояние допуска не согласовано с профилем")
            if key is not None and (not isinstance(key, str) or not key):
                raise ValueError("Некорректная ссылка на профиль допуска")
            if not isinstance(leaf.get("owner_role"), str) or not leaf["owner_role"].strip():
                raise ValueError("Не задан владелец правил категории")
            for field in ("required_functions", "limitations", "test_refs", "next_tasks"):
                values = leaf.get(field)
                if not isinstance(values, list) or not values or any(not isinstance(value, str) or not value.strip() for value in values):
                    raise ValueError(f"Некорректное поле категории: {field}")


_REGISTRY = json.loads(Path(__file__).with_name("category_registry.json").read_text(encoding="utf-8"))
validate_registry(_REGISTRY)
REGISTRY_VERSION: str = _REGISTRY["registry_version"]


def registry_snapshot() -> dict:
    """Return detached metadata; callers cannot mutate the loaded registry."""
    return deepcopy(_REGISTRY)


def catalogue_tree() -> dict[str, list[str]]:
    return {group["label"]: [leaf["label"] for leaf in group["leaves"]] for group in _REGISTRY["groups"]}


def resolve_category(category: str | None, subcategory: str | None) -> dict | None:
    """Resolve a parent/leaf pair exactly; never guess a neighbouring leaf.

    A legacy leaf-only label is accepted only when globally unambiguous.
    """
    parent, child = normalize_label(category), normalize_label(subcategory)
    matches = []
    for group in _REGISTRY["groups"]:
        parent_matches = parent in {normalize_label(label) for label in [group["label"], *group["aliases"]]}
        for leaf in group["leaves"]:
            names = {normalize_label(label) for label in [leaf["label"], *leaf["aliases"]]}
            if (child and parent_matches and child in names) or (not child and parent in names):
                matches.append(leaf)
    return deepcopy(matches[0]) if len(matches) == 1 else None
