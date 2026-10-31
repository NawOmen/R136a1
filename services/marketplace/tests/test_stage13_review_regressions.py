"""Regression cases from PR125 review, exercised against real transaction/file paths."""
import asyncio
from datetime import date, timedelta

import pytest
from sqlalchemy import text

from conftest import grant_packaging_documents, make_token
from test_category_admission import _auth, _seller_with_product, _upload_document
from test_stage13_documents import _editor, CONFIRMS
from synthetic_files import WAV


@pytest.mark.parametrize("data,media", [(b"<svg></svg>", "image/svg+xml"), (b"<html></html>", "text/html"),
    (b"MZbad", "audio/wav"), (b"\x89PNG\r\n\x1a\nrest", "image/png"), (b"%PDF-1.4 rest", "application/pdf")])
def test_unknown_and_header_only_files_fail_closed(data, media):
    from app.file_safety import check_upload
    with pytest.raises(ValueError):
        check_upload(data, media)


def test_actual_wav_is_readable():
    from app.file_safety import check_upload
    assert check_upload(WAV, "audio/wav") == "audio/wav"


async def test_explicit_null_and_omitted_expiry_are_different(client, db_session):
    _, company, token, _ = await _seller_with_product(client, db_session)
    expiry = str(date.today() + timedelta(days=15))
    document = await _upload_document(client, token, company, scope_category="Упаковка и тара", valid_until=expiry)
    editor = await _editor(db_session)
    body = {"decision": "verified", "scope_category": "Упаковка и тара", "note": "Синтетическая проверка"}
    for version, endpoint in (("v3", "decision"), ("v1", "verification")):
        path = f"/api/{version}/documents/{document['id']}/{endpoint}"
        response = await client.post(path, headers=_auth(make_token(editor)), json=body)
        assert response.status_code == 200, response.text
        if version == "v3":
            assert response.json()["valid_until"] == expiry
        cleared = await client.post(path, headers=_auth(make_token(editor)), json={**body, "valid_until": None})
        assert cleared.status_code == 200 and cleared.json()["valid_until"] is None


async def test_confirm_changes_reevaluate_and_queue_rematch(client, db_session):
    user, company, token, product = await _seller_with_product(client, db_session)
    await grant_packaging_documents(db_session, company, decision_user_id=user, confirms=CONFIRMS)
    assert (await client.post(f"/api/v1/products/{product}/publish", json={"published": True}, headers=_auth(token))).status_code == 200
    document_id = await db_session.scalar(text("SELECT id FROM marketplace.documents WHERE company_id=:id AND document_type='test_report' LIMIT 1"), {"id": company})
    editor = await _editor(db_session)
    response = await client.post(f"/api/v3/documents/{document_id}/decision", headers=_auth(make_token(editor)),
        json={"decision": "verified", "scope_category": "Упаковка и тара", "scope_subcategory": "Бумажные стаканы",
              "confirms": {}, "note": "Подтверждение материала снято"})
    assert response.status_code == 200, response.text
    assert await db_session.scalar(text("SELECT count(*) FROM marketplace.trust_audit_events WHERE entity_id=:id AND event_type='document_status_reevaluated'"), {"id": document_id}) == 1
    assert await db_session.scalar(text("SELECT count(*) FROM marketplace.match_events WHERE entity_id=:id AND status='pending'"), {"id": document_id}) == 1
    from app.document_lifecycle import drain_rematches
    await drain_rematches(db_session)
    await db_session.commit()
    assert await db_session.scalar(text("SELECT count(*) FROM marketplace.match_events WHERE entity_id=:id AND status='processed'"), {"id": document_id}) == 1


async def test_deleting_draft_evidence_keeps_audit(client, db_session):
    user, company, token, _ = await _seller_with_product(client, db_session)
    await grant_packaging_documents(db_session, company, decision_user_id=user, confirms=CONFIRMS)
    document = await db_session.scalar(text("SELECT id FROM marketplace.documents WHERE company_id=:id LIMIT 1"), {"id": company})
    assert (await client.delete(f"/api/v1/documents/{document}", headers=_auth(token))).status_code == 204
    event = (await db_session.execute(text("SELECT actor_user_id,payload FROM marketplace.trust_audit_events WHERE entity_id=:id AND event_type='document_deleted'"), {"id": document})).mappings().one()
    assert event["actor_user_id"] == user and event["payload"]["status"] == "verified"


