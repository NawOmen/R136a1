import json
import re
from copy import deepcopy
from typing import Any

import httpx
from pydantic import BaseModel, ValidationError

from .anonymizer import anonymize_text
from .config import settings


class ModelUnavailable(RuntimeError):
    pass


def _ollama_schema(response_model: type[BaseModel]) -> dict[str, Any]:
    """Ограничения длины проверяет Pydantic, а не несовместимая грамматика Ollama."""
    schema = deepcopy(response_model.model_json_schema())

    def visit(node: Any) -> None:
        if not isinstance(node, dict):
            return
        node.pop("minLength", None)
        node.pop("maxLength", None)
        # Обходим только узлы схемы: имена полей, default и examples — данные.
        for keyword in ("properties", "patternProperties", "$defs", "definitions", "dependentSchemas"):
            for child in node.get(keyword, {}).values():
                visit(child)
        for keyword in ("items", "additionalProperties", "contains", "not", "if", "then", "else", "propertyNames"):
            visit(node.get(keyword))
        for keyword in ("anyOf", "allOf", "oneOf", "prefixItems"):
            for child in node.get(keyword, []):
                visit(child)

    visit(schema)
    return schema


_REASONING_BLOCK = re.compile(r"^\s*<(?:think|thinking)>.*?</(?:think|thinking)>\s*", re.S)


def _json_from_text(value: str) -> dict[str, Any]:
    text = value.strip()
    # Снимаем только явно размеченный блок размышлений в начале ответа.
    # JSON, в строках которого встречается текст, не изменяется.
    if text.startswith("<think"):
        text = _REASONING_BLOCK.sub("", text).strip()
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
            "think": False,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": prompt},
            ],
            "format": _ollama_schema(response_model),
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
            raise ModelUnavailable("Локальная модель недоступна или вернула неверный JSON") from exc

    async def vision_text(self, image_base64: str, prompt: str) -> str:
        payload = {
            "model": settings.ollama_vision_model,
            "stream": False,
            "think": False,
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
            raise ModelUnavailable("Локальное распознавание изображения недоступно") from exc


class TrainedMLXProvider:
    # Сохраняем версионированный идентификатор маршрута существующего API.
    # Конкретная версия адаптера сохраняется отдельно в model_version.
    route_name = "local_qwen"

    async def structured(
        self, system: str, prompt: str, response_model: type[BaseModel]
    ) -> BaseModel:
        schema = json.dumps(response_model.model_json_schema(), ensure_ascii=False)
        # Размышления выключены на сервере и подтверждены мягким переключателем.
        system_content = f"{system}\nВерни только JSON по схеме: {schema}\n/no_think"
        payload = {
            # MLX server связывает default_model с --model и --adapter-path.
            # Произвольное имя здесь заставило бы сервер искать другую модель.
            "model": "default_model",
            "stream": False,
            "temperature": 0,
            "max_tokens": settings.mlx_max_tokens,
            "messages": [
                {"role": "system", "content": system_content},
                {"role": "user", "content": prompt},
            ],
        }
        # chat_template_kwargs здесь не передаём: mlx_lm.server 0.32 на этом поле
        # роняет поток генерации («generation thread died») и отвечает 404, после
        # чего сервер жив только до перезапуска. Размышления отключает серверный
        # `--chat-template-args` при старте модели плюс мягкий `/no_think` выше.
        url = f"{settings.mlx_base_url.rstrip('/')}/v1/chat/completions"
        try:
            async with httpx.AsyncClient(timeout=settings.mlx_timeout_seconds) as client:
                response = await client.post(url, json=payload)
                response.raise_for_status()
                data = response.json()
            content = data["choices"][0]["message"]["content"]
            if not isinstance(content, str):
                raise ValueError("Ожидался текст JSON")
            return response_model.model_validate(_json_from_text(content))
        except (httpx.HTTPError, KeyError, IndexError, TypeError, ValueError, ValidationError) as exc:
            # Без скрытого переключения на базовую модель или внешний сервис.
            raise ModelUnavailable("Обученная локальная модель недоступна или вернула неверный JSON") from exc

    async def vision_text(self, image_base64: str, prompt: str) -> str:
        # Адаптер обучен извлечению текста; vision остаётся отдельным маршрутом.
        return await OllamaProvider().vision_text(image_base64, prompt)


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
            raise ModelUnavailable("DeepSeek недоступен или вернул неверный JSON") from exc


class RoutedProvider:
    def __init__(self) -> None:
        self.local = TrainedMLXProvider() if settings.local_llm_backend == "mlx" else OllamaProvider()
        # Разговорные задачи (справка, объяснение совместимости) идут в общую модель:
        # обученный адаптер отвечает по фактам, а не беседует.
        self.assistant = OllamaProvider() if settings.assistant_llm_backend == "ollama" else self.local
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
        try:
            result = await self.local.structured(system, prompt, response_model)
        except ModelUnavailable as trained_error:
            # Адаптер обучен извлечению фактов и на части категорий возвращает
            # некорректный ответ. Общая локальная модель обслуживается тем же
            # контрактом; подмена не скрывается — маршрут и модель пишутся в прогон.
            if self.assistant is self.local:
                raise
            try:
                result = await self.assistant.structured(system, prompt, response_model)
            except ModelUnavailable:
                raise trained_error
            return result, "local_general", f"Обученный адаптер не разобрал запрос: {trained_error}"
        return result, getattr(self.local, "route_name", "local_qwen"), fallback_reason
