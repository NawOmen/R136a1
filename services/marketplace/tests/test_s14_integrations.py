"""S14: предметные интеграции — решения и честные границы.

S14.01 — ERP live sync не применим; файловый обмен несёт метку источника.
S14.02 — провайдер не подключён: честный 409 без записей и ложного успеха.
"""
import uuid

import pytest
from sqlalchemy import func, select

from app.models import CatalogImport, Product
from conftest import make_company, make_token, make_user

CSV = 'Название;Категория;Цена;Минимум;Срок;Остаток;Характеристика: unit\nСтол офисный;Товары для бизнеса;7900;5;10;40;шт\n'.encode()


@pytest.mark.asyncio
async def test_import_carries_source_system_label(client, db_session):
    user = await make_user(db_session)
    company = await make_company(db_session, user, can_buy=False, can_sell=True)
    headers = {"Authorization": f"Bearer {make_token(user)}"}
    path = f"/api/v1/companies/{company}/catalog-import"
    files = {"file": ("catalog.csv", CSV, "text/csv")}
    preview = await client.post(path, files=files, headers=headers, data={"source_system": "1C:ERP"})
    assert preview.status_code == 200, preview.text
    assert preview.json()["source_system"] == "1C:ERP"
    consent = {"commit": "true", "human_approved": "true", "request_key": str(uuid.uuid4()),
               "expected_hash": preview.json()["content_hash"], "source_system": "1C:ERP"}
    result = await client.post(path, files=files, headers=headers, data=consent)
    assert result.status_code == 200, result.text
    assert result.json()["source_system"] == "1C:ERP"
    assert await db_session.scalar(select(func.count()).select_from(Product)) == 1


@pytest.mark.asyncio
async def test_providers_report_not_connected(client, db_session):
    user = await make_user(db_session)
    await make_company(db_session, user, can_buy=False, can_sell=True)
    headers = {"Authorization": f"Bearer {make_token(user)}"}
    listed = await client.get("/api/v1/integrations/providers", headers=headers)
    assert listed.status_code == 200, listed.text
    assert {item["slug"] for item in listed.json()} == {"edo", "registry", "logistics"}
    assert all(item["status"] == "not_connected" for item in listed.json())
    before = await db_session.scalar(select(func.count()).select_from(CatalogImport))
    for slug in ("edo", "registry", "logistics"):
        response = await client.post(f"/api/v1/integrations/providers/{slug}/events", headers=headers,
                                     json={"idempotency_key": str(uuid.uuid4()),
                                           "event_type": "document_signed", "payload": {}})
        assert response.status_code == 409, response.text
        assert response.json()["status"] == "not_connected"
    assert await db_session.scalar(select(func.count()).select_from(CatalogImport)) == before
    unknown = await client.post("/api/v1/integrations/providers/sms-spam/events", headers=headers,
                                json={"idempotency_key": str(uuid.uuid4()), "event_type": "x"})
    assert unknown.status_code == 422
    anonymous = await client.post("/api/v1/integrations/providers/edo/events",
                                  json={"idempotency_key": str(uuid.uuid4()), "event_type": "x"})
    assert anonymous.status_code in (401, 403)
