import asyncio
import base64
import json
import os
import sys
from pathlib import Path

from .providers import ModelUnavailable, OllamaProvider


def canonical_media_type(data: bytes, content_type: str, name: str = "") -> str:
    media = (content_type or "").split(";", 1)[0].strip().lower()
    media = {"audio/x-m4a": "audio/mp4", "audio/m4a": "audio/mp4", "audio/mp3": "audio/mpeg"}.get(media, media)
    # Browsers sometimes omit MIME for M4A. Extension AND container signature are
    # required; the bounded decoder still checks the actual stream afterwards.
    if media in {"", "application/octet-stream"} and name.lower().endswith(".m4a"):
        if len(data) >= 12 and data[4:8] == b"ftyp":
            return "audio/mp4"
    return media


class UnreadableMaterial(ValueError):
    pass


_slots = asyncio.Semaphore(1)


async def bounded_decode(operation, data, options, *, timeout=6):
    """Cancellation/timeout kills and reaps the native worker before releasing a slot."""
    async with _slots:
        env = {key: os.environ[key] for key in ("PATH", "HOME", "TMPDIR", "HF_HOME", "XDG_CACHE_HOME") if key in os.environ}
        env.update({"OPENBLAS_NUM_THREADS": "1", "OMP_NUM_THREADS": "2", "MKL_NUM_THREADS": "1"})
        process = await asyncio.create_subprocess_exec(sys.executable,
            str(Path(__file__).with_name("file_worker.py")), operation, json.dumps(options),
            stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL, env=env)
        try:
            output, _ = await asyncio.wait_for(process.communicate(data), timeout=timeout)
        except BaseException:
            if process.returncode is None:
                process.kill()
            await process.wait()
            raise
        if process.returncode:
            raise UnreadableMaterial("Файл повреждён или превышает предел ресурсов обработки")
        try:
            value = json.loads(output)
            if value.get("error") == "whisper_unavailable":
                raise ModelUnavailable("Локальная модель Whisper не подготовлена или недоступна")
            if not value.get("ok"):
                raise UnreadableMaterial("Файл повреждён, защищён паролем или превышает предел обработки")
            return value["value"]
        except (ValueError, KeyError):
            raise UnreadableMaterial("Файл не прошёл безопасную проверку") from None


class LocalTranscriber:
    _lock = asyncio.Lock()

    async def transcribe(self, data: bytes, suffix: str) -> str:
        from .config import settings
        media_type = {".wav": "audio/wav", ".ogg": "audio/ogg", ".mp3": "audio/mpeg",
                      ".webm": "audio/webm", ".m4a": "audio/mp4"}.get(suffix)
        if not media_type:
            raise UnreadableMaterial("Неподдерживаемый аудиоформат")
        if self._lock.locked():
            raise UnreadableMaterial("Распознавание занято; повторите запрос позже")
        async with self._lock:
            return await bounded_decode("speech", data,
                {"media_type": media_type, "suffix": suffix, "model": settings.whisper_model,
                 "device": settings.whisper_device, "compute_type": settings.whisper_compute_type,
                 "max_chars": settings.max_combined_text_chars, "cpu_seconds": settings.transcribe_timeout_seconds},
                timeout=settings.transcribe_timeout_seconds)


async def image_to_text(data: bytes, provider: OllamaProvider) -> str:
    encoded = base64.b64encode(data).decode("ascii")
    return await provider.vision_text(encoded,
        "Опиши по-русски только видимые характеристики товара и весь читаемый текст. "
        "Не угадывай материал или покрытие, если они не видны.")


async def pdf_to_text(data: bytes, provider: OllamaProvider) -> str:
    from .config import settings
    try:
        parsed = await bounded_decode("pdf", data, {"max_chars": settings.max_combined_text_chars})
    except TimeoutError:
        raise UnreadableMaterial("Проверка PDF превысила допустимое время") from None
    pages, total = [], 0
    for number, page in enumerate(parsed, 1):
        value = page["text"]
        if page["image"] is not None:
            value = await image_to_text(base64.b64decode(page["image"]), provider)
        total += len(value)
        if total > settings.max_combined_text_chars:
            raise UnreadableMaterial("Распознанный PDF превышает предел текста; разделите материал")
        pages.append(f"[[Страница {number}]]\n{value}")
    return "\n".join(pages)


async def validated_audio(data, media_type):
    if media_type not in {"audio/wav", "audio/x-wav", "audio/mpeg", "audio/ogg", "audio/webm", "audio/mp4"}:
        raise UnreadableMaterial("Неподдерживаемый аудиоформат")
    try:
        await bounded_decode("audio", data, {"media_type": media_type})
    except TimeoutError:
        raise UnreadableMaterial("Проверка аудио превысила допустимое время") from None


async def transcribe_material(data, media_type, transcriber):
    media_type = canonical_media_type(data, media_type)
    from .config import settings
    async def work():
        await validated_audio(data, media_type)
        suffix = {"audio/wav": ".wav", "audio/x-wav": ".wav", "audio/mpeg": ".mp3",
                  "audio/ogg": ".ogg", "audio/webm": ".webm", "audio/mp4": ".m4a"}[media_type]
        return await transcriber.transcribe(data, suffix)
    # Queue wait and decoder validation are included in the same audio deadline.
    return await asyncio.wait_for(work(), timeout=settings.transcribe_timeout_seconds)


async def _material_to_text(name, content_type, data, provider, transcriber) -> tuple[str, str]:
    media_type = canonical_media_type(data, content_type, name)
    try:
        if media_type in {"text/plain", "text/markdown", "text/csv"}:
            value = data.decode("utf-8")
            if "\x00" in value:
                raise UnreadableMaterial("Текст содержит бинарные данные")
            return value, "document"
        if media_type == "application/pdf":
            return await pdf_to_text(data, provider), "document"
        if media_type in {"image/png", "image/jpeg", "image/webp"}:
            await bounded_decode("image", data, {"media_type": media_type})
            return await image_to_text(data, provider), "image"
        if media_type.startswith("audio/"):
            value = await transcribe_material(data, media_type, transcriber)
            if not value:
                raise UnreadableMaterial("В аудиофайле не удалось распознать речь")
            return value, "audio"
    except (TimeoutError, UnicodeDecodeError, OSError, ValueError) as exc:
        if isinstance(exc, UnreadableMaterial):
            raise
        raise UnreadableMaterial("Материал повреждён или превышает допустимое время обработки") from None
    raise UnreadableMaterial("Поддерживаются UTF-8 текст, PDF, PNG/JPEG/WebP и аудио")


async def material_to_text(name, content_type, data, provider, transcriber) -> tuple[str, str]:
    from .config import settings
    try:
        return await asyncio.wait_for(_material_to_text(name, content_type, data, provider, transcriber),
                                      timeout=settings.material_processing_timeout_seconds)
    except TimeoutError:
        raise UnreadableMaterial("Обработка материала превысила допустимое время") from None
