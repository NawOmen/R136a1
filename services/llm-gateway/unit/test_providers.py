import json

import pytest
from pydantic import BaseModel, Field

from app.config import settings
from app.providers import ModelUnavailable, OllamaProvider, _ollama_schema
from app.schemas import PlatformAssistantOut, RawExtraction


@pytest.mark.parametrize("local,assistant", [("mlx", "ollama"), ("ollama", "mlx"), ("ollama", "ollama"), ("mlx", "mlx")])
def test_assistant_backend_and_route_match_the_actual_model(monkeypatch, local, assistant):
    from app.providers import RoutedProvider, TrainedMLXProvider
    monkeypatch.setattr(settings, "local_llm_backend", local)
    monkeypatch.setattr(settings, "assistant_llm_backend", assistant)
    provider = RoutedProvider()
    assert isinstance(provider.assistant, OllamaProvider if assistant == "ollama" else TrainedMLXProvider)
    assert (provider.assistant is provider.local) == (local == assistant)
    if local == "mlx" and assistant == "ollama":
        assert provider.assistant.route_name == "local_general"
    if local == "ollama" and assistant == "mlx":
        assert provider.assistant.route_name == "local_trained"


@pytest.mark.asyncio
async def test_trained_failure_uses_general_model_and_reports_fallback(monkeypatch):
    from app.providers import RoutedProvider
    monkeypatch.setattr(settings, "local_llm_backend", "mlx")
    monkeypatch.setattr(settings, "assistant_llm_backend", "ollama")
    provider = RoutedProvider()
    async def broken(*args):
        raise ModelUnavailable("синтетический сбой адаптера")
    async def general(*args):
        return RawExtraction(category="Крепёж", facts=[])
    monkeypatch.setattr(provider.local, "structured", broken)
    monkeypatch.setattr(provider.assistant, "structured", general)
    result, route, reason = await provider.structured("system", "prompt", RawExtraction, False)
    assert result.category == "Крепёж" and route == "local_general"
    assert "сбой адаптера" in reason


@pytest.mark.asyncio
async def test_same_ollama_backend_is_not_retried_as_a_different_model(monkeypatch):
    from app.providers import RoutedProvider
    monkeypatch.setattr(settings, "local_llm_backend", "ollama")
    monkeypatch.setattr(settings, "assistant_llm_backend", "ollama")
    provider = RoutedProvider()
    calls = []
    async def broken(*args):
        calls.append(True)
        raise ModelUnavailable("синтетический сбой")
    monkeypatch.setattr(provider.local, "structured", broken)
    with pytest.raises(ModelUnavailable):
        await provider.structured("system", "prompt", RawExtraction, False)
    assert len(calls) == 1


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


@pytest.mark.asyncio
async def test_trained_mlx_default_route_and_validated_json(monkeypatch):
    from app.providers import RoutedProvider, TrainedMLXProvider
    class MLXResponse(FakeResponse):
        def json(self):
            return {"choices": [{"message": {"content": self.content}}]}
    class MLXClient(RecordingClient):
        async def post(self, url, json):
            assert url.endswith('/v1/chat/completions')
            self.payloads.append(json)
            return MLXResponse('{"category":"Крепёж","facts":[]}')
    MLXClient.payloads = []
    monkeypatch.setattr(settings, 'local_llm_backend', 'mlx')
    monkeypatch.setattr('app.providers.httpx.AsyncClient', MLXClient)
    provider = RoutedProvider()
    assert isinstance(provider.local, TrainedMLXProvider)
    result, route, fallback = await provider.structured('system', 'prompt', RawExtraction, False)
    assert result.category == 'Крепёж' and route == 'local_qwen' and fallback is None
    payload = MLXClient.payloads[0]
    assert payload['model'] == 'default_model'
    assert payload['temperature'] == 0 and payload['stream'] is False
    assert payload['max_tokens'] == 640
    assert 'properties' in payload['messages'][0]['content']


