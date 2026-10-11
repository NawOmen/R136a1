"""S13.02/S13.03/S13.04: документы, scrub секретов, сигнатуры файлов."""

import uuid
from datetime import date, timedelta

import pytest
from sqlalchemy import text

from app.file_safety import check_upload
from test_category_admission import _auth, _seller_with_product, _upload_document
from conftest import grant_packaging_documents, make_company, make_marketplace_admin, make_token, make_user

CONFIRMS = {"material": ["крафт-картон"], "coating": ["PE"]}
from synthetic_files import PNG, JPEG, WEBP, PDF


@pytest.mark.parametrize("data,content_type", [
    (PNG, "image/png"), (JPEG, "image/jpeg"), (WEBP, "image/webp"),
    (PDF, "application/pdf"), ("текст".encode("utf-8"), "text/plain"),
])
def test_file_safety_accepts_matching_format(data, content_type):
    assert check_upload(data, content_type) == content_type.split(";")[0]


@pytest.mark.parametrize("data,content_type", [
    (b"MZ\x90\x00evil", "image/png"),
    (b"<svg xmlns='http://www.w3.org/2000/svg'></svg>", "image/png"),
    (b"just text", "image/jpeg"),
    (b"just text", "application/pdf"),
    (b"\xff\xfe binary", "text/plain"),
    (b"", "image/png"),
    (b"RIFF\x00\x00\x00\x00NOTWEBP", "image/webp"),
])
def test_file_safety_rejects_mismatch(data, content_type):
    with pytest.raises(ValueError):
        check_upload(data, content_type)


async def _editor(db_session):
    editor = await make_user(db_session)
    await db_session.execute(text("UPDATE auth.users SET is_category_editor=true WHERE id=:id"), {"id": editor})
    await db_session.commit()
    return editor


async def test_upload_rejects_forged_bytes(client, db_session):
    user, company, token, product_id = await _seller_with_product(client, db_session)
    headers = _auth(token)
    forged = await client.post(f"/api/v1/companies/{company}/documents", headers=headers,
                               data={"name": "Подделка", "document_type": "certificate"},
                               files={"file": ("evil.png", b"MZ\x90\x00evil", "image/png")})
    assert forged.status_code == 415
    assert (await client.post(f"/api/v1/products/{product_id}/images", headers=headers,
                              files={"file": ("evil.png", b"MZ\x90\x00evil", "image/png")})).status_code == 415
    assert (await client.post(f"/api/v1/companies/{company}/production-photo", headers=headers,
                              files={"file": ("evil.png", b"MZ\x90\x00evil", "image/png")})).status_code == 415


async def test_expiring_endpoint_lists_only_verified_with_horizon(client, db_session):
    user, company, token, _ = await _seller_with_product(client, db_session)
    headers = _auth(token)
    soon = await _upload_document(client, token, company, scope_category="Упаковка и тара",
                                  valid_until=str(date.today() + timedelta(days=10)))
    far = await _upload_document(client, token, company, scope_category="Упаковка и тара",
                                 valid_until=str(date.today() + timedelta(days=300)))
    editor = await _editor(db_session)
    for document_id in (soon["id"], far["id"]):
        decided = await client.post(f"/api/v1/documents/{document_id}/verification", headers=_auth(make_token(editor)),
                                    json={"decision": "verified", "scope_category": "Упаковка и тара",
                                          "scope_subcategory": "Бумажные стаканы", "note": "Проверка синтетики"})
        assert decided.status_code == 200, decided.text
    body = (await client.get(f"/api/v1/companies/{company}/documents/expiring", headers=headers)).json()
    ids = [item["id"] for item in body]
    assert soon["id"] in ids
    assert far["id"] not in ids
    stranger = await make_user(db_session)
    assert (await client.get(f"/api/v1/companies/{company}/documents/expiring",
                             headers=_auth(make_token(stranger)))).status_code == 404
    assert (await client.get(f"/api/v1/companies/{company}/documents/expiring?within_days=0",
                             headers=headers)).status_code == 422


