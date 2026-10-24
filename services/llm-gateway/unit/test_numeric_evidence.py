import pytest

from app.agents import merge_facts
from app.schemas import RawExtraction, RawFact, SourceDescriptor


def extract(value, quote, *, key="quantity_units", text=None, extra_facts=(), extra_sources=()):
    source = SourceDescriptor(id="request_text", kind="text", name="Запрос", text=text or quote)
    raw = RawExtraction(category="бумажные стаканы", facts=[
        RawFact(key=key, value=value, source_id=source.id, confidence=.99, evidence=quote),
        *extra_facts,
    ])
    properties, _, questions = merge_facts(raw, [source, *extra_sources], [])
    return next(item for item in properties if item.key == key), questions


@pytest.mark.parametrize("key,value,quote", [
    ("quantity_units", 9000, "Нужно 5000 стаканов"),
    ("quantity_units", "9000", "Нужно 5000 стаканов"),
    ("quantity_units", 5, "Нужно 5000 стаканов"),
    ("budget_rub", 1000, "Бюджет 10000 рублей"),
    ("volume_ml", 5, "Объём 5,5 мл"),
    ("lead_time_days", 20, "Срок 10 дней"),
    ("temperature_min_c", 18, "Температура −18 °C"),
    ("temperature_min_c", 18, "Температура: -18 °C"),
])
def test_numeric_mismatch_requires_an_answer_without_prefilling_model_value(key, value, quote):
    prop, questions = extract(value, quote, key=key)
    assert prop.status == "needs_clarification"
    assert prop.value is None
    assert prop.sources[0].value == value  # Preserve what the model actually returned.
    assert prop.sources[0].locator["located"]
    assert any(item.key == key and not item.options for item in questions)


@pytest.mark.parametrize("value,quote", [
    (5000, "Нужно 5000 стаканов"),
    (5000, "Нужно 5 000 стаканов"),
    (5000, "Нужно 5\u00a0000 стаканов"),
    (5000, "Нужно 5\u202f000 стаканов"),
    (5000, "Нужно 5000, доставка в Москву"),
    (5.5, "Объём 5,5 мл"),
    (5.5, "Объём 5.50 мл"),
    (-18, "Температура −18 °C"),
])
def test_exact_numeric_value_in_a_located_quote_remains_confirmed(value, quote):
    prop, questions = extract(value, quote)
    assert prop.status == "confirmed"
    assert prop.value == value
    assert all(item.key != prop.key for item in questions)


def test_confidence_and_corroborating_source_cannot_hide_a_mismatching_quote():
    other = SourceDescriptor(id="other", kind="document", name="ТЗ", text="9000 стаканов")
    fact = RawFact(key="quantity_units", value=9000, source_id="other", confidence=.99, evidence=other.text)
    prop, questions = extract(9000, "Нужно 5000 стаканов", extra_sources=[other], extra_facts=[fact])
    assert prop.status == "needs_clarification" and prop.value is None
    assert len(prop.sources) == 2
    assert any(item.key == prop.key for item in questions)


@pytest.mark.parametrize("value,quote,text", [
    (9000, "9000 стаканов", "Нужно 5000 стаканов"),
    (10, "за десять дней", "за десять дней"),
    (10, "", "Срок 10 дней"),
    (18, "Температура−18 °C", "Температура−18 °C"),
])
def test_unverifiable_numeric_evidence_is_not_automatically_confirmed(value, quote, text):
    prop, _ = extract(value, quote, key="lead_time_days", text=text)
    assert prop.status == "assumed"


@pytest.mark.parametrize("value,quote,key", [
    ("Москва", "Доставка в Москву: Москва", "delivery_city"),
    (["ГОСТ 123", "PE"], "ГОСТ 123, покрытие PE", "mandatory_requirements"),
    ("400×300×300", "400×300×300 мм", "dimensions_mm"),
])
def test_text_lists_and_dimension_triples_keep_their_existing_semantics(value, quote, key):
    prop, _ = extract(value, quote, key=key)
    assert prop.status == "confirmed" and prop.value == value
