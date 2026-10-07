"""Technical value validation; no compliance decisions or unit conversion."""
from decimal import Decimal, InvalidOperation

from .category_registry import registry_snapshot, resolve_category, normalize_label

_FIELDS = registry_snapshot()["characteristic_fields"]


def _number(value, field: dict) -> Decimal:
    if isinstance(value, bool) or not isinstance(value, (str, int, float, Decimal)):
        raise ValueError
    text = str(value).strip().replace(",", ".")
    # Existing aliases can contain e.g. "400 мл". Accept only the field's
    # explicit unit, without converting or rewriting the saved value.
    unit = field.get("unit")
    if unit and text.lower().endswith(unit.lower()):
        text = text[:-len(unit)].strip()
    return Decimal(text)


def characteristic_profile(category: str, subcategory: str | None) -> dict | None:
    leaf = resolve_category(category, subcategory)
    return leaf["technical_profile"] if leaf else None


def validate_profile_values(
    category: str, subcategory: str | None, characteristics: dict,
    *, require_product_fields: bool = False,
) -> list[str]:
    profile = characteristic_profile(category, subcategory)
    if profile is None:
        return []  # Legacy/free classifications need their own migration policy.
    errors = []
    normalized = {normalize_label(str(key)): value for key, value in characteristics.items()}
    for key in profile["fields"]:
        field = _FIELDS[key]
        aliases = {normalize_label(key), *(normalize_label(alias) for alias in field["aliases"])}
        values = [(normalize_label(str(alias)), value) for alias, value in characteristics.items()
                  if normalize_label(str(alias)) in aliases]
        if not values:
            if require_product_fields and key in profile["required_for_product"]:
                errors.append(f"Укажите характеристику «{field['label']}»")
            continue
        canonical = []
        for _, value in values:
            if field["type"] == "text":
                if not isinstance(value, str) or not value.strip() or len(value.strip()) > field.get("max_length", 500):
                    errors.append(f"«{field['label']}»: нужен непустой текст до 500 символов")
                    continue
                canonical.append(normalize_label(value))
            else:
                try:
                    number = _number(value, field)
                    if not number.is_finite() or (field.get("positive") and number <= 0):
                        raise ValueError
                    if field["type"] == "integer" and number != number.to_integral_value():
                        raise ValueError
                    canonical.append(number)
                except (ValueError, InvalidOperation):
                    kind = "положительное целое число" if field["type"] == "integer" else ("положительное число" if field.get("positive") else "конечное число")
                    errors.append(f"«{field['label']}»: укажите {kind} в указанной единице")
        if len(set(canonical)) > 1:
            errors.append(f"«{field['label']}»: значения в синонимах противоречат друг другу")
    minimum = normalized.get("temperature_min_c")
    maximum = normalized.get("temperature_max_c")
    if "temperature_min_c" in profile["fields"] and minimum is not None and maximum is not None:
        try:
            if _number(minimum, _FIELDS["temperature_min_c"]) > _number(maximum, _FIELDS["temperature_max_c"]):
                errors.append("Минимальная температура не может превышать максимальную")
        except (ValueError, InvalidOperation):
            pass  # Individual field errors already explain invalid input.
    return errors