async def test_expired_document_blocks_publish_between_view_and_action(client, db_session):
    user, company, token, product_id = await _seller_with_product(client, db_session)
    await grant_packaging_documents(db_session, company, decision_user_id=user, confirms=CONFIRMS)
    assert (await client.post(f"/api/v1/products/{product_id}/publish", json={"published": True},
                              headers=_auth(token))).status_code == 200
    await db_session.execute(text("UPDATE marketplace.documents SET valid_until = CURRENT_DATE - 1 WHERE company_id = :cid"),
                             {"cid": company})
    await db_session.commit()
    await client.post(f"/api/v1/products/{product_id}/publish", json={"published": False}, headers=_auth(token))
    blocked = await client.post(f"/api/v1/products/{product_id}/publish", json={"published": True}, headers=_auth(token))
    assert blocked.status_code == 409, blocked.text


async def test_delete_verified_document_reevaluates_and_notifies_without_unpublishing(client, db_session):
    user, company, token, product_id = await _seller_with_product(client, db_session)
    await grant_packaging_documents(db_session, company, decision_user_id=user, confirms=CONFIRMS)
    assert (await client.post(f"/api/v1/products/{product_id}/publish", json={"published": True},
                              headers=_auth(token))).status_code == 200
    document_id = (await db_session.execute(
        text("SELECT id FROM marketplace.documents WHERE company_id = :cid LIMIT 1"), {"cid": company})).scalar_one()
    assert (await client.delete(f"/api/v1/documents/{document_id}", headers=_auth(token))).status_code == 204
    notes = (await db_session.execute(
        text("SELECT message FROM marketplace.notifications WHERE user_id = :uid"), {"uid": user})).scalars().all()
    assert any("Стакан 400 мл PE" in message for message in notes)
    events = (await db_session.execute(
        text("SELECT payload FROM marketplace.trust_audit_events WHERE event_type = 'document_status_reevaluated'"))).mappings().all()
    assert events and "Стакан 400 мл PE" in events[0]["payload"]["products_without_admission"]
    own = await client.get(f"/api/v1/companies/{company}/products", headers=_auth(token))
    assert own.json()[0]["is_published"] is True


async def test_repeat_verification_does_not_spam(client, db_session):
    _, company, token, _ = await _seller_with_product(client, db_session)
    document = await _upload_document(client, token, company, scope_category="Упаковка и тара")
    editor = await _editor(db_session)
    payload = {"decision": "verified", "scope_category": "Упаковка и тара",
               "scope_subcategory": "Бумажные стаканы", "note": "Проверка синтетики"}
    first = await client.post(f"/api/v1/documents/{document['id']}/verification",
                              headers=_auth(make_token(editor)), json=payload)
    assert first.status_code == 200, first.text
    second = await client.post(f"/api/v1/documents/{document['id']}/verification",
                               headers=_auth(make_token(editor)), json=payload)
    assert second.status_code == 200
    count = (await db_session.execute(
        text("SELECT COUNT(*) FROM marketplace.trust_audit_events WHERE event_type = 'document_verification_changed' "
             "AND entity_id = :eid"), {"eid": document["id"]})).scalar_one()
    assert count == 1


async def test_audit_scrubs_secrets_and_chain_stays_valid(client, db_session):
    from app.trust import append_audit_event

    user = await make_user(db_session)
    event = await append_audit_event(
        db_session, event_type="s13_probe", entity_type="probe",
        explanation="Проверка вычищения секретов.",
        payload={"password": "hunter2", "nested": {"api_key": "AAA", "ok": 1}},
        source_refs=[{"type": "note", "token": "TTT"}])
    await db_session.commit()
    assert event.payload == {"password": "[скрыто]", "nested": {"api_key": "[скрыто]", "ok": 1}}
    assert event.source_refs == [{"type": "note", "token": "[скрыто]"}]
    admin = await make_marketplace_admin(db_session)
    admin_headers = _auth(make_token(admin))
    assert (await client.get("/api/v1/audit/verify", headers=admin_headers)).json()["valid"] is True
    await db_session.execute(
        text("UPDATE marketplace.trust_audit_events SET explanation = 'подмена' WHERE id = :eid"), {"eid": event.id})
    await db_session.commit()
    broken = await client.get("/api/v1/audit/verify", headers=admin_headers)
    assert broken.json()["valid"] is False
    assert broken.json()["broken_sequence"] == event.sequence
