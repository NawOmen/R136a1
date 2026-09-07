import os

import pytest

from app.providers import OllamaProvider
from app.schemas import PlatformAssistantOut, RawExtraction


@pytest.mark.ollama
@pytest.mark.asyncio
@pytest.mark.skipif(
    os.getenv("RUN_OLLAMA_SMOKE") != "1",
    reason="Требуется локальная Ollama и RUN_OLLAMA_SMOKE=1",
)
async def test_real_ollama_returns_structured_result():
    result = await OllamaProvider().structured(
        "Извлеки требования. Не выдумывай отсутствующие значения.",
        "Нужно 5000 бумажных стаканов в Москву за 10 дней.",
        RawExtraction,
    )

    assert result.category


@pytest.mark.ollama
@pytest.mark.asyncio
@pytest.mark.skipif(
    os.getenv("RUN_OLLAMA_SMOKE") != "1",
    reason="Требуется локальная Ollama и RUN_OLLAMA_SMOKE=1",
)
async def test_real_ollama_returns_platform_assistant_answer():
    result = await OllamaProvider().structured(
        "Ты помощник ПоРукам. Каталог доступен по /catalog. Отвечай кратко по-русски.",
        "Где найти товары?",
        PlatformAssistantOut,
    )
    assert 1 <= len(result.answer) <= 2000
    assert len(result.links) <= 3
