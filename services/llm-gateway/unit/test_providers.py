import pytest
from pydantic import BaseModel, Field

from app.config import settings
from app.providers import ModelUnavailable, OllamaProvider, _ollama_schema
from app.schemas import PlatformAssistantOut, RawExtraction


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
    assert RecordingClient.payloads[0]["model"] == settings.ollama_model
    assert RecordingClient.payloads[1]["model"] == settings.ollama_vision_model


def test_ollama_schema_relaxes_only_string_lengths_in_schema_nodes():
    class Detail(BaseModel):
        text: str = Field(min_length=2, max_length=10)

    class Result(BaseModel):
        details: list[Detail | None] = Field(max_length=3)
        minLength: str = Field(min_length=1, max_length=5)
        metadata: dict = {"minLength": 7, "maxLength": 9}

    original = Result.model_json_schema()
    schema = _ollama_schema(Result)
    assert schema["$defs"]["Detail"]["properties"]["text"] == {"title": "Text", "type": "string"}
    assert schema["properties"]["details"]["maxItems"] == 3
    assert schema["properties"]["details"]["items"]["anyOf"][0]["$ref"] == "#/$defs/Detail"
    assert schema["properties"]["minLength"]["type"] == "string"
    assert "maxLength" not in schema["properties"]["minLength"]
    assert schema["properties"]["metadata"]["default"] == {"minLength": 7, "maxLength": 9}
    assert schema["required"] == original["required"]
    assert Result.model_json_schema() == original


@pytest.mark.asyncio
@pytest.mark.parametrize("answer", ["Откройте каталог.", "", "а" * 2001])
async def test_assistant_uses_compatible_grammar_but_keeps_output_validation(monkeypatch, answer):
    import json

    class AssistantClient(RecordingClient):
        async def post(self, url, json):
            self.payloads.append(json)
            return FakeResponse(response_text)

    response_text = json.dumps({"answer": answer, "links": []})
    AssistantClient.payloads = []
    monkeypatch.setattr("app.providers.httpx.AsyncClient", AssistantClient)
    if not answer or len(answer) > 2000:
        with pytest.raises(ModelUnavailable):
            await OllamaProvider().structured("Справка", "Как купить?", PlatformAssistantOut)
    else:
        result = await OllamaProvider().structured("Справка", "Как купить?", PlatformAssistantOut)
        assert result.answer == answer
    schema = AssistantClient.payloads[0]["format"]
    assert "minLength" not in schema["properties"]["answer"]
    assert "maxLength" not in schema["properties"]["answer"]
    assert schema["properties"]["links"]["maxItems"] == 3
