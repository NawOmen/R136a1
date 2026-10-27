import pytest

from app.agents import SYSTEM_PROMPT, merge_facts
from app.schemas import RawExtraction, RawFact, SourceDescriptor


def merge(key, value, quote, *, category="Крепёж", extra=()):
    source = SourceDescriptor(id="text", kind="text", name="Запрос", text=quote)
    raw = RawExtraction(category=category, facts=[RawFact(key=key, value=value, source_id="text", confidence=.99, evidence=quote), *extra])
    properties, conflicts, questions = merge_facts(raw, [source], [])
    return {prop.key: prop for prop in properties}, conflicts, questions


@pytest.mark.parametrize("key", ["unit", "quantity", "qty", "units", "штук", "шт."])
def test_numeric_quantity_aliases_reach_downstream_key_without_inventing_a_unit(key):
    props, _, _ = merge(key, 200, "Нужно купить 200 болтов М8×40")
    assert props["quantity_units"].value == 200
    assert props["quantity_units"].status == "confirmed"
    assert "unit" not in props
    assert "Количество всегда извлекай отдельным числом в quantity_units" in SYSTEM_PROMPT


def test_alias_repair_still_checks_numeric_evidence():
    props, _, questions = merge("unit", 9000, "Нужно 5000 стаканов")
    assert props["quantity_units"].value is None
    assert props["quantity_units"].status == "needs_clarification"
    assert any(q.key == "quantity_units" for q in questions)


def test_derived_unit_without_word_in_quote_is_not_confirmed():
    props, _, _ = merge("unit", "шт", "Нужно 5000 бумажных стаканов")
    assert props["unit"].status == "assumed"
    assert props["quantity_units"].status == "needs_clarification"


@pytest.mark.parametrize("unit,quote", [("шт", "Нужно 200 шт."), ("штук", "Нужно 200 штук"), ("кг", "Нужно 200 кг")])
def test_explicit_dictionary_unit_is_confirmed_and_count_is_not_inferred(unit, quote):
    props, _, _ = merge("unit", unit, quote)
    assert props["unit"].status == "confirmed"
    assert props["unit"].value == ("кг" if unit == "кг" else "шт")
    assert props["quantity_units"].value is None


@pytest.mark.parametrize("unit", ["банан", "м³", True])
def test_invalid_or_category_incompatible_unit_requires_clarification(unit):
    props, _, questions = merge("unit", unit, f"Единица заказа: {unit}")
    assert props["unit"].status == "needs_clarification"
    assert props["unit"].value is None
    assert any(q.key == "unit" and "шт" in q.options for q in questions)


def test_quantity_conflicts_are_kept_after_key_repair():
    other = RawFact(key="quantity_units", value=300, source_id="text", confidence=.99, evidence="Было 300, нужно 200")
    props, conflicts, _ = merge("unit", 200, "Было 300, нужно 200", extra=[other])
    assert props["quantity_units"].status == "needs_clarification"
    assert conflicts[0].key == "quantity_units" and set(conflicts[0].values) == {200, 300}


def test_invalid_unit_never_becomes_a_conflict_option():
    other = RawFact(key="unit",value="шт",source_id="text",confidence=.99,evidence="Заказать в шт")
    props, _, questions = merge("unit","банан","Заказать в шт, единица банан",extra=[other])
    assert props["unit"].status == "needs_clarification"
    assert "банан" not in next(q for q in questions if q.key == "unit").options


def test_all_registry_units_have_a_supported_canonical_spelling():
    from app.agents import unit_value
    from app.category_grounding import REGISTRY
    for category in REGISTRY["categories"]:
        for unit in category["units"]:
            assert unit_value(unit) == unit
