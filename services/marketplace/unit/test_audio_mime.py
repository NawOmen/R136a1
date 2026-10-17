from pathlib import Path
import pytest
from app.file_safety import canonical_media_type, validate_upload


@pytest.mark.asyncio
@pytest.mark.parametrize("mime",["audio/mp4","audio/x-m4a","audio/m4a","application/octet-stream",""])
async def test_browser_m4a_validated_and_stored_as_canonical_audio(mime):
    data=(Path(__file__).resolve().parents[3]/"packages/test-fixtures/buyer-evidence/voice-message.m4a").read_bytes()
    assert await validate_upload(data,canonical_media_type(data,mime,"voice.m4a")) == "audio/mp4"


@pytest.mark.asyncio
async def test_m4a_extension_does_not_bypass_binary_validation():
    data=b"<html>not audio</html>"
    with pytest.raises(ValueError):
        await validate_upload(data,canonical_media_type(data,"application/octet-stream","voice.m4a"))
    with pytest.raises(ValueError):
        await validate_upload(b"\x00\x00\x00\x20ftypM4A broken", "audio/x-m4a")