async def test_expiry_is_detected_without_user_get_and_does_not_spam(client, db_session):
    from app.document_lifecycle import process_expiry
    user, company, token, _ = await _seller_with_product(client, db_session)
    await grant_packaging_documents(db_session, company, decision_user_id=user, confirms=CONFIRMS)
    document_id = await db_session.scalar(text("SELECT id FROM marketplace.documents WHERE company_id=:id LIMIT 1"), {"id": company})
    await db_session.execute(text("UPDATE marketplace.documents SET valid_until=:expires WHERE id=:id"), {"expires": date.today() + timedelta(days=2), "id": document_id})
    await db_session.commit()
    assert await process_expiry(db_session, document_id)
    await db_session.commit()
    assert not await process_expiry(db_session, document_id)
    await db_session.commit()
    assert await process_expiry(db_session, document_id, today=date.today() + timedelta(days=3))
    await db_session.commit()
    assert not await process_expiry(db_session, document_id, today=date.today() + timedelta(days=3))
    await db_session.commit()
    events = (await db_session.execute(text("SELECT event_type FROM marketplace.trust_audit_events WHERE entity_id=:id AND event_type IN ('document_expiring','document_expired')"), {"id": document_id})).scalars().all()
    assert sorted(events) == ['document_expired','document_expiring']
    notices = (await db_session.execute(text("SELECT explanation FROM marketplace.trust_audit_events WHERE entity_id=:id AND event_type IN ('document_expiring','document_expired')"), {"id":document_id})).scalars().all()
    expiry = date.today() + timedelta(days=2)
    assert all(expiry.strftime('%d.%m.%y') in notice and expiry.isoformat() not in notice for notice in notices)



async def test_parallel_verification_has_one_decision(client, db_session):
    _, company, token, _ = await _seller_with_product(client, db_session)
    doc = await _upload_document(client, token, company, scope_category="Упаковка и тара")
    editor = await _editor(db_session)
    args = {"headers": _auth(make_token(editor)), "json": {"decision": "verified", "scope_category": "Упаковка и тара", "note": "Одно решение"}}
    results = await asyncio.gather(*(client.post(f"/api/v1/documents/{doc['id']}/verification", **args) for _ in range(2)))
    assert all(r.status_code == 200 for r in results)
    assert await db_session.scalar(text("SELECT count(*) FROM marketplace.trust_audit_events WHERE entity_id=:id AND event_type='document_verification_changed'"), {"id": doc['id']}) == 1


async def test_publication_waits_for_document_writer(client, db_session, session_factory):
    from app.resources import lock_company
    user, company, token, product = await _seller_with_product(client, db_session)
    await grant_packaging_documents(db_session, company, decision_user_id=user, confirms=CONFIRMS)
    async with session_factory() as writer:
        await lock_company(writer, company)
        task = asyncio.create_task(client.post(f"/api/v1/products/{product}/publish", headers=_auth(token), json={"published": True}))
        await asyncio.sleep(0.05)
        assert not task.done()
        await writer.execute(text("UPDATE marketplace.documents SET verification_status='rejected' WHERE company_id=:id"), {"id": company})
        await writer.commit()
        response = await task
    assert response.status_code == 409, response.text
    assert not await db_session.scalar(text("SELECT is_published FROM marketplace.products WHERE id=:id"), {"id": product})


async def test_audit_and_approval_redact_labelled_text_and_nested_keys(db_session):
    from app.trust import append_audit_event, record_human_approval, verify_event, GENESIS_HASH
    from conftest import make_user
    marker = "synthetic-sensitive-marker"
    event = await append_audit_event(db_session, event_type="redaction_probe", entity_type="probe",
        explanation=f"access_token={marker}", payload={"refresh_token": marker, "nested": [f"Bearer {marker}"]})
    assert marker not in str(event.payload) + event.explanation
    assert verify_event(GENESIS_HASH, event)
    user = await make_user(db_session)
    approval = await record_human_approval(db_session, action="probe", entity_type="probe", actor_user_id=user,
        permission="test", decision="approved", payload={}, explanation="Синтетическое решение", reason=f"api_key: {marker}")
    assert marker not in approval.reason
    await db_session.commit()


