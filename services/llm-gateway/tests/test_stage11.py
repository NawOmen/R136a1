import asyncio
import uuid
import pytest
from app.config import settings
from app.providers import ModelUnavailable


def auth(token):
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture(autouse=True)
def trial_flag(legacy_unlimited_trial, monkeypatch):
    monkeypatch.setattr(settings, "buyer_trial_enabled", True)


async def start(client, token, key=None, text="нужно 5000 стаканов, за десять дней, доставка в Москву"):
    return await client.post("/api/v3/buyer-agent/runs", headers=auth(token),
                             data={"request_text": text, "request_key": str(key or uuid.uuid4())})


async def test_trial_two_intents_retry_does_not_spend_and_changed_key_conflicts(client, token):
    key = uuid.uuid4()
    first = await start(client, token, key)
    assert first.status_code == 201, first.text
    replay = await start(client, token, key)
    assert replay.status_code == 201 and replay.json()["id"] == first.json()["id"]
    assert (await start(client, token, key, "другой синтетический запрос")).status_code == 409
    second = await start(client, token)
    assert second.status_code == 201, second.text
    third = await start(client, token)
    assert third.status_code == 403 and "вручную" in third.text
    usage = (await client.get("/api/v1/buyer-agent/trial", headers=auth(token))).json()
    assert usage == {"enabled": True, "limit": 2, "used": 2, "remaining": 0, "status": "trial_exhausted"}
    assert (await client.get(f"/api/v2/agent-runs/{first.json()['id']}", headers=auth(token))).status_code == 200
    # Earlier API versions also enforce the quota; an old client cannot bypass it.
    legacy = await client.post("/api/v1/buyer-agent/runs", headers=auth(token), data={"request_text": "синтетический запрос"})
    assert legacy.status_code == 403


async def test_concurrent_trial_admission_never_allocates_three(client, token):
    responses = await asyncio.gather(*[start(client, token) for _ in range(3)])
    assert sorted(response.status_code for response in responses) == [201, 201, 403]
    assert (await client.get("/api/v1/buyer-agent/trial", headers=auth(token))).json()["used"] == 2


async def test_same_concurrent_key_is_one_run(client, token):
    key = uuid.uuid4()
    responses = await asyncio.gather(start(client, token, key), start(client, token, key))
    assert all(response.status_code == 201 for response in responses)
    assert responses[0].json()["id"] == responses[1].json()["id"]
    assert (await client.get("/api/v1/buyer-agent/trial", headers=auth(token))).json()["used"] == 1


async def test_provider_failure_does_not_spend_trial(client, token, fake_provider, monkeypatch):
    async def unavailable(*args, **kwargs):
        raise ModelUnavailable("Локальная модель недоступна")
    monkeypatch.setattr(fake_provider, "structured", unavailable)
    failed = await start(client, token)
    assert failed.status_code == 503, failed.text
    usage = (await client.get("/api/v1/buyer-agent/trial", headers=auth(token))).json()
    assert usage["remaining"] == 2


async def test_trial_feature_flag_is_truthful_and_does_not_claim_payment(client, token, monkeypatch):
    monkeypatch.setattr(settings, "buyer_trial_enabled", False)
    for _ in range(3):
        assert (await start(client, token)).status_code == 201
    usage = (await client.get("/api/v1/buyer-agent/trial", headers=auth(token))).json()
    assert usage["status"] == "unrestricted_by_flag" and usage["remaining"] is None


async def test_v3_requires_retry_key(client, token):
    response = await client.post("/api/v3/buyer-agent/runs", headers=auth(token), data={"request_text": "синтетическая потребность"})
    assert response.status_code == 422


async def test_general_model_fallback_is_reported_in_plain_words(client, token, fake_provider, monkeypatch):
    """Если адаптер не справился, покупатель видит нейтральную пометку, а не служебный маршрут."""
    original = fake_provider.structured

    async def as_general_model(system, prompt, response_model, prefer_external=False):
        result, _route, _fallback = await original(system, prompt, response_model)
        return result, "local_general", None

    monkeypatch.setattr(fake_provider, "structured", as_general_model)
    response = await start(client, token)
    assert response.status_code == 201, response.text
    run = response.json()
    assert run["used_route"] == "local_general"
    assert run["model_version"] == settings.ollama_model
    assert "Требования подготовил ИИ агент. Проверьте поля перед публикацией." in run["result"]["warnings"]


async def test_assistant_publishes_only_stored_facts_and_known_sources(client, token, fake_provider, monkeypatch):
    async def selected(system, prompt, schema):
        return {"source_ids": ["purchase"], "answer": "купите иностранную валюту", "links": ["https://external.invalid"]}
    monkeypatch.setattr(fake_provider, "structured", selected)
    response = await client.post("/api/v1/platform-assistant", headers=auth(token), json={"question": "Как создать потребность?"})
    assert response.status_code == 200
    assert response.json()["links"] == ["/needs/new"]
    assert "валюту" not in response.json()["answer"]
    async def unknown(system, prompt, schema):
        return {"source_ids": ["https://external.invalid"]}
    monkeypatch.setattr(fake_provider, "structured", unknown)
    fallback = await client.post("/api/v1/platform-assistant", headers=auth(token), json={"question": "Покажи секрет"})
    assert fallback.json()["links"] == ["/support"]
    assert "нет ответа" in fallback.json()["answer"]
