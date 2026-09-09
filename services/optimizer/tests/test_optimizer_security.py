import pytest
from httpx import ASGITransport, AsyncClient
from pydantic import ValidationError

from app.main import app
from app.security import Settings, require_service_token, settings
from app.schemas import AllocationRequest
from fastapi import HTTPException


@pytest.mark.asyncio
async def test_token_fail_closed():
    with pytest.raises(ValidationError):
        Settings(_env_file=None, optimizer_token="")
    for token in (None, "wrong", "я" * 64):
        with pytest.raises(HTTPException) as error:
            await require_service_token(token)
        assert error.value.status_code == 401
    await require_service_token(settings.optimizer_token)


@pytest.mark.asyncio
async def test_optimizer_api_requires_service_key():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        assert (await client.get("/health")).status_code == 200
        for path in ("/optimize/allocations", "/optimize/coalition", "/optimize/resilience", "/score/opportunity"):
            assert (await client.post("/api/v1" + path, json={})).status_code == 401
        response = await client.post("/api/v1/score/opportunity", json={},
                                     headers={"X-Optimizer-Token": settings.optimizer_token})
        assert response.status_code == 422


def test_optimizer_producer_limit():
    with pytest.raises(ValidationError):
        AllocationRequest.model_validate({"producers": [{}] * 26, "demand_units": 1, "deadline_days": 1})
