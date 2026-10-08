"""Оценка банка русскоязычных задач: критичные поля, а не только валидный JSON."""

import json
import os
from pathlib import Path

import pytest

from app.providers import ModelUnavailable, OllamaProvider
from app.schemas import RawExtraction, RawFact

BANK_PATH = (
    Path(__file__).resolve().parents[3]
    / "packages" / "test-fixtures" / "agent-task-bank" / "ru_tasks.json"
)


def auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def scripted_extraction(task: dict) -> RawExtraction:
    if task["id"] == "bank-001":
        facts = [
            RawFact(key="quantity_units", value=5000, source_id="request_text", confidence=0.95, evidence="нужно 5000"),
            RawFact(key="lead_time_days", value=10, source_id="request_text", confidence=0.9, evidence="за десять дней"),
            RawFact(key="delivery_city", value="Москва", source_id="request_text", confidence=0.95, evidence="в Москву"),
            RawFact(key="budget_rub", value=150000, source_id="request_text", confidence=0.9, evidence="бюджет 150000 рублей"),
        ]
        return RawExtraction(category="бумажные стаканы", facts=facts)
    if task["id"] == "bank-002":
        facts = [
            RawFact(key="quantity_units", value=20000, source_id="request_text", confidence=0.95, evidence="20000 болтов"),
            RawFact(key="lead_time_days", value=20, source_id="request_text", confidence=0.9, evidence="за 20 дней"),
            RawFact(key="delivery_city", value="Казань", source_id="request_text", confidence=0.95, evidence="в Казань"),
        ]
        return RawExtraction(category="крепёж", facts=facts)
    if task["id"] == "bank-003":
        facts = [
            RawFact(key="body_material", value="полипропилен", source_id="file_1", confidence=0.9, evidence="лотки из полипропилена"),
            RawFact(key="body_material", value="полистирол", source_id="file_2", confidence=0.85, evidence="лотки из полистирола"),
            RawFact(key="quantity_units", value=30000, source_id="request_text", confidence=0.95, evidence="30000 лотков"),
        ]
        return RawExtraction(category="упаковка", facts=facts)
    if task["id"] == "bank-004":
        facts = [
            RawFact(key="quantity_units", value=5000, source_id="request_text", confidence=0.95, evidence="нужно 5000"),
            RawFact(key="print", value="не указано", source_id="request_text", confidence=0.4, evidence="цвет не указано"),
            RawFact(key="inner_coating", value="—", source_id="request_text", confidence=0.3, evidence="покрытие —"),
        ]
        return RawExtraction(category="бумажные стаканы", facts=facts)
    return RawExtraction(
        category="бумажные стаканы",
        facts=[RawFact(key="quantity_units", value=5000, source_id="request_text", confidence=0.95, evidence="нужно 5000")],
    )


def properties_by_key(result: dict) -> dict:
    return {item["key"]: item for item in result["properties"]}


@pytest.mark.asyncio
async def test_bank_correct_and_conflicting_tasks(client, token, fake_provider):
    bank = json.loads(BANK_PATH.read_text(encoding="utf-8"))
    for task in bank["tasks"]:
        fake_provider.extraction = scripted_extraction(task)
        files = None
        if task["id"] == "bank-003":
            files = [
                ("files", ("tz.txt", "ТЗ: лотки из полипропилена, 30000 шт.", "text/plain")),
                ("files", ("nakladnaya.txt", "Накладная: лотки из полистирола, 30000 шт.", "text/plain")),
            ]
        kwargs = {"data": {"request_text": task["input_text"]}, "headers": auth(token)}
        if files:
            kwargs["files"] = files
        response = await client.post("/api/v1/buyer-agent/runs", **kwargs)
        assert response.status_code == 201, task["id"]
        body = response.json()
        assert body["result"]["category"] == task["expected_category"], task["id"]
        props = properties_by_key(body["result"])
        for key, expected in task["critical_fields"].items():
            assert props[key]["value"] == expected, (task["id"], key)
        if task["conflicts_expected"]:
            assert body["result"]["conflicts"], task["id"]
            assert body["result"]["can_confirm"] is False, task["id"]
        else:
            assert not body["result"]["conflicts"], task["id"]
        for forbidden in task.get("forbidden_values") or []:
            assert all(prop["value"] != forbidden for prop in body["result"]["properties"]), (task["id"], forbidden)
        assert all(prop["status"] == "needs_clarification"
                   for prop in body["result"]["properties"] if prop["value"] is None), task["id"]
        if task.get("must_warn"):
            assert any("попытка изменить" in warning for warning in body["result"]["warnings"]), task["id"]
        if task.get("price_must_not_change"):
            assert all(prop["value"] != 1 for prop in body["result"]["properties"]), task["id"]


@pytest.mark.ollama
@pytest.mark.asyncio
@pytest.mark.skipif(
    os.getenv("RUN_OLLAMA_SMOKE") != "1",
    reason="Требуется локальная Ollama и RUN_OLLAMA_SMOKE=1",
)
async def test_bank_live_sample_checks_critical_fields():
    """Одна версия банка имеет воспроизводимую выборку: критичные поля живого прогона."""
    bank = json.loads(BANK_PATH.read_text(encoding="utf-8"))
    sample = next(task for task in bank["tasks"] if task["id"] == "bank-001")
    try:
        result = await OllamaProvider().structured(
            "Извлеки требования. Не выдумывай отсутствующие значения.",
            sample["input_text"],
            RawExtraction,
        )
    except ModelUnavailable:
        pytest.skip("Локальная модель недоступна")
    assert result.category == sample["expected_category"]
    facts = {(fact.key, str(fact.value)) for fact in result.facts}
    assert ("quantity_units", "5000") in facts
