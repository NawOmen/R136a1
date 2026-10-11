"""File decoders run only in a disposable, resource-limited subprocess."""
import io
import json
import sys
import warnings

MAX_PIXELS = 4_194_304
MAX_EXPANDED = 16 * 1024 * 1024
MAX_AUDIO_SECONDS = 300


def limits(memory_mb=512, cpu_seconds=5):
    # Production is Linux; fail closed when OS resource budgets are unavailable.
    import resource
    resource.setrlimit(resource.RLIMIT_AS, (memory_mb * 1024**2, memory_mb * 1024**2))
    resource.setrlimit(resource.RLIMIT_CPU, (cpu_seconds, cpu_seconds + 1))
    resource.setrlimit(resource.RLIMIT_FSIZE, (32 * 1024**2, 32 * 1024**2))
    resource.setrlimit(resource.RLIMIT_NOFILE, (64, 64))


def image(data, media_type):
    from PIL import Image
    Image.MAX_IMAGE_PIXELS = MAX_PIXELS
    with warnings.catch_warnings():
        warnings.simplefilter("error", Image.DecompressionBombWarning)
        with Image.open(io.BytesIO(data)) as value:
            if value.format != {"image/png": "PNG", "image/jpeg": "JPEG", "image/webp": "WEBP"}[media_type]:
                raise ValueError("Формат изображения не соответствует заявленному")
            if value.width * value.height > MAX_PIXELS or getattr(value, "n_frames", 1) != 1:
                raise ValueError("Слишком большое или многокадровое изображение")
            value.verify()
        with Image.open(io.BytesIO(data)) as value:
            value.load()


def pdf(data):
    from pypdf import PdfReader
    from pypdf.generic import StreamObject
    reader = PdfReader(io.BytesIO(data), strict=True)
    if reader.is_encrypted or not 0 < len(reader.pages) <= 30:
        raise ValueError("PDF с паролем, без страниц или более 30 страниц не принимается")
    total = 0
    # Decode referenced streams under OS memory/CPU budgets, not in the web server.
    for generation, objects in reader.xref.items():
        for object_id in objects:
            from pypdf.generic import IndirectObject
            obj = reader.get_object(IndirectObject(object_id, generation, reader))
            if isinstance(obj, StreamObject):
                total += len(obj.get_data())
                if total > MAX_EXPANDED:
                    raise ValueError("Распакованный PDF превышает 16 МБ")
    for page in reader.pages:
        page.get_contents()


def audio(data, media_type):
    import av
    allowed = {"audio/wav": {"wav"}, "audio/x-wav": {"wav"}, "audio/mpeg": {"mp3"},
               "audio/ogg": {"ogg"}, "audio/webm": {"matroska", "webm"},
               "audio/mp4": {"mov", "mp4", "m4a", "3gp", "3g2", "mj2"}}
    with av.open(io.BytesIO(data)) as container:
        if not set(container.format.name.split(",")) & allowed[media_type] or not container.streams.audio:
            raise ValueError("Аудиоконтейнер не соответствует заявленному")
        seconds = 0.0
        frames = 0
        for frame in container.decode(audio=0):
            frames += 1
            seconds += frame.samples / frame.sample_rate
            if seconds > MAX_AUDIO_SECONDS:
                raise ValueError("Аудио длиннее 5 минут")
        if not frames:
            raise ValueError("Аудио не содержит читаемых кадров")


def main():
    limits()
    try:
        data = sys.stdin.buffer.read(25 * 1024**2 + 1)
        if len(data) > 25 * 1024**2:
            raise ValueError("Файл больше 25 МБ")
        media_type = sys.argv[1]
        if media_type.startswith("image/"):
            image(data, media_type)
        elif media_type == "application/pdf":
            pdf(data)
        else:
            audio(data, media_type)
        print(json.dumps({"ok": True}))
    except Exception:
        # Decoder exception text can contain document contents or file paths.
        print(json.dumps({"ok": False}))


if __name__ == "__main__":
    main()
