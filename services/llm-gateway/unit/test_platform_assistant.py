import uuid

from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient, Request, Response
import pytest

from app.api import router
from app.security import CurrentUser, get_current_user


@pytest.mark.asyncio
@pytest.mark.parametrize("source_ids, expected_status", [(["purchase"], 200), (["unknown"], 200), (["purchase"] * 3, 503)])
async def test_platform_assistant_with_ollama_grammar_compatibility(monkeypatch, source_ids, expected_status):
    from app.config import settings
    monkeypatch.setattr(settings, "local_llm_backend", "ollama")
    app = FastAPI()
    app.include_router(router)
    async def authenticated_user():
        return CurrentUser(uuid.uuid4())

    app.dependency_overrides[get_current_user] = authenticated_user

    class OllamaClient:
        def __init__(self, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def post(self, url, json):
            import json as json_module

            field = json["format"]["properties"]["source_ids"]["items"]
            if "minLength" in field or "maxLength" in field:
                return Response(400, request=Request("POST", url), text="failed to parse grammar")
            return Response(200, request=Request("POST", url), json={
                "message": {"content": json_module.dumps({"source_ids": source_ids})},
            })

    monkeypatch.setattr("app.providers.httpx.AsyncClient", OllamaClient)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/api/v1/platform-assistant", json={"question": "Где найти товары?"})
    assert response.status_code == expected_status
    if expected_status == 200:
        from app.knowledge import KnowledgeSelection, answer
        assert response.json() == answer(KnowledgeSelection(source_ids=source_ids))
    else:
        assert "FAQ" in response.json()["detail"]


@pytest.mark.asyncio
async def test_platform_assistant_uses_general_model_when_trained_adapter_is_default(monkeypatch):
    """Адаптер обучен извлечению фактов: выбор источников справки идёт в общую модель."""
    from app.config import settings
    monkeypatch.setattr(settings, "local_llm_backend", "mlx")
    monkeypatch.setattr(settings, "assistant_llm_backend", "ollama")
    app = FastAPI()
    app.include_router(router)

    async def authenticated_user():
        return CurrentUser(uuid.uuid4())

    app.dependency_overrides[get_current_user] = authenticated_user

    class OllamaClient:
        def __init__(self, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def post(self, url, json):
            import json as json_module

            return Response(200, request=Request("POST", url), json={
                "message": {"content": json_module.dumps({"source_ids": ["deal"]})},
            })

    async def trained_adapter_is_not_a_chat_model(self, system, prompt, response_model):
        raise AssertionError("Выбор источников справки не должен идти в обученный адаптер")

    monkeypatch.setattr("app.providers.httpx.AsyncClient", OllamaClient)
    monkeypatch.setattr("app.providers.TrainedMLXProvider.structured",
                        trained_adapter_is_not_a_chat_model)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/api/v1/platform-assistant", json={"question": "Как согласовать условия сделки?"})
    assert response.status_code == 200
    assert "/deals" in response.json()["links"]
