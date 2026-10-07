"""Проверки реальных сервисов внутри отдельной Compose-сети."""
import io
import os
import uuid

import httpx
import pytest

pytestmark = pytest.mark.skipif(os.getenv("RUN_DOCKER_INTEGRATION") != "1", reason="Только выделенный Docker-стенд")


@pytest.mark.parametrize("host,port", [("gateway-auth",8001), ("marketplace",8002), ("llm-gateway",8003), ("optimizer",8004)])
def test_live_service_health(host, port):
    assert httpx.get(f"http://{host}:{port}/health", timeout=10).status_code == 200


@pytest.mark.parametrize("host,port", [("gateway-auth",8001), ("marketplace",8002), ("llm-gateway",8003)])
def test_live_openapi_is_available(host, port):
    response = httpx.get(f"http://{host}:{port}/openapi.json", timeout=10)
    assert response.status_code == 200
    assert any(path.startswith("/api/v1/") for path in response.json()["paths"])


@pytest.mark.parametrize("host,port,path", [
    ("gateway-auth",8001,"/api/v1/auth/me"),
    ("marketplace",8002,"/api/v1/deals/mine"),
    ("llm-gateway",8003,"/api/v1/agent-runs/00000000-0000-0000-0000-000000000000"),
])
def test_live_private_routes_reject_anonymous(host, port, path):
    response = httpx.get(f"http://{host}:{port}{path}", timeout=10)
    assert response.status_code in (401, 403)


def test_real_minio_roundtrip():
    from minio import Minio

    client = Minio(os.environ["MINIO_ENDPOINT"], access_key=os.environ["MINIO_ACCESS_KEY"],
                   secret_key=os.environ["MINIO_SECRET_KEY"], secure=False)
    bucket = "e2e-" + uuid.uuid4().hex
    key = "synthetic.txt"
    payload = "Синтетический документ автоматической проверки".encode()
    client.make_bucket(bucket)

    def cleanup():
        client.remove_object(bucket, key)
        client.remove_bucket(bucket)

    try:
        client.put_object(bucket, key, io.BytesIO(payload), len(payload), content_type="text/plain; charset=utf-8")
        response = client.get_object(bucket, key)
        try:
            assert response.read() == payload
        finally:
            response.close()
            response.release_conn()
    except BaseException:
        # Ошибка удаления не должна заменить первоначальную причину падения.
        try:
            cleanup()
        except Exception:
            pass
        raise
    else:
        cleanup()
