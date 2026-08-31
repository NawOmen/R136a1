import json
from typing import Any

import httpx
from pydantic import BaseModel, ValidationError

from .anonymizer import anonymize_text
from .config import settings


class ModelUnavailable(RuntimeError):
    pass


def _json_from_text(value: str) -> dict[str, Any]:
    text = value.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[-1]
        text = text.rsplit("```", 1)[0]
    parsed = json.loads(text)
    if not isinstance(parsed, dict):
        raise ValueError("Модель вернула не JSON-объект")
    return parsed


class OllamaProvider:
    route_name = "local_qwen"

    async def structured(
        self, system: str, prompt: str, response_model: type[BaseModel]
    ) -> BaseModel:
        payload = {
            "model": settings.ollama_model,
            "stream": False,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": prompt},
            ],
            "format": response_model.model_json_schema(),
            "options": {
                "temperature": 0.1,
                "num_ctx": settings.llm_context_tokens,
            },
        }
        try:
            async with httpx.AsyncClient(timeout=settings.ollama_timeout_seconds) as client:
                response = await client.post(f"{settings.ollama_base_url}/api/chat", json=payload)
                response.raise_for_status()
                content = response.json()["message"]["content"]
            return response_model.model_validate(_json_from_text(content))
        except (httpx.HTTPError, KeyError, ValueError, ValidationError, json.JSONDecodeError) as exc:
            raise ModelUnavailable(f"Локальная Qwen недоступна или вернула неверный JSON: {exc}") from exc

    async def vision_text(self, image_base64: str, prompt: str) -> str:
        payload = {
            "model": settings.ollama_model,
            "stream": False,
            "messages": [
                {
                    "role": "user",
                    "content": prompt,
                    "images": [image_base64],
                }
            ],
            "options": {"temperature": 0.1, "num_ctx": settings.llm_context_tokens},
        }
        try:
            async with httpx.AsyncClient(timeout=settings.ollama_timeout_seconds) as client:
                response = await client.post(f"{settings.ollama_base_url}/api/chat", json=payload)
                response.raise_for_status()
                return str(response.json()["message"]["content"]).strip()
        except (httpx.HTTPError, KeyError, ValueError) as exc:
            raise ModelUnavailable(f"Локальное распознавание изображения недоступно: {exc}") from exc


class DeepSeekProvider:
    route_name = "external_deepseek"

    async def structured(
        self, system: str, prompt: str, response_model: type[BaseModel]
    ) -> BaseModel:
        if not settings.deepseek_api_key:
            raise ModelUnavailable("Ключ DeepSeek не настроен")
        safe_prompt = anonymize_text(prompt)
        schema_instruction = json.dumps(response_model.model_json_schema(), ensure_ascii=False)
        payload = {
            "model": settings.deepseek_model,
            "messages": [
                {
                    "role": "system",
                    "content": f"{system}\nВерни только JSON по схеме: {schema_instruction}",
                },
                {"role": "user", "content": safe_prompt},
            ],
            "temperature": 0.1,
            "response_format": {"type": "json_object"},
        }
        headers = {"Authorization": f"Bearer {settings.deepseek_api_key}"}
        try:
            async with httpx.AsyncClient(timeout=settings.deepseek_timeout_seconds) as client:
                response = await client.post(
                    f"{settings.deepseek_base_url.rstrip('/')}/chat/completions",
                    json=payload,
                    headers=headers,
                )
                response.raise_for_status()
                content = response.json()["choices"][0]["message"]["content"]
            return response_model.model_validate(_json_from_text(content))
        except (httpx.HTTPError, KeyError, IndexError, ValueError, ValidationError, json.JSONDecodeError) as exc:
            raise ModelUnavailable(f"DeepSeek недоступен или вернул неверный JSON: {exc}") from exc


class RoutedProvider:
    def __init__(self) -> None:
        self.local = OllamaProvider()
        self.external = DeepSeekProvider()

    async def structured(
        self,
        system: str,
        prompt: str,
        response_model: type[BaseModel],
        prefer_external: bool,
    ) -> tuple[BaseModel, str, str | None]:
        fallback_reason = None
        if prefer_external:
            try:
                result = await self.external.structured(system, prompt, response_model)
                return result, self.external.route_name, None
            except ModelUnavailable as exc:
                fallback_reason = str(exc)
        result = await self.local.structured(system, prompt, response_model)
        return result, getattr(self.local, "route_name", "local_qwen"), fallback_reason
