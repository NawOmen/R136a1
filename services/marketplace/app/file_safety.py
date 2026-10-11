"""Проверка реального формата загружаемых файлов по сигнатурам.

Заявленный клиентом content_type не является доказательством формата:
подмена (например, исполняемый файл как image/png) должна отклоняться
явной ошибкой 415 до сохранения объекта и дальнейшей обработки.
SVG отклоняется всегда: векторная графика с активным содержимым
не является безопасным изображением для показа в браузере.
"""

_IMAGE_SIGNATURES = {
    "image/png": (b"\x89PNG\r\n\x1a\n",),
    "image/jpeg": (b"\xff\xd8\xff",),
    "image/webp": (b"RIFF",),
}

_PDF_SIGNATURE = b"%PDF-"


def _looks_like_svg(data: bytes) -> bool:
    head = data.lstrip()[:512].lower()
    return head.startswith(b"<svg") or (head.startswith(b"<") and b"<svg" in head[:256])


def _is_webp(data: bytes) -> bool:
    return data.startswith(b"RIFF") and len(data) >= 12 and data[8:12] == b"WEBP"


def check_upload(data: bytes, content_type: str) -> str:
    """Сверить байты с заявленным типом. Вернуть подтверждённый тип.

    Raises:
        ValueError: содержимое не соответствует заявленному формату.
    """
    media_type = (content_type or "").split(";", 1)[0].strip().lower()
    if not data:
        raise ValueError("Файл пуст")
    if media_type in _IMAGE_SIGNATURES or media_type == "application/octet-stream":
        if _looks_like_svg(data):
            raise ValueError("SVG-изображения не принимаются")
    if media_type in _IMAGE_SIGNATURES:
        if media_type == "image/webp":
            valid = _is_webp(data)
        else:
            valid = any(data.startswith(signature) for signature in _IMAGE_SIGNATURES[media_type])
        if not valid:
            raise ValueError("Содержимое не соответствует заявленному изображению")
        return media_type
    if media_type == "application/pdf":
        if not data.startswith(_PDF_SIGNATURE):
            raise ValueError("Содержимое не является PDF-документом")
        return media_type
    if media_type in ("text/plain", "text/markdown"):
        try:
            data.decode("utf-8")
        except UnicodeDecodeError:
            raise ValueError("Текстовый файл должен быть в кодировке UTF-8") from None
        return media_type
    if media_type.startswith("audio/"):
        return media_type
    return media_type
