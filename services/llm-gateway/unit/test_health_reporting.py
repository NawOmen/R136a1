"""Health must report the model and backend that actually serve requests."""
import pytest

from app import api
from app.config import settings


@pytest.mark.asyncio
async def test_health_reports_trained_mlx_backend(monkeypatch):
    monkeypatch.setattr(settings, "local_llm_backend", "mlx")
    monkeypatch.setattr(settings, "trained_model_version", "porukam-buyer-qwen3.5")
    monkeypatch.setattr(settings, "ollama_vision_model", "qwen3.5:9b")
    health = await api.health()
    assert health.local_backend == "mlx"
    assert health.local_model == "porukam-buyer-qwen3.5"
    assert health.vision_model == "qwen3.5:9b"


@pytest.mark.asyncio
async def test_health_reports_ollama_backend_by_default(monkeypatch):
    monkeypatch.setattr(settings, "local_llm_backend", "ollama")
    monkeypatch.setattr(settings, "ollama_model", "qwen3.5:9b")
    health = await api.health()
    assert health.local_backend == "ollama"
    assert health.local_model == "qwen3.5:9b"
