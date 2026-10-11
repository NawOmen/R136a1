"""Disposable native decoder. No web/database configuration or external LLM calls."""
import base64
import io
import json
import math
import sys
import warnings


def image_check(data, media_type):
    from PIL import Image
    Image.MAX_IMAGE_PIXELS = 4_194_304
    with warnings.catch_warnings():
        warnings.simplefilter("error", Image.DecompressionBombWarning)
        with Image.open(io.BytesIO(data)) as image:
            expected = {"image/png": "PNG", "image/jpeg": "JPEG", "image/webp": "WEBP"}[media_type]
            if image.format != expected or image.width * image.height > 4_194_304 or getattr(image, "n_frames", 1) != 1:
                raise ValueError()
            image.verify()
        with Image.open(io.BytesIO(data)) as image:
            image.load()


def audio_check(data, media_type):
    import av
    formats = {"audio/wav": {"wav"}, "audio/x-wav": {"wav"}, "audio/mpeg": {"mp3"},
               "audio/ogg": {"ogg"}, "audio/webm": {"matroska", "webm"},
               "audio/mp4": {"mov", "mp4", "m4a", "3gp", "3g2", "mj2"}}
    with av.open(io.BytesIO(data)) as container:
        if not set(container.format.name.split(",")) & formats[media_type] or not container.streams.audio:
            raise ValueError()
        seconds, frames = 0.0, 0
        for frame in container.decode(audio=0):
            frames += 1
            seconds += frame.samples / frame.sample_rate
            if seconds > 300:
                raise ValueError()
        if not frames:
            raise ValueError()


def pdf_pages(data, max_chars):
    import pymupdf as fitz
    with fitz.open(stream=data, filetype="pdf") as document:
        if document.needs_pass or not 0 < len(document) <= 30:
            raise ValueError()
        expanded = 0
        for xref in range(1, document.xref_length()):
            if document.xref_is_stream(xref):
                expanded += len(document.xref_stream(xref))
                if expanded > 16 * 1024**2:
                    raise ValueError()
        pages, chars, rendered = [], 0, 0
        for page in document:
            text = page.get_text("text").strip()
            chars += len(text)
            if chars > max_chars:
                raise ValueError()
            image = None
            if not text:
                scale = min(1.5, 2048 / max(page.rect.width, page.rect.height, 1))
                pixmap = page.get_pixmap(matrix=fitz.Matrix(scale, scale), alpha=False)
                png = pixmap.tobytes("png")
                rendered += len(png)
                if rendered > 20 * 1024**2:
                    raise ValueError()
                image = base64.b64encode(png).decode("ascii")
            pages.append({"text": text, "image": image})
        return pages


class WhisperUnavailable(RuntimeError):
    pass


def speech(data, options):
    from faster_whisper import WhisperModel
    audio_check(data, options["media_type"])
    try:
        model = WhisperModel(options["model"], device=options["device"], compute_type=options["compute_type"],
                             cpu_threads=2, local_files_only=True)
    except Exception:
        raise WhisperUnavailable() from None
    segments, _ = model.transcribe(io.BytesIO(data), language="ru", vad_filter=True)
    values, chars = [], 0
    for segment in segments:
        value = f"[[{segment.start:.2f}-{segment.end:.2f} с]] {segment.text.strip()}"
        chars += len(value)
        if chars > options["max_chars"]:
            raise ValueError()
        values.append(value)
    return "\n".join(values).strip()



def main():
    operation, options = sys.argv[1], json.loads(sys.argv[2])
    import resource
    memory = (2048 if operation == "speech" else 512) * 1024**2
    cpu = max(1, math.ceil(options.get("cpu_seconds", 5)))
    resource.setrlimit(resource.RLIMIT_AS, (memory, memory))
    resource.setrlimit(resource.RLIMIT_CPU, (cpu, cpu + 1))
    file_limit = 32 * 1024**2
    resource.setrlimit(resource.RLIMIT_FSIZE, (file_limit, file_limit))
    resource.setrlimit(resource.RLIMIT_NOFILE, (64, 64))
    try:
        data = sys.stdin.buffer.read(25 * 1024**2 + 1)
        if not data or len(data) > 25 * 1024**2:
            raise ValueError()
        if operation == "pdf":
            value = pdf_pages(data, options["max_chars"])
        elif operation == "image":
            image_check(data, options["media_type"])
            value = True
        elif operation == "audio":
            audio_check(data, options["media_type"])
            value = True
        elif operation == "speech":
            value = speech(data, options)
        else:
            raise ValueError()
        print(json.dumps({"ok": True, "value": value}))
    except WhisperUnavailable:
        print(json.dumps({"ok": False, "error": "whisper_unavailable"}))
    except Exception:
        print(json.dumps({"ok": False}))


if __name__ == "__main__":
    main()
