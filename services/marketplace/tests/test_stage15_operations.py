"""TLS selection is checked through the object-verification pipeline, without network storage."""
import importlib.util
from pathlib import Path
from types import SimpleNamespace
import pytest
from sqlalchemy.ext.asyncio import create_async_engine
from conftest import TEST_DATABASE_URL


def verifier():
    path = Path(__file__).resolve().parents[3] / 'scripts/verify-restored-objects.py'
    spec = importlib.util.spec_from_file_location('restored_objects', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize('source_secure,copy_value,expected', [
    (True, None, [True, True]), (True, 'false', [True, False]),
    (False, 'true', [False, True]), (False, None, [False, False])])
async def test_object_verification_honors_source_and_copy_tls(monkeypatch, source_secure, copy_value, expected):
    module = verifier()
    monkeypatch.setenv('MINIO_COPY_ENDPOINT', 'synthetic-copy:9000')
    if copy_value is None: monkeypatch.delenv('MINIO_COPY_SECURE', raising=False)
    else: monkeypatch.setenv('MINIO_COPY_SECURE', copy_value)
    monkeypatch.setattr(module.settings, 'minio_secure', source_secure)
    selected = []
    def client(endpoint, **kwargs):
        selected.append(kwargs['secure'])
        return SimpleNamespace(list_buckets=lambda: [])
    monkeypatch.setattr(module, 'Minio', client)
    monkeypatch.setattr(module, 'create_async_engine', lambda _: create_async_engine(TEST_DATABASE_URL))
    assert await module.main() == 1  # Empty storage cannot prove successful recovery.
    assert selected == expected


async def test_invalid_copy_tls_fails_before_storage_access(monkeypatch):
    module = verifier()
    monkeypatch.setenv('MINIO_COPY_ENDPOINT', 'synthetic-copy:9000')
    monkeypatch.setenv('MINIO_COPY_SECURE', 'ambiguous')
    def forbidden(*args, **kwargs): raise AssertionError('No storage access for invalid transport')
    monkeypatch.setattr(module, 'Minio', forbidden)
    with pytest.raises(ValueError, match='MINIO_COPY_SECURE'):
        await module.main()
