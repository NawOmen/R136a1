"""Versioned catalogue identity, independent of legal document admission.

Display labels remain the v1 wire contract; IDs are stable metadata for future
profile revisions. Registry entries never grant publication or deal approval.
"""
import json
import re
from copy import deepcopy
from contextvars import ContextVar
from contextlib import contextmanager
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

    fields = data.get("characteristic_fields", {})
    for key, definition in fields.items():
        if not isinstance(key, str) or definition.get("type") not in {"text", "number", "integer"}:
            raise ValueError("Некорректный тип характеристики")
        if not definition.get("label") or not isinstance(definition.get("aliases"), list):
            raise ValueError("Некорректное описание характеристики")
    for group in groups:
        for leaf in group["leaves"]:
            profile = leaf.get("technical_profile")
            if not profile or type(profile.get("version")) is not int or profile["version"] < 1:
                raise ValueError("Не задана версия технического профиля")
            keys = profile.get("fields", [])
            if not isinstance(keys, list) or not keys or any(not isinstance(key, str) for key in keys) or len(keys) != len(set(keys)) or any(key not in fields for key in keys):
                raise ValueError("Некорректные поля технического профиля")
            if not isinstance(profile.get("required_for_product"), list) or not profile["required_for_product"] or any(key not in keys for key in profile.get("required_for_product", [])):
                raise ValueError("Обязательная характеристика отсутствует в профиле")
            passport = profile.get("passport")
            if passport is not None:
                sections = {"identification", "units", "producer", "commercial", "resource", "documents", "compatibility", "logistics", "acceptance", "repeat", "sources", "update_policy"}
                if not isinstance(passport, dict) or set(passport) != sections:
                    raise ValueError("Паспорт должен содержать все предметные разделы")
                if any(not isinstance(passport[key], dict) or not passport[key] for key in sections - {"sources", "update_policy"}):
                    raise ValueError("Разделы паспорта должны содержать структурированные правила")
                if passport["identification"].get("required") != profile["required_for_product"] or passport["compatibility"].get("hard_fields") != profile["required_for_product"]:
                    raise ValueError("Обязательная идентификация и жёсткие ограничения должны совпадать")
                conditions=passport["identification"].get("required_when",[])
                if not isinstance(conditions,list):raise ValueError("Зависимости свойств должны быть списком")
                for condition in conditions:
                    if not isinstance(condition,dict) or condition.get("field") not in keys or not isinstance(condition.get("values"),list) or not condition["values"] or any(not isinstance(value,str) or not value.strip() for value in condition["values"]) or not isinstance(condition.get("required"),list) or any(key not in keys for key in condition["required"]):
                        raise ValueError("Некорректная предметная зависимость свойств")
                allowed = passport["units"].get("allowed")
                if not isinstance(allowed, list) or not allowed or any(not isinstance(unit, str) or not unit.strip() for unit in allowed) or len(set(allowed)) != len(allowed):
                    raise ValueError("Не заданы однозначные единицы категории")
                base_units = {'кг':'г', 'т':'г', 'м':'мм', 'м²':'см²', 'л':'мл', 'м³':'мл'}
                if any(unit in allowed and base not in allowed for unit, base in base_units.items()):
                    raise ValueError("Физическая единица должна разрешать точную меньшую единицу хранения")
                checks = passport["acceptance"].get("checks")
                if not isinstance(checks, list) or not checks or any(not isinstance(check, str) or not check.strip() for check in checks):
                    raise ValueError("Не заданы предметные проверки приёмки")
                if passport["documents"].get("review_required") is not True or passport["documents"].get("admission_profile") != leaf["admission_profile_key"]:
                    raise ValueError("Паспорт не может отменять проверку применимости документов")
                if passport["repeat"] != {"new_draft": True, "revalidate": True, "copy_approvals": False, "copy_documents": False}:
                    raise ValueError("Повтор должен заново проверять условия и допуск")
                sources = passport["sources"]
                if not isinstance(sources, list) or not sources or any(not isinstance(source, dict) or not source.get("scope") or not (source.get("url") or source.get("path")) for source in sources):
                    raise ValueError("Укажите проверяемые источники правил")
                if not isinstance(passport["update_policy"], str) or not passport["update_policy"].strip():
                    raise ValueError("Не задан порядок обновления правил")
            names = []
            for key in keys:
                names.extend({normalize_label(alias) for alias in [key, *fields[key]["aliases"]]})
            if len(names) != len(set(names)):
                raise ValueError("Синонимы характеристик неоднозначны")


_REGISTRY = json.loads(Path(__file__).with_name("category_registry.json").read_text(encoding="utf-8"))
validate_registry(_REGISTRY)
REGISTRY_VERSION: str = _REGISTRY["registry_version"]


_REQUEST_REGISTRY = ContextVar("category_registry", default=None)


@contextmanager
def registry_context(data):
    if data is not None: validate_registry(data)
    token = _REQUEST_REGISTRY.set(data)
    try: yield
    finally: _REQUEST_REGISTRY.reset(token)


def _registry():
    return _REQUEST_REGISTRY.get() or _REGISTRY


def registry_snapshot() -> dict:
    """Return detached metadata; callers cannot mutate the loaded registry."""
    return deepcopy(_registry())


def catalogue_tree() -> dict[str, list[str]]:
    return {group["label"]: [leaf["label"] for leaf in group["leaves"]] for group in _registry()["groups"]}


def resolve_category(category: str | None, subcategory: str | None) -> dict | None:
    """Resolve a parent/leaf pair exactly; never guess a neighbouring leaf.

    A legacy leaf-only label is accepted only when globally unambiguous.
    """
    parent, child = normalize_label(category), normalize_label(subcategory)
    matches = []
    for group in _registry()["groups"]:
        parent_matches = parent in {normalize_label(label) for label in [group["label"], *group["aliases"]]}
        for leaf in group["leaves"]:
            names = {normalize_label(label) for label in [leaf["label"], *leaf["aliases"]]}
            if (child and parent_matches and child in names) or (not child and parent in names):
                matches.append(leaf)
    return deepcopy(matches[0]) if len(matches) == 1 else None


def base_registry_snapshot():
    return deepcopy(_REGISTRY)
