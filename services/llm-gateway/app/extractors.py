import asyncio
import base64
import os
import tempfile
from pathlib import Path

import pymupdf as fitz

from .providers import OllamaProvider


class UnreadableMaterial(ValueError):
    pass


class LocalTranscriber:
    _model = None
    _lock = asyncio.Lock()

    async def transcribe(self, data: bytes, suffix: str) -> str:
        async with self._lock:
            return await asyncio.to_thread(self._transcribe_sync, data, suffix)

    def _transcribe_sync(self, data: bytes, suffix: str) -> str:
        from faster_whisper import WhisperModel

        if self._model is None:
            from .config import settings

            self._model = WhisperModel(
                settings.whisper_model,
                device=settings.whisper_device,
                compute_type=settings.whisper_compute_type,
            )
        path = ""
        try:
            with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
                tmp.write(data)
                path = tmp.name
            segments, _ = self._model.transcribe(path, language="ru", vad_filter=True)
            return "\n".join(
                f"[[{segment.start:.2f}-{segment.end:.2f} с]] {segment.text.strip()}"
                for segment in segments
            ).strip()
        finally:
            if path:
                os.unlink(path)


async def image_to_text(data: bytes, provider: OllamaProvider) -> str:
    encoded = base64.b64encode(data).decode("ascii")
    return await provider.vision_text(
        encoded,
        "Опиши по-русски только видимые характеристики товара и весь читаемый текст. "
        "Не угадывай материал или покрытие, если они не видны.",
    )


async def pdf_to_text(data: bytes, provider: OllamaProvider) -> str:
    try:
        document = fitz.open(stream=data, filetype="pdf")
    except Exception as exc:
        raise UnreadableMaterial("PDF повреждён или не читается") from exc
    try:
        if len(document) == 0:
            raise UnreadableMaterial("PDF не содержит страниц")
        if len(document) > 30:
            raise UnreadableMaterial("PDF содержит больше 30 страниц; разделите материал")
        from .config import settings
        pages, total = [], 0
        for number, page in enumerate(document, 1):
            value = page.get_text("text").strip()
            if not value:
                scale = min(1.5, 2048 / max(page.rect.width, page.rect.height, 1))
                pixmap = page.get_pixmap(matrix=fitz.Matrix(scale, scale), alpha=False)
                value = await image_to_text(pixmap.tobytes("png"), provider)
            total += len(value)
            if total > settings.max_combined_text_chars:
                raise UnreadableMaterial("Распознанный PDF превышает предел текста; разделите материал")
            pages.append(f"[[Страница {number}]]\n{value}")
        return "\n".join(pages)
    finally:
        document.close()


async def material_to_text(
    name: str,
    content_type: str,
    data: bytes,
    provider: OllamaProvider,
    transcriber: LocalTranscriber,
) -> tuple[str, str]:
    suffix = Path(name).suffix.lower()
    if content_type.startswith("text/") or suffix in {".md", ".txt", ".csv"}:
        try:
            return data.decode("utf-8"), "document"
        except UnicodeDecodeError as exc:
            raise UnreadableMaterial("Текстовый файл должен быть в UTF-8") from exc
    if content_type == "application/pdf" or suffix == ".pdf":
        return await pdf_to_text(data, provider), "document"
    if content_type.startswith("image/"):
        return await image_to_text(data, provider), "image"
    if content_type.startswith("audio/") or suffix in {".m4a", ".mp3", ".wav", ".ogg"}:
        text = await transcriber.transcribe(data, suffix or ".audio")
        if not text:
            raise UnreadableMaterial("В аудиофайле не удалось распознать речь")
        return text, "audio"
    raise UnreadableMaterial("Поддерживаются текст, PDF, изображения и аудио")
