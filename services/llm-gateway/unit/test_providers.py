import pytest

from app.providers import OllamaProvider
from app.schemas import RawExtraction


class FakeResponse:
    def __init__(self, content: str):
        self.content = content

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        return {"message": {"content": self.content}}


class RecordingClient:
    payloads: list[dict] = []

    def __init__(self, *args, **kwargs):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, traceback):
        return None

    async def post(self, url: str, json: dict):
        self.payloads.append(json)
        if "images" in json["messages"][0]:
            return FakeResponse("На изображении синтетический стакан")
        return FakeResponse('{"category":"бумажные стаканы","facts":[]}')


@pytest.mark.asyncio
async def test_ollama_typical_operations_disable_thinking(monkeypatch):
    RecordingClient.payloads = []
    monkeypatch.setattr("app.providers.httpx.AsyncClient", RecordingClient)
    provider = OllamaProvider()

    result = await provider.structured("system", "prompt", RawExtraction)
    image_text = await provider.vision_text("synthetic-base64", "распознай")

    assert result.category == "бумажные стаканы"
    assert image_text == "На изображении синтетический стакан"
    assert len(RecordingClient.payloads) == 2
    assert all(payload["think"] is False for payload in RecordingClient.payloads)
