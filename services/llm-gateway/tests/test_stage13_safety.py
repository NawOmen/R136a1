"""S13.04: выключаемый внешний маршрут, сигнатуры аудио, лимит распознавания."""

import pytest
from pydantic import BaseModel


class _Note(BaseModel):
    notes: list[str] = []


async def test_external_route_disabled_sends_nothing(monkeypatch):
    from app import providers
    from app.config import settings
    from app.providers import DeepSeekProvider, ModelUnavailable

    monkeypatch.setattr(settings, "deepseek_api_key", "")

    def _forbidden(*args, **kwargs):
        raise AssertionError("внешний вызов при выключенном маршруте")

    monkeypatch.setattr(providers.httpx, "AsyncClient", _forbidden)
    with pytest.raises(ModelUnavailable):
        await DeepSeekProvider().structured("system", "prompt", _Note)


async def test_external_route_sends_only_anonymized_context(monkeypatch):
    import json

    from app import providers
    from app.config import settings
    from app.providers import DeepSeekProvider

    monkeypatch.setattr(settings, "deepseek_api_key", "синтетический-ключ")
    calls = []

    class _Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {"choices": [{"message": {"content": json.dumps({"notes": []})}}]}

    class _Client:
        def __init__(self, *args, **kwargs):
            calls.append(kwargs)

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def post(self, url, json=None, headers=None):
            calls.append({"url": url, "json": json, "headers": headers})
            return _Response()

    monkeypatch.setattr(providers.httpx, "AsyncClient", _Client)
    await DeepSeekProvider().structured(
        "system",
        "ООО «Секретный завод», ИНН 7712345678, manager@example.ru",
        _Note,
    )
    posted = next(call for call in calls if "url" in call)
    user_text = posted["json"]["messages"][1]["content"]
    assert "Секретный" not in user_text
    assert "7712345678" not in user_text
    assert "manager@example.ru" not in user_text
    assert "api.deepseek.com" in posted["url"]
    assert posted["json"]["response_format"] == {"type": "json_object"}


async def test_transcribe_rejects_mismatched_audio(client, token, monkeypatch):
    from app import api as gateway_api

    async def _must_not_run(data, suffix):
        raise AssertionError("транскрипция не должна запускаться для чужих байтов")

    monkeypatch.setattr(gateway_api.transcriber, "transcribe", _must_not_run)
    response = await client.post(
        "/api/v1/transcribe",
        files={"file": ("note.wav", b"not audio at all", "audio/wav")},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 415, response.text


async def test_transcribe_accepts_valid_signature(client, token, monkeypatch):
    from app import api as gateway_api

    async def _fake_transcribe(data, suffix):
        return "распознанный текст"

    monkeypatch.setattr(gateway_api.transcriber, "transcribe", _fake_transcribe)
    wav = b"RIFF" + b"\x00" * 4 + b"WAVE" + b"\x00" * 100
    response = await client.post(
        "/api/v1/transcribe",
        files={"file": ("note.wav", wav, "audio/wav")},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200, response.text
    assert response.json()["text"] == "распознанный текст"


async def test_transcribe_timeout_is_bounded(client, token, monkeypatch):
    import asyncio

    from app import api as gateway_api
    from app.config import settings

    async def _slow_transcribe(data, suffix):
        await asyncio.sleep(60)
        return "поздно"

    monkeypatch.setattr(gateway_api.transcriber, "transcribe", _slow_transcribe)
    monkeypatch.setattr(settings, "transcribe_timeout_seconds", 0.05)
    wav = b"RIFF" + b"\x00" * 4 + b"WAVE" + b"\x00" * 100
    response = await client.post(
        "/api/v1/transcribe",
        files={"file": ("note.wav", wav, "audio/wav")},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 504, response.text