async def test_direct_match_excludes_revoked_admission(client,db_session):
    from app.models import Need,Offer,DeliveryAddress
    from app.matching import _has_direct_match
    from conftest import make_company, make_user
    user,company,token,product=await _seller_with_product(client,db_session)
    await grant_packaging_documents(db_session,company,decision_user_id=user,confirms=CONFIRMS)
    await db_session.execute(text("UPDATE marketplace.documents SET verification_status='rejected' WHERE company_id=:cid"),{'cid':company})
    buyer=await make_user(db_session);bc=await make_company(db_session,buyer,can_sell=False)
    address=DeliveryAddress(company_id=bc,address='г. Москва, ул. Синтетическая, д.1',city='Москва',region='Москва');db_session.add(address);await db_session.flush()
    need=Need(company_id=bc,created_by_user_id=buyer,category='Упаковка и тара',subcategory='Бумажные стаканы',characteristics={'volume_ml':400,'material':'крафт-картон','coating':'PE'},volume_units=20000,budget_rub=300000,deadline_date=date.today()+timedelta(days=20),delivery_address_id=address.id,visibility='closed',status='open_for_offers')
    db_session.add(need);await db_session.flush()
    offer=Offer(need_id=need.id,company_id=company,created_by_user_id=user,price_rub=10,available_units=20000,moq_units=20000,lead_time_days=2,delivery_cost_rub=0,price_tiers=[],status='sent',commercial_quote={'need':{'revision':need.revision},'estimate':{'complete':True,'total_rub':'200000'}})
    db_session.add(offer);await db_session.commit()
    match,reason=await _has_direct_match(db_session,need)
    assert not match
    assert "Допуск продавца не подтверждён" in reason
    assert "MOQ, бюджет или срок" not in reason



async def test_group_and_approved_reserve_parties_receive_document_alert(db_session):
    from app.api.documents import _notify_affected_deals
    from app.models import ParticipantOrder, GroupOffer
    from sqlalchemy import select
    from test_stage13_access_matrix import _world
    w = await _world(db_session)
    # Remove the direct deal so the alert is proved for independent grouped/reserve obligations.
    await db_session.execute(text('DELETE FROM marketplace.deals WHERE id=:id'), {'id': w['deal'].id})
    await db_session.execute(text("UPDATE marketplace.reserve_commitments SET confirmation_status='approved' WHERE id=:id"), {'id': w['commitment'].id})
    group_offer = await db_session.scalar(select(GroupOffer).where(GroupOffer.coalition_id == w['coalition'].id))
    db_session.add(ParticipantOrder(coalition_id=w['coalition'].id, group_offer_id=group_offer.id,
        need_id=w['need'].id, buyer_company_id=w['bc'], seller_company_id=w['sc'], units=10,
        total_price_rub=1000, status='created'))
    await db_session.flush()
    assert await _notify_affected_deals(db_session, w['sc'], 'Синтетический документ', 'Мебель', None) == 2
    await db_session.commit()
    notes = (await db_session.execute(text('SELECT message FROM marketplace.notifications WHERE user_id=:id'), {'id': w['buyer']})).scalars().all()
    assert any('Синтетический документ' in note for note in notes)


async def test_outbox_rematch_failure_is_durable_and_can_be_retried(client, db_session, monkeypatch):
    from app.document_lifecycle import drain_rematches
    from app.models import MatchEvent
    from app import matching
    import uuid
    event = MatchEvent(event_type='document_admission_changed', entity_id=uuid.uuid4(), payload={}, status='pending')
    db_session.add(event)
    await db_session.commit()
    event_id = event.id
    async def unavailable(*args, **kwargs):
        raise RuntimeError('synthetic rematch unavailable')
    with monkeypatch.context() as temporary:
        temporary.setattr(matching, 'run_market_rematch', unavailable)
        with pytest.raises(RuntimeError):
            await drain_rematches(db_session)
        await db_session.rollback()
    assert await db_session.scalar(text('SELECT status FROM marketplace.match_events WHERE id=:id'), {'id': event_id}) == 'pending'
    assert await drain_rematches(db_session) == 1
    await db_session.commit()
    assert await db_session.scalar(text('SELECT status FROM marketplace.match_events WHERE id=:id'), {'id': event_id}) == 'processed'


async def test_upload_cancellation_kills_native_validator(tmp_path, monkeypatch):
    import os
    from app import file_safety
    from synthetic_files import PNG
    marker = tmp_path / 'pid'
    (tmp_path / 'file_safety_worker.py').write_text(f"import os,time\nopen({str(marker)!r},'w').write(str(os.getpid()))\ntime.sleep(120)\n")
    monkeypatch.setattr(file_safety, '__file__', str(tmp_path / 'file_safety.py'))
    task = asyncio.create_task(file_safety.validate_upload(PNG, 'image/png'))
    for _ in range(100):
        if marker.exists():
            break
        await asyncio.sleep(0.01)
    assert marker.exists()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    with pytest.raises(ProcessLookupError):
        os.kill(int(marker.read_text()), 0)
    assert not file_safety._slots.locked()
