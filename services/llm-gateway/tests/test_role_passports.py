import json
from pathlib import Path

import pytest

from app.config import settings
from app.role_passports import MODEL_MANIFEST, PROMPT_VERSION, ROLE_PASSPORTS, TOOL_REGISTRY


def auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


REQUIRED_PASSPORT_FIELDS = {
    "title", "purpose", "inputs", "outputs", "sources", "tools", "company_scope",
    "prompt_version", "model", "schema_version", "implemented_by", "time_limits",
    "resource_limits", "stop_conditions", "result", "decision_by",
}


@pytest.mark.asyncio
async def test_agent_roles_endpoint_lists_all_passports(client):
    response = await client.get("/api/v2/agent-roles")
    assert response.status_code == 200
    roles = {item["id"]: item for item in response.json()}
    assert set(roles) == {"buyer_investigation", "buyer", "seller", "marketplace", "coalition", "resilience"}
    for role_id, passport in roles.items():
        assert REQUIRED_PASSPORT_FIELDS <= set(passport), role_id
        assert all(passport[field] for field in REQUIRED_PASSPORT_FIELDS - {"tools"}), role_id
        assert set(passport["tools"]) <= set(TOOL_REGISTRY), role_id


@pytest.mark.asyncio
async def test_code_implemented_roles_state_no_llm(client):
    for role_id in ("marketplace", "coalition", "resilience"):
        response = await client.get(f"/api/v2/agent-roles/{role_id}")
        assert response.status_code == 200
        body = response.json()
        assert body["implemented_by"] == "code"
        assert body["model"] == "нет модели"
    assert (await client.get("/api/v2/agent-roles/unknown")).status_code == 404


def test_model_manifest_records_selection_criteria():
    assert {"porukam-buyer-qwen3.5", "qwen3.5:9b", "deepseek-v4-pro"} <= set(MODEL_MANIFEST)
    for model, record in MODEL_MANIFEST.items():
        for field in ("role", "quality_gate", "latency_budget", "ram_vram", "license", "data_rule"):
            assert record[field], (model, field)


def test_trained_runtime_alias_matches_model_lock():
    repo_root = Path(__file__).resolve().parents[3]
    model_lock = json.loads((repo_root / "infra" / "models.lock.json").read_text(encoding="utf-8"))
    configured_model = model_lock["local_llm"]["model"]
    assert settings.trained_model_version == configured_model
    assert configured_model in MODEL_MANIFEST


@pytest.mark.asyncio
async def test_run_records_versions_and_test_double_kind(client, token):
    response = await client.post(
        "/api/v1/buyer-agent/runs",
        data={"request_text": "Нужно 5000 бумажных стаканов в Москву за десять дней"},
        headers=auth(token),
    )
    assert response.status_code == 201
    body = response.json()
    assert body["prompt_version"] == PROMPT_VERSION
    expected_model = settings.trained_model_version if settings.local_llm_backend == "mlx" else settings.ollama_model
    assert body["model_version"] == expected_model
    assert body["provider_kind"] == "test_double"


def test_task_bank_is_versioned_ground_truth():
    bank_path = Path(__file__).resolve().parents[3] / "packages" / "test-fixtures" / "agent-task-bank" / "ru_tasks.json"
    bank = json.loads(bank_path.read_text(encoding="utf-8"))
    assert bank["version"] == 1
    assert len(bank["tasks"]) >= 5
    modes = {task["mode"] for task in bank["tasks"]}
    assert {"correct", "conflicting"} <= modes
    categories = {task["expected_category"] for task in bank["tasks"]}
    assert len(categories) >= 2
    for task in bank["tasks"]:
        assert task["input_text"] and task["expected_category"]
