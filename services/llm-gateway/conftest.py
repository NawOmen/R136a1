"""Ephemeral keys for tests only; production settings have no signing-key fallback."""
import os
import secrets

os.environ.setdefault("JWT_SECRET", secrets.token_urlsafe(48))
os.environ.setdefault("OPTIMIZER_TOKEN", secrets.token_urlsafe(48))
