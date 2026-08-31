import os

import pytest

from app.providers import OllamaProvider
from app.schemas import RawExtraction


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
