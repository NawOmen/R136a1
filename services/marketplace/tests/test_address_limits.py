import asyncio
import uuid

import httpx
import pytest
from fastapi import HTTPException
from sqlalchemy import text

from app.address_limits import reserve_address_request
from app.api import addresses
from conftest import make_company, make_token, make_user


@pytest.fixture(autouse=True)
async def clear_limits(db_session):
    await db_session.execute(text("DELETE FROM marketplace.address_suggestion_limits"))
    await db_session.commit()


async def test_shared_company_limit_is_atomic_persistent_and_resets_by_bucket(session_factory):
    company_id = uuid.uuid4()

    async def attempt():
        async with session_factory() as session:
            try:
                await reserve_address_request(session, company_id)
                return 200
            except HTTPException as error:
                assert error.headers == {"Retry-After": "60"}
                return error.status_code

    responses = await asyncio.gather(*(attempt() for _ in range(35)))
    assert responses.count(200) == 30 and responses.count(429) == 5
    assert await attempt() == 429
    async with session_factory() as session:
        await reserve_address_request(session, uuid.uuid4())
        await session.execute(text("UPDATE marketplace.address_suggestion_limits SET bucket = bucket - 3 WHERE company_id = :id"), {"id": company_id})
        await session.commit()
    assert await attempt() == 200


async def test_limit_applies_before_external_call_and_does_not_affect_manual_addresses(client, db_session, monkeypatch):
    user = await make_user(db_session)
    company = await make_company(db_session, user)
    headers = {"Authorization": f"Bearer {make_token(user)}"}
    monkeypatch.setattr(addresses.settings, "dadata_api_key", "synthetic-test-key")
    monkeypatch.setattr("app.address_limits.ADDRESS_REQUESTS_PER_MINUTE", 1)
    calls = []

    class Provider:
        async def __aenter__(self): return self
        async def __aexit__(self, *args): pass
        async def post(self, url, **kwargs):
            calls.append(kwargs["json"])
            raise httpx.ConnectError("synthetic outage")

    monkeypatch.setattr(addresses.httpx, "AsyncClient", lambda **kwargs: Provider())
    path = f"/api/v1/companies/{company}/address-suggestions?query=Москва"
    assert (await client.get(path, headers=headers)).status_code == 503
    limited = await client.get(path, headers=headers)
    assert limited.status_code == 429 and limited.headers["retry-after"] == "60"
    assert len(calls) == 1  # Even a failed provider request consumes a slot.
    saved = await client.post(f"/api/v1/companies/{company}/addresses", headers=headers,
                              json={"city": "Москва", "address": "Синтетический адрес, 1", "region": "Москва"})
    assert saved.status_code == 201, saved.text
    stranger = await make_user(db_session)
    denied = await client.get(path, headers={"Authorization": f"Bearer {make_token(stranger)}"})
    assert denied.status_code == 404 and len(calls) == 1
