import uuid
from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi import HTTPException

from app.api import addresses
from app.deps import CurrentUser


@pytest.mark.asyncio
async def test_suggestions_check_scope_before_using_provider(monkeypatch):
    membership = AsyncMock(side_effect=HTTPException(403, "Нет доступа"))
    monkeypatch.setattr(addresses, "require_company_buyer", membership)
    with pytest.raises(HTTPException) as error:
        await addresses.suggest_addresses(uuid.uuid4(), "Москва", CurrentUser(uuid.uuid4()), object())
    assert error.value.status_code == 403


@pytest.mark.asyncio
async def test_missing_provider_is_explicit_and_manual_entry_remains_possible(monkeypatch):
    monkeypatch.setattr(addresses, "require_company_buyer", AsyncMock())
    monkeypatch.setattr(addresses.settings, "dadata_api_key", "")
    with pytest.raises(HTTPException) as error:
        await addresses.suggest_addresses(uuid.uuid4(), "Москва", CurrentUser(uuid.uuid4()), object())
    assert error.value.status_code == 503
    assert "вручную" in error.value.detail


@pytest.mark.asyncio
async def test_only_russian_suggestions_and_typed_query_are_forwarded(monkeypatch):
    monkeypatch.setattr(addresses, "require_company_buyer", AsyncMock())
    monkeypatch.setattr(addresses.settings, "dadata_api_key", "synthetic-provider-key")
    async def handle(request):
        import json
        data = json.loads(request.content)
        assert set(data) == {"query", "count", "locations", "restrict_value"}
        assert data["query"] == "Москва Лесная 1"
        assert data["locations"] == [{"country_iso_code": "RU"}]
        return httpx.Response(200, json={"suggestions": [
            {"value": "г Москва, ул Лесная, д 1", "data": {"country_iso_code": "RU", "city": "Москва", "region_with_type": "г Москва", "house": "1"}},
            {"value": "Иностранный адрес", "data": {"country_iso_code": "XX"}},
        ]})
    quota = AsyncMock()
    monkeypatch.setattr(addresses, "reserve_address_request", quota)
    original = httpx.AsyncClient
    monkeypatch.setattr(addresses.httpx, "AsyncClient", lambda **kwargs: original(transport=httpx.MockTransport(handle), **kwargs))
    company_id, db = uuid.uuid4(), object()
    items = await addresses.suggest_addresses(company_id, "Москва Лесная 1", CurrentUser(uuid.uuid4()), db)
    quota.assert_awaited_once_with(db, company_id)
    assert len(items) == 1
    assert items[0]["city"] == "Москва"
    assert items[0]["house"] == "1"


def test_chat_accepts_short_messages_but_rejects_empty_text():
    from app.schemas import SupportTicketIn
    from pydantic import ValidationError
    assert SupportTicketIn(subject="Чат с поддержкой", message=" Спасибо ").message == "Спасибо"
    with pytest.raises(ValidationError):
        SupportTicketIn(subject="Чат с поддержкой", message="   ")
