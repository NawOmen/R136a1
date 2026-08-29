"""Хранилище файлов в MinIO (S3-совместимое)."""

import io

from minio import Minio

from .config import settings

_client = Minio(
    settings.minio_endpoint,
    access_key=settings.minio_access_key,
    secret_key=settings.minio_secret_key,
    secure=settings.minio_secure,
)


def ensure_bucket() -> None:
    if not _client.bucket_exists(settings.minio_bucket):
        _client.make_bucket(settings.minio_bucket)


def upload_object(key: str, data: bytes, content_type: str) -> str:
    ensure_bucket()
    _client.put_object(
        settings.minio_bucket,
        key,
        io.BytesIO(data),
        length=len(data),
        content_type=content_type,
    )
    return key


def delete_object(key: str) -> None:
    _client.remove_object(settings.minio_bucket, key)


def download_object(key: str) -> bytes:
    response = _client.get_object(settings.minio_bucket, key)
    try:
        return response.read()
    finally:
        response.close()
        response.release_conn()
