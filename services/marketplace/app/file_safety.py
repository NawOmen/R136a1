"""Fail-closed format checks and bounded decoding before storing an upload."""
import asyncio
import json
import os
import subprocess
import sys
from pathlib import Path

def canonical_media_type(data: bytes, content_type: str, name: str = "") -> str:
    media = (content_type or "").split(";", 1)[0].strip().lower()
    media = {"audio/x-m4a": "audio/mp4", "audio/m4a": "audio/mp4", "audio/mp3": "audio/mpeg"}.get(media, media)
    # Browsers sometimes omit MIME for M4A. Extension AND container signature are
    # required; the bounded decoder still checks the actual stream afterwards.
    if media in {"", "application/octet-stream"} and name.lower().endswith(".m4a"):
        if len(data) >= 12 and data[4:8] == b"ftyp":
            return "audio/mp4"
    return media


SUPPORTED = {"image/png", "image/jpeg", "image/webp", "application/pdf", "text/plain", "text/markdown",
             "audio/wav", "audio/x-wav", "audio/mpeg", "audio/ogg", "audio/webm", "audio/mp4"}
VALIDATION_TIMEOUT = 6
_slots = asyncio.Semaphore(1)


def check_upload(data: bytes, content_type: str) -> str:
    media_type = canonical_media_type(data, content_type)
    if not data:
        raise ValueError("Файл пуст")
    if len(data) > 25 * 1024**2:
        raise ValueError("Файл больше 25 МБ")
    if media_type not in SUPPORTED:
        raise ValueError("Неподдерживаемый формат файла; SVG и HTML не принимаются")
    if media_type in {"text/plain", "text/markdown"}:
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError:
            raise ValueError("Текстовый файл должен быть в кодировке UTF-8") from None
        if "\x00" in text or text.lstrip().lower().startswith(("<svg", "<!doctype html", "<html")):
            raise ValueError("Содержимое не является обычным текстом")
        return media_type
    try:
        result = subprocess.run([sys.executable, str(Path(__file__).with_name("file_safety_worker.py")), media_type],
            input=data, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=VALIDATION_TIMEOUT, check=False,
            env={key: os.environ[key] for key in ("PATH", "SYSTEMROOT") if key in os.environ})
        if result.returncode or not json.loads(result.stdout).get("ok"):
            raise ValueError("Файл повреждён, не соответствует формату или превышает предел обработки")
    except (subprocess.TimeoutExpired, json.JSONDecodeError, OSError):
        raise ValueError("Файл не прошёл проверку за допустимое время") from None
    return media_type


async def validate_upload(data: bytes, content_type: str) -> str:
    media_type = canonical_media_type(data, content_type)
    if media_type not in SUPPORTED or not data or len(data) > 25 * 1024**2 or media_type.startswith("text/"):
        return check_upload(data, content_type)
    try:
        await asyncio.wait_for(_slots.acquire(), timeout=VALIDATION_TIMEOUT)
    except TimeoutError:
        raise ValueError("Проверка файлов занята; повторите загрузку позже") from None
    try:
        process = await asyncio.create_subprocess_exec(sys.executable,
            str(Path(__file__).with_name("file_safety_worker.py")), media_type,
            stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
            env={key: os.environ[key] for key in ("PATH", "SYSTEMROOT") if key in os.environ})
        try:
            output, _ = await asyncio.wait_for(process.communicate(data), timeout=VALIDATION_TIMEOUT)
        except BaseException:
            if process.returncode is None:
                process.kill()
            await process.wait()
            raise
        if process.returncode or not json.loads(output).get("ok"):
            raise ValueError("Файл повреждён, не соответствует формату или превышает предел обработки")
    except (TimeoutError, json.JSONDecodeError, OSError):
        raise ValueError("Файл не прошёл проверку за допустимое время") from None
    finally:
        _slots.release()
    return media_type
