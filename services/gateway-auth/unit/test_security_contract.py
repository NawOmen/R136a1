import secrets
import uuid

import jwt
import pytest
from pydantic import ValidationError

from app.config import Settings, settings
from app.schemas import RegisterIn
from app.security import create_access_token, decode_access_token, verify_password
from app.security_events import fingerprint


def test_key_is_required_and_hidden(monkeypatch):
    monkeypatch.delenv("JWT_SECRET")
    with pytest.raises(ValidationError):
        Settings(_env_file=None)
    for key in ("", "x" * 64, "dev-secret-change-me-0123456789abcdef"):
        with pytest.raises(ValidationError) as error:
            Settings(_env_file=None, jwt_secret=key)
        assert "input_value" not in str(error.value)
    key = secrets.token_urlsafe(48)
    assert key not in repr(Settings(_env_file=None, jwt_secret=key))


def test_token_requires_expiry():
    assert decode_access_token(create_access_token(uuid.uuid4()))["exp"]
    for payload in ({"sub": str(uuid.uuid4())}, {"sub": str(uuid.uuid4()), "exp": 1}):
        with pytest.raises(jwt.PyJWTError):
            decode_access_token(jwt.encode(payload, settings.jwt_secret, algorithm="HS256"))


def test_account_fingerprint_does_not_store_email():
    assert len(fingerprint("user@demo.ru")) == 64
    assert fingerprint("user@demo.ru") == fingerprint("user@demo.ru")
    assert fingerprint("user@demo.ru") != fingerprint("other@demo.ru")


def test_bcrypt_byte_limit():
    assert verify_password("я" * 100, "invalid") is False
    with pytest.raises(ValidationError):
        RegisterIn(last_name="Тест", first_name="Тест", email="test@demo.ru", password="я" * 37)
