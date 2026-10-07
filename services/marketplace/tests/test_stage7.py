from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError

from app.models import Document, HumanApprovalRecord, SupportTicket, TrustAuditEvent
from app.trust import GENESIS_HASH, append_audit_event, verify_event
from conftest import make_company, make_token, make_user


async def test_support_ticket_is_private_and_audited(client, db_session):
    owner = await make_user(db_session)
    company = await make_company(db_session, owner)
    stranger = await make_user(db_session)

    response = await client.post(
        "/api/v1/support/tickets",
        headers={"Authorization": f"Bearer {make_token(owner)}"},
        json={"company_id": str(company), "subject": "Ошибка карточки", "message": "Не получается обновить карточку товара."},
    )
    assert response.status_code == 201
    assert response.json()["status"] == "new"

    mine = await client.get(
        "/api/v1/support/tickets/mine",
        headers={"Authorization": f"Bearer {make_token(stranger)}"},
    )
    assert mine.status_code == 200
    assert mine.json() == []
    assert (await db_session.execute(select(SupportTicket))).scalars().one()
    event = (await db_session.execute(select(TrustAuditEvent))).scalars().one()
    assert event.source_refs[0]["type"] == "user_message"
    assert verify_event(GENESIS_HASH, event)


async def test_admin_can_process_support_and_chain_detects_tampering(client, db_session):
    user = await make_user(db_session)
    await db_session.execute(text("UPDATE auth.users SET is_marketplace_admin = true WHERE id = :id"), {"id": user})
    await db_session.commit()
    token = make_token(user)
    created = await client.post(
        "/api/v1/support/tickets",
        headers={"Authorization": f"Bearer {token}"},
        json={"subject": "Нужна помощь", "message": "Проверьте синтетическую заявку компании."},
    )
    ticket_id = created.json()["id"]
    updated = await client.patch(
        f"/api/v1/admin/support/tickets/{ticket_id}",
        headers={"Authorization": f"Bearer {token}"},
        json={"status": "resolved", "admin_response": "Проверено в прототипе."},
    )
    assert updated.status_code == 200
    assert updated.json()["status"] == "resolved"
    valid = await client.get("/api/v1/audit/verify", headers={"Authorization": f"Bearer {token}"})
    assert valid.json() == {"valid": True, "checked_events": 2, "broken_sequence": None}

    first = (await db_session.execute(select(TrustAuditEvent).order_by(TrustAuditEvent.sequence))).scalars().first()
    first.explanation = "Подменено"
    await db_session.commit()
    broken = await client.get("/api/v1/audit/verify", headers={"Authorization": f"Bearer {token}"})
    assert broken.json()["valid"] is False


async def test_non_admin_cannot_process_support(client, db_session):
    user = await make_user(db_session)
    response = await client.get(
        "/api/v1/admin/support/tickets",
        headers={"Authorization": f"Bearer {make_token(user)}"},
    )
    assert response.status_code == 403


async def test_company_audit_hides_cross_company_payload(client, db_session):
    owner = await make_user(db_session)
    company = await make_company(db_session, owner)
    outsider = await make_user(db_session)
    await append_audit_event(db_session, event_type="coalition_obligations_checked",
        entity_type="coalition", entity_id=__import__("uuid").uuid4(),
        actor_user_id=owner, actor_company_id=company,
        source_refs=[{"type": "other_need", "id": "private-reference"}],
        explanation="Условия проверены.", payload={"other_member": "private-reference"})
    await db_session.commit()
    path = f"/api/v1/audit/events?company_id={company}"
    allowed = await client.get(path, headers={"Authorization": f"Bearer {make_token(owner)}"})
    assert allowed.status_code == 200
    assert allowed.json()[0]["explanation"] == "Условия проверены."
    assert allowed.json()[0]["payload"] == {}
    assert allowed.json()[0]["source_refs"] == []
    denied = await client.get(path, headers={"Authorization": f"Bearer {make_token(outsider)}"})
    assert denied.status_code in {403, 404}


async def test_uploaded_document_never_becomes_verified_from_its_own_claims(db_session):
    fake = Document(
        company_id=__import__("uuid").uuid4(), name="Поддельный сертификат",
        document_type="certificate", file_key="synthetic/fake.pdf", content_type="application/pdf",
    )
    db_session.add(fake)
    await db_session.flush()
    assert fake.verification_status == "unverified"


async def test_human_approval_model_rejects_invalid_decision_at_database(db_session):
    # Ограничение БД дублирует прикладную проверку и не даёт записать неявное решение.
    user = await make_user(db_session)
    db_session.add(HumanApprovalRecord(
        action="test", entity_type="test", actor_user_id=user,
        permission="company_admin", decision="maybe", payload_hash="0" * 64,
    ))
    try:
        await db_session.commit()
        assert False, "Ожидалось ограничение решения"
    except IntegrityError:
        await db_session.rollback()
