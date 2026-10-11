"""S14: предметные интеграции — решения и честные границы.

S14.01 — ERP live sync не применим; файловый обмен несёт метку источника.
S14.02 — провайдер не подключён: честный 409 без записей и ложного успеха.
"""
import uuid

import pytest
from sqlalchemy import func, select

from app.models import CatalogImport, HumanApprovalRecord, Product, TrustAuditEvent
from conftest import make_company, make_token, make_user

CSV = 'Название;Категория;Цена;Минимум;Срок;Остаток;Характеристика: unit\nСтол офисный;Товары для бизнеса;7900;5;10;40;шт\n'.encode()


@pytest.mark.asyncio
@pytest.mark.parametrize("api_version", ["v1", "v3"])
async def test_import_source_survives_idempotent_repeat(client, db_session, api_version):
    user = await make_user(db_session)
    company = await make_company(db_session, user, can_buy=False, can_sell=True)
    headers = {"Authorization": f"Bearer {make_token(user)}"}
    path = f"/api/{api_version}/companies/{company}/catalog-import"
    files = {"file": ("catalog.csv", CSV, "text/csv")}
    key = str(uuid.uuid4())
    preview = await client.post(path, files=files, headers=headers, data={"source_system": " 1C:ERP "})
    assert preview.status_code == 200, preview.text
    assert preview.json()["source_system"] == "1C:ERP"
    consent = {"commit": "true", "human_approved": "true", "request_key": key,
               "expected_hash": preview.json()["content_hash"], "source_system": "1C:ERP"}
    first = await client.post(path, files=files, headers=headers, data=consent)
    assert first.status_code == 200, first.text
    assert first.json()["source_system"] == "1C:ERP"
    stored = await db_session.scalar(select(CatalogImport).where(CatalogImport.company_id == company))
    assert stored.source_system == "1C:ERP"
    repeat = await client.post(path, files=files, headers=headers,
                               data={**consent, "source_system": " 1C:ERP "})
    assert repeat.status_code == 200, repeat.text
    assert repeat.json()["import_id"] == first.json()["import_id"]
    assert repeat.json()["source_system"] == "1C:ERP"
    changed = await client.post(path, files=files, headers=headers,
                                data={**consent, "source_system": "OtherERP"})
    assert changed.status_code == 409
    missing = await client.post(path, files=files, headers=headers,
                                data={k: value for k, value in consent.items() if k != "source_system"})
    assert missing.status_code == 409
    assert await db_session.scalar(select(func.count()).select_from(CatalogImport).where(
        CatalogImport.company_id == company)) == 1
    assert await db_session.scalar(select(func.count()).select_from(Product).where(
        Product.company_id == company)) == 1
    audits = (await db_session.scalars(select(HumanApprovalRecord).where(
        HumanApprovalRecord.action == "catalog_import",
        HumanApprovalRecord.actor_company_id == company))).all()
    assert len(audits) == 1
    events = (await db_session.scalars(select(TrustAuditEvent).where(
        TrustAuditEvent.actor_company_id == company,
        TrustAuditEvent.event_type == "human_approval_recorded"))).all()
    assert len(events) == 1
    assert events[0].payload["approval_id"] == str(audits[0].id)
    assert events[0].payload["decision_payload"]["source_system"] == stored.source_system
    assert events[0].payload["decision_payload"]["content_hash"] == stored.content_hash


@pytest.mark.asyncio
async def test_unlabelled_import_stays_unknown_on_repeat(client, db_session):
    user = await make_user(db_session)
    company = await make_company(db_session, user, can_buy=False, can_sell=True)
    headers = {"Authorization": f"Bearer {make_token(user)}"}
    path = f"/api/v3/companies/{company}/catalog-import"
    files = {"file": ("catalog.csv", CSV, "text/csv")}
    preview = await client.post(path, files=files, headers=headers)
    assert preview.status_code == 200, preview.text
    assert preview.json()["source_system"] is None
    consent = {"commit": "true", "human_approved": "true", "request_key": str(uuid.uuid4()),
               "expected_hash": preview.json()["content_hash"]}
    first = await client.post(path, files=files, headers=headers, data=consent)
    assert first.status_code == 200, first.text
    repeat = await client.post(path, files=files, headers=headers,
                               data={**consent, "source_system": " "})
    assert repeat.status_code == 200, repeat.text
    assert repeat.json()["import_id"] == first.json()["import_id"]
    assert repeat.json()["source_system"] is None
    changed = await client.post(path, files=files, headers=headers,
                                data={**consent, "source_system": "1C:ERP"})
    assert changed.status_code == 409
    stored = await db_session.get(CatalogImport, uuid.UUID(first.json()["import_id"]))
    assert stored.source_system is None


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
