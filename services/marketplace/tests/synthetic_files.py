"""Real, tiny synthetic fixtures: headers alone must never be accepted as files."""
import io
import wave

from PIL import Image
from pypdf import PdfWriter


def image(kind):
    stream = io.BytesIO()
    Image.new("RGB", (8, 8), (130, 170, 210)).save(stream, format=kind)
    return stream.getvalue()


PNG, JPEG, WEBP = (image(kind) for kind in ("PNG", "JPEG", "WEBP"))
stream = io.BytesIO()
writer = PdfWriter()
writer.add_blank_page(width=72, height=72)
writer.write(stream)
PDF = stream.getvalue()
stream = io.BytesIO()
with wave.open(stream, "wb") as output:
    output.setnchannels(1)
    output.setsampwidth(2)
    output.setframerate(8000)
    output.writeframes(b"\x00\x00" * 800)
WAV = stream.getvalue()
