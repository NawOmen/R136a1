import copy
import json
from pathlib import Path
import uuid

import pytest

from app.agents import search_capabilities
from app.buyer_comparison import buyer_summary, catalog_reference, positive_integer
from app.schemas import CapabilityMatch, RequirementProperty


def prop(key, value, status="confirmed"):
    return RequirementProperty(key=key, label=key, value=value, confidence=1, status=status, sources=[])


def product(**changes):
    return {"id": uuid.uuid4(), "name": "Демо-стакан", "price_rub": 2.50,
            "price_tiers": [{"min_units": 1000, "unit_price_rub": 2.25}],
            "moq_units": 500, "lead_time_days": 7, "characteristics": {"volume_ml": 400}, **changes}


def test_price_is_calculated_exactly_and_not_invented():
    result = catalog_reference(product(), [prop("quantity_units", 1000), prop("volume_ml", 400)], [])
    assert result.comparable and result.total_rub == "2250.00"
    assert result.unit_price_rub == "2.25"
    match = CapabilityMatch(company_id=uuid.uuid4(), company_name="Демо", score=50, reasons=[], catalog=[result])
    summary = buyer_summary([match], False)
    assert "2250.00 ₽" in summary and "7 дн." in summary
    assert "Доставка и дополнительные работы не включены" in summary


@pytest.mark.parametrize("properties,cautions", [
    ([prop("quantity_units", 100), prop("volume_ml", 400)], []),
    ([prop("quantity_units", 1000), prop("volume_ml", 350)], []),
    ([prop("quantity_units", 1000), prop("volume_ml", 400, "assumed")], []),
    ([prop("quantity_units", 1000)], []),
    ([prop("quantity_units", 1000), prop("volume_ml", 400), prop("inner_coating", "PLA")], []),
    ([prop("quantity_units", 1000), prop("volume_ml", 400)], ["Размер вне диапазона"]),
    ([prop("quantity_units", 1000), prop("volume_ml", 400), prop("lead_time_days", 2)], []),
    ([prop("quantity_units", 1000), prop("volume_ml", 400), prop("budget_rub", 100)], []),
])
def test_insufficient_evidence_never_becomes_comparable_price(properties, cautions):
    result = catalog_reference(product(), properties, cautions)
    assert not result.comparable and result.total_rub is None


@pytest.mark.parametrize("value", [None, True, "NaN", "Infinity", "-1", "1.5", "неизвестно"])
def test_invalid_quantity(value):
    assert positive_integer(value) is None


class FakeDB:
    def __init__(self, rows, products=()):
        self.rows, self.products, self.calls = rows, list(products), []

    async def execute(self, statement, params=None):
        self.calls.append((str(statement), params))
        return self

    def mappings(self):
        return self

    def all(self):
        return self.products if "FROM marketplace.products" in self.calls[-1][0] else self.rows


def suppliers():
    path = Path(__file__).resolve().parents[3] / "packages/test-fixtures/capabilities/detailed_suppliers.json"
    rows = json.loads(path.read_text())
    for row in rows:
        row["company_id"] = uuid.UUID(row["company_id"])
    return rows


@pytest.mark.asyncio
async def test_expanded_passport_search_exclusion_and_limits():
    rows = suppliers()
    db = FakeDB(rows)
    matches = await search_capabilities(db, "металлические детали", [prop("quantity_units", 50), prop("diameter_mm", 200)])
    assert len(matches) == 1
    assert matches[0].details["material_grades"] == "Сталь 45, алюминий АМг6"
    assert len(matches[0].cautions) == 2
    assert await search_capabilities(FakeDB(rows), "металлические детали", [], rows[0]["company_id"]) == []


@pytest.mark.asyncio
async def test_many_detailed_passports_are_bounded_without_extra_llm_calls():
    base = suppliers()[2]
    rows = []
    for index in range(1000):
        row = copy.deepcopy(base)
        row["company_id"] = uuid.UUID(int=index + 1)
        rows.append(row)
    db = FakeDB(rows)
    matches = await search_capabilities(db, "бумажные стаканы", [prop("quantity_units", 5000)])
    assert len(matches) == 10
    assert len(db.calls) == 2
    assert all(match.cautions for match in matches)
    summary = buyer_summary(matches, False)
    assert "Показано кандидатов по паспортам: 10" in summary
    assert "недостаточно" in summary and "минимальная стоимость" not in summary


def test_unresolved_summary_does_not_rank_prices():
    quote = catalog_reference(product(), [prop("quantity_units", 1000), prop("volume_ml", 400)], [])
    match = CapabilityMatch(company_id=uuid.uuid4(), company_name="Демо", score=50, reasons=[], catalog=[quote])
    assert "минимальная стоимость" not in buyer_summary([match], True)
    assert "заказ невозможен" in buyer_summary([], False)


@pytest.mark.asyncio
async def test_requirement_only_candidate_is_visible_but_not_comparable():
    row = suppliers()[0]
    row.update(technologies=["токарная и фрезерная обработка"], materials=["сталь"],
               completed_order_types=[], certifications=[], details={}, size_ranges={})
    properties = [prop("body_material", "сталь"), prop("quantity_units", 1000)]
    reference = product(company_id=row["company_id"], characteristics={"body_material": "сталь"})
    matches = await search_capabilities(FakeDB([row], [reference]), "металлические детали", properties)
    assert len(matches) == 1
    candidate = matches[0]
    assert any("Категория не подтверждена" in item for item in candidate.cautions)
    assert not candidate.catalog[0].comparable
    assert candidate.catalog[0].total_rub is None
    assert "минимальная стоимость" not in buyer_summary(matches, False)

    # A hypothesis or a request without any supporting facts is not enough.
    assert await search_capabilities(FakeDB([row]), "металлические детали", []) == []
    assert await search_capabilities(FakeDB([row]), "металлические детали", [prop("body_material", "сталь", "assumed")]) == []
    assert await search_capabilities(FakeDB([row]), "металлические детали", properties, row["company_id"]) == []


@pytest.mark.asyncio
async def test_confirmed_category_ranks_before_requirement_only_candidate():
    direct, fallback = suppliers()[0], copy.deepcopy(suppliers()[0])
    fallback.update(company_id=uuid.uuid4(), technologies=["токарная обработка"], details={},
                    completed_order_types=[], materials=["сталь"])
    matches = await search_capabilities(FakeDB([fallback, direct]), "металлические детали", [prop("body_material", "сталь")])
    assert [match.company_id for match in matches] == [direct["company_id"], fallback["company_id"]]