@pytest.mark.asyncio
@pytest.mark.parametrize('content', ['not json', '{}', '[]'])
async def test_trained_mlx_bad_response_fails_without_base_fallback(monkeypatch, content):
    from app.providers import TrainedMLXProvider
    class BadResponse(FakeResponse):
        def json(self):
            return {'choices': [{'message': {'content': content}}]}
    class Client(RecordingClient):
        async def post(self, url, json):
            assert '/api/chat' not in url
            return BadResponse(content)
    monkeypatch.setattr('app.providers.httpx.AsyncClient', Client)
    with pytest.raises(ModelUnavailable):
        await TrainedMLXProvider().structured('s', 'p', RawExtraction)


@pytest.mark.asyncio
async def test_trained_mlx_network_failure_does_not_call_ollama(monkeypatch):
    import httpx
    from app.providers import TrainedMLXProvider
    urls = []
    class Client(RecordingClient):
        async def post(self, url, json):
            urls.append(url)
            raise httpx.ConnectError('synthetic unavailable')
    monkeypatch.setattr('app.providers.httpx.AsyncClient', Client)
    with pytest.raises(ModelUnavailable):
        await TrainedMLXProvider().structured('s', 'p', RawExtraction)
    assert len(urls) == 1 and urls[0].endswith('/v1/chat/completions')


@pytest.mark.asyncio
async def test_trained_text_keeps_vision_separate(monkeypatch):
    from app.providers import TrainedMLXProvider
    RecordingClient.payloads = []
    monkeypatch.setattr('app.providers.httpx.AsyncClient', RecordingClient)
    await TrainedMLXProvider().vision_text('synthetic', 'p')
    assert RecordingClient.payloads[0]['model'] == settings.ollama_vision_model
    assert 'images' in RecordingClient.payloads[0]['messages'][0]


@pytest.mark.asyncio
async def test_trained_mlx_always_disables_thinking(monkeypatch):
    from app.providers import TrainedMLXProvider
    class MLXResponse(FakeResponse):
        def json(self):
            return {"choices": [{"message": {"content": '{"category":"Крепёж","facts":[]}'}}]}
    class Client(RecordingClient):
        async def post(self, url, json):
            self.payloads.append(dict(json))
            return MLXResponse("ok")
    Client.payloads = []
    monkeypatch.setattr("app.providers.httpx.AsyncClient", Client)
    await TrainedMLXProvider().structured("s", "p", RawExtraction)
    payload = Client.payloads[0]
    # Размышления выключены серверным --chat-template-args и мягким /no_think.
    assert payload["messages"][0]["content"].rstrip().endswith("/no_think")
    assert payload["max_tokens"] == settings.mlx_max_tokens
    assert not hasattr(settings, "mlx_enable_thinking")


@pytest.mark.asyncio
async def test_trained_mlx_never_sends_chat_template_kwargs(monkeypatch):
    """mlx_lm.server 0.32 на этом поле роняет поток генерации и отвечает 404 до перезапуска."""
    from app.providers import TrainedMLXProvider
    class MLXResponse(FakeResponse):
        def json(self):
            return {"choices": [{"message": {"content": '{"category":"Крепёж","facts":[]}'}}]}
    class Client(RecordingClient):
        async def post(self, url, json):
            self.payloads.append(dict(json))
            return MLXResponse("ok")
    Client.payloads = []
    monkeypatch.setattr("app.providers.httpx.AsyncClient", Client)
    await TrainedMLXProvider().structured("s", "p", RawExtraction)
    assert len(Client.payloads) == 1
    assert "chat_template_kwargs" not in Client.payloads[0]
    assert "enable_thinking" not in json.dumps(Client.payloads[0])


@pytest.mark.asyncio
async def test_tagged_reasoning_block_is_stripped_before_json(monkeypatch):
    from app.providers import TrainedMLXProvider
    class MLXResponse(FakeResponse):
        def json(self):
            return {"choices": [{"message": {"content": '<think>долго рассуждал</think>{"category":"Крепёж","facts":[]}'}}]}
    class Client(RecordingClient):
        async def post(self, url, json):
            return MLXResponse("ok")
    monkeypatch.setattr("app.providers.httpx.AsyncClient", Client)
    result = await TrainedMLXProvider().structured("s", "p", RawExtraction)
    assert result.category == "Крепёж"
