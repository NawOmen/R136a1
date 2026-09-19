"""Категорийный допуск: доказательства, применимость и блокировка публикации.

Проверяем, что допуск выдаётся только по документам, которые человек подтвердил
для нужной области действия, и что загрузка файла сама по себе допуск не даёт.
"""

from datetime import datetime, timedelta, timezone

from sqlalchemy import select, text

from conftest import (
    grant_packaging_documents,
    make_company,
    make_marketplace_admin,
    make_token,
    make_user,
)


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


async def _seller_with_product(client, db_session, *, category="Упаковка и тара", subcategory="Бумажные стаканы"):
    user = await make_user(db_session)
    company = await make_company(db_session, user, can_buy=False, can_sell=True)
    token = make_token(user)
    created = await client.post(
        f"/api/v1/companies/{company}/products",
        json={
            "name": "Стакан 400 мл PE",
            "category": category,
            "subcategory": subcategory,
            "characteristics": {"volume_ml": 400, "material": "крафт-картон", "coating": "PE"},
            "price_rub": 11.2,
            "moq_units": 20000,
            "lead_time_days": 9,
        },
        headers=_auth(token),
    )
    assert created.status_code == 201, created.text
    return user, company, token, created.json()["id"]


async def _upload_document(client, token, company, *, document_type="declaration", scope_category=None, scope_subcategory=None, valid_until=None):
    data = {"name": f"Документ {document_type}", "document_type": document_type}
    if scope_category is not None:
        data["scope_category"] = scope_category
    if scope_subcategory is not None:
        data["scope_subcategory"] = scope_subcategory
    if valid_until is not None:
        data["valid_until"] = valid_until
    response = await client.post(
        f"/api/v1/companies/{company}/documents",
        data=data,
        files={"file": ("doc.pdf", b"%PDF-1.4 synthetic", "application/pdf")},
        headers=_auth(token),
    )
    assert response.status_code == 201, response.text
    return response.json()


async def test_publication_blocked_without_documents(client, db_session):
    _, _, token, product_id = await _seller_with_product(client, db_session)

    report = await client.get(
        "/api/v1/category-requirements",
        params={"category": "Упаковка и тара", "subcategory": "Бумажные стаканы"},
    )
    assert report.status_code == 200
    assert report.json()["supported"] is True
    assert len(report.json()["checklist"]) == 2
    assert all(item["state"] == "required" for item in report.json()["checklist"])

    publish = await client.post(
        f"/api/v1/products/{product_id}/publish", json={"published": True}, headers=_auth(token)
    )
    assert publish.status_code == 409
    assert "Публикация заблокирована" in publish.json()["detail"]
    assert "не предоставлено" in publish.json()["detail"]


async def test_uploaded_document_does_not_grant_admission(client, db_session):
    _, company, token, product_id = await _seller_with_product(client, db_session)
    await _upload_document(
        client, token, company, scope_category="Упаковка и тара", scope_subcategory="Бумажные стаканы"
    )

    admission = await client.get(
        f"/api/v1/companies/{company}/category-admission",
        params={"category": "Упаковка и тара", "subcategory": "Бумажные стаканы"},
        headers=_auth(token),
    )
    assert admission.status_code == 200
    body = admission.json()
    assert body["state"] == "blocked"
    declaration = next(item for item in body["requirements"] if item["code"] == "packaging_conformity")
    assert declaration["state"] == "uploaded_unverified"
    assert declaration["state_label"] == "Загружено, не проверено"

    publish = await client.post(
        f"/api/v1/products/{product_id}/publish", json={"published": True}, headers=_auth(token)
    )
    assert publish.status_code == 409


async def test_seller_cannot_verify_own_document(client, db_session):
    _, company, token, _ = await _seller_with_product(client, db_session)
    document = await _upload_document(client, token, company, scope_category="Упаковка и тара")

    response = await client.post(
        f"/api/v1/documents/{document['id']}/verification",
        json={"decision": "verified", "scope_category": "Упаковка и тара"},
        headers=_auth(token),
    )
    assert response.status_code == 403
    assert "администратора площадки" in response.json()["detail"]


async def test_admission_after_verifier_confirms_both_documents(client, db_session):
    _, company, token, product_id = await _seller_with_product(client, db_session)
    admin = await make_marketplace_admin(db_session)
    admin_token = make_token(admin)

    for document_type in ("declaration", "test_report"):
        document = await _upload_document(client, token, company, document_type=document_type)
        verified = await client.post(
            f"/api/v1/documents/{document['id']}/verification",
            json={
                "decision": "verified",
                "scope_category": "Упаковка и тара",
                "scope_subcategory": "Бумажные стаканы",
                "valid_until": (datetime.now(timezone.utc).date() + timedelta(days=365)).isoformat(),
                "confirms": {"material": ["крафт-картон"], "coating": ["PE"]},
                "note": "Применимость подтверждена для стаканов 150–600 мл.",
            },
            headers=_auth(admin_token),
        )
        assert verified.status_code == 200, verified.text
        assert verified.json()["verification_status"] == "verified"
        assert verified.json()["verified_by_user_id"] == str(admin)

    admission = await client.get(
        f"/api/v1/companies/{company}/category-admission",
        params={"category": "Упаковка и тара", "subcategory": "Бумажные стаканы"},
        headers=_auth(token),
    )
    assert admission.json()["state"] == "admitted"
    assert admission.json()["blocking_open"] == 0

    publish = await client.post(
        f"/api/v1/products/{product_id}/publish", json={"published": True}, headers=_auth(token)
    )
    assert publish.status_code == 200

    checklist = await client.get(f"/api/v1/products/{product_id}/admission")
    assert checklist.status_code == 200
    body = checklist.json()
    assert body["state"] == "admitted"
    assert all(item["state"] == "satisfied" for item in body["checklist"])
    # Покупатель не получает имён файлов и внутренних ссылок на документы
    assert all(item["document_ids"] == [] for item in body["checklist"])


async def test_document_of_other_category_is_not_evidence(client, db_session):
    _, company, token, product_id = await _seller_with_product(client, db_session)
    admin_token = make_token(await make_marketplace_admin(db_session))

    for document_type in ("declaration", "test_report"):
        document = await _upload_document(client, token, company, document_type=document_type)
        verified = await client.post(
            f"/api/v1/documents/{document['id']}/verification",
            json={"decision": "verified", "scope_category": "Продукты питания", "note": "Проверено."},
            headers=_auth(admin_token),
        )
        assert verified.status_code == 200

    admission = await client.get(
        f"/api/v1/companies/{company}/category-admission",
        params={"category": "Упаковка и тара", "subcategory": "Бумажные стаканы"},
        headers=_auth(token),
    )
    body = admission.json()
    assert body["state"] == "blocked"
    assert all(item["state"] == "scope_mismatch" for item in body["requirements"])

    publish = await client.post(
        f"/api/v1/products/{product_id}/publish", json={"published": True}, headers=_auth(token)
    )
    assert publish.status_code == 409


async def test_document_without_scope_requires_applicability_check(client, db_session):
    _, company, token, _ = await _seller_with_product(client, db_session)
    admin_token = make_token(await make_marketplace_admin(db_session))

    document = await _upload_document(client, token, company)
    # Без области действия подтверждение запрещено: применимость не доказана.
    rejected = await client.post(
        f"/api/v1/documents/{document['id']}/verification",
        json={"decision": "verified"},
        headers=_auth(admin_token),
    )
    assert rejected.status_code == 422

    admission = await client.get(
        f"/api/v1/companies/{company}/category-admission",
        params={"category": "Упаковка и тара", "subcategory": "Бумажные стаканы"},
        headers=_auth(token),
    )
    state = next(item for item in admission.json()["requirements"] if item["code"] == "packaging_conformity")
    assert state["state"] == "needs_scope"
    assert state["state_label"] == "Нужна проверка применимости"


async def test_expired_and_rejected_documents_do_not_grant_admission(client, db_session):
    _, company, token, _ = await _seller_with_product(client, db_session)
    admin_token = make_token(await make_marketplace_admin(db_session))
    yesterday = (datetime.now(timezone.utc).date() - timedelta(days=1)).isoformat()

    declaration = await _upload_document(client, token, company, document_type="declaration")
    expired = await client.post(
        f"/api/v1/documents/{declaration['id']}/verification",
        json={
            "decision": "verified",
            "scope_category": "Упаковка и тара",
            "scope_subcategory": "Бумажные стаканы",
            "valid_until": yesterday,
            "note": "Срок действия истёк.",
        },
        headers=_auth(admin_token),
    )
    assert expired.status_code == 200

    report = await _upload_document(client, token, company, document_type="test_report")
    rejected = await client.post(
        f"/api/v1/documents/{report['id']}/verification",
        json={
            "decision": "rejected",
            "scope_category": "Упаковка и тара",
            "note": "Материал не подтверждён.",
        },
        headers=_auth(admin_token),
    )
    assert rejected.status_code == 200
    assert rejected.json()["verification_status"] == "rejected"

    admission = await client.get(
        f"/api/v1/companies/{company}/category-admission",
        params={"category": "Упаковка и тара", "subcategory": "Бумажные стаканы"},
        headers=_auth(token),
    )
    states = {item["code"]: item["state"] for item in admission.json()["requirements"]}
    assert states["packaging_conformity"] == "expired"
    assert states["food_contact"] == "rejected"
    assert admission.json()["state"] == "blocked"


async def test_rejection_requires_reason_and_writes_audit(client, db_session):
    _, company, token, _ = await _seller_with_product(client, db_session)
    admin_token = make_token(await make_marketplace_admin(db_session))
    document = await _upload_document(client, token, company, scope_category="Упаковка и тара")

    without_reason = await client.post(
        f"/api/v1/documents/{document['id']}/verification",
        json={"decision": "rejected"},
        headers=_auth(admin_token),
    )
    assert without_reason.status_code == 422

    rejected = await client.post(
        f"/api/v1/documents/{document['id']}/verification",
        json={"decision": "rejected", "scope_category": "Упаковка и тара", "note": "Документ нечитаемый."},
        headers=_auth(admin_token),
    )
    assert rejected.status_code == 200

    events = (
        await db_session.execute(
            text(
                "SELECT event_type FROM marketplace.trust_audit_events "
                "WHERE event_type IN ('document_uploaded', 'document_verification_changed') "
                "ORDER BY sequence"
            )
        )
    ).scalars().all()
    assert "document_uploaded" in events
    assert "document_verification_changed" in events
    approvals = (
        await db_session.execute(text("SELECT decision FROM marketplace.human_approval_records"))
    ).scalars().all()
    assert "rejected" in approvals
    # Компания получает уведомление: доказательство перестало подтверждать допуск.
    notifications = (
        await db_session.execute(
            text("SELECT message FROM marketplace.notifications WHERE type = 'document_verification_changed'")
        )
    ).scalars().all()
    assert notifications
    assert "не подтверждает допуск" in notifications[0]


async def test_deleting_verified_document_notifies_company(client, db_session):
    user, company, token, _ = await _seller_with_product(client, db_session)
    document = await _upload_document(client, token, company, scope_category="Упаковка и тара")
    admin_token = make_token(await make_marketplace_admin(db_session))
    verified = await client.post(
        f"/api/v1/documents/{document['id']}/verification",
        json={
            "decision": "verified",
            "scope_category": "Упаковка и тара",
            "scope_subcategory": "Бумажные стаканы",
            "note": "Проверено.",
        },
        headers=_auth(admin_token),
    )
    assert verified.status_code == 200

    removed = await client.delete(f"/api/v1/documents/{document['id']}", headers=_auth(token))
    assert removed.status_code == 204
    notifications = (
        await db_session.execute(
            text("SELECT message FROM marketplace.notifications WHERE user_id = :uid"), {"uid": user}
        )
    ).scalars().all()
    assert any("удалён" in message for message in notifications)


async def test_pending_documents_queue_requires_marketplace_admin(client, db_session):
    _, company, token, _ = await _seller_with_product(client, db_session)
    await _upload_document(client, token, company, scope_category="Упаковка и тара")

    forbidden = await client.get("/api/v1/admin/documents/pending", headers=_auth(token))
    assert forbidden.status_code == 403

    admin_token = make_token(await make_marketplace_admin(db_session))
    queue = await client.get("/api/v1/admin/documents/pending", headers=_auth(admin_token))
    assert queue.status_code == 200
    assert len(queue.json()) == 1
    assert queue.json()[0]["company_id"] == str(company)
    assert queue.json()[0]["company_display_name"]


async def test_unsupported_category_is_not_published(client, db_session):
    _, _, token, product_id = await _seller_with_product(
        client, db_session, category="Медицина и гигиена", subcategory="Расходные материалы"
    )
    requirements = await client.get(
        "/api/v1/category-requirements",
        params={"category": "Медицина и гигиена", "subcategory": "Расходные материалы"},
    )
    assert requirements.status_code == 200
    assert requirements.json()["supported"] is False

    publish = await client.post(
        f"/api/v1/products/{product_id}/publish", json={"published": True}, headers=_auth(token)
    )
    assert publish.status_code == 409
    assert "не поддерживается" in publish.json()["detail"] or "заблокирована" in publish.json()["detail"]


async def test_published_product_cannot_change_category_without_evidence(client, db_session):
    user, company, token, product_id = await _seller_with_product(client, db_session)
    await grant_packaging_documents(
        db_session, company, decision_user_id=user, confirms={"material": ["крафт-картон"], "coating": ["PE"]}
    )

    publish = await client.post(
        f"/api/v1/products/{product_id}/publish", json={"published": True}, headers=_auth(token)
    )
    assert publish.status_code == 200

    changed = await client.patch(
        f"/api/v1/products/{product_id}",
        json={"category": "Продукты питания", "subcategory": "Напитки"},
        headers=_auth(token),
    )
    assert changed.status_code == 409
    assert "Изменение отклонено" in changed.json()["detail"]


async def test_category_without_configured_rules_stays_publishable(client, db_session):
    _, _, token, product_id = await _seller_with_product(
        client, db_session, category="Полиграфия и реклама", subcategory="Этикетки"
    )
    admission = await client.get(
        "/api/v1/category-requirements",
        params={"category": "Полиграфия и реклама", "subcategory": "Этикетки"},
    )
    assert admission.json()["profile_title"] is None

    publish = await client.post(
        f"/api/v1/products/{product_id}/publish", json={"published": True}, headers=_auth(token)
    )
    assert publish.status_code == 200


async def test_admission_report_keeps_history_of_publication(client, db_session):
    user, company, token, product_id = await _seller_with_product(client, db_session)
    await grant_packaging_documents(
        db_session, company, decision_user_id=user, confirms={"material": ["крафт-картон"], "coating": ["PE"]}
    )
    publish = await client.post(
        f"/api/v1/products/{product_id}/publish", json={"published": True}, headers=_auth(token)
    )
    assert publish.status_code == 200

    from app.models import TrustAuditEvent

    events = (
        await db_session.execute(
            select(TrustAuditEvent)
            .where(TrustAuditEvent.event_type == "product_published_with_admission")
            .order_by(TrustAuditEvent.sequence)
        )
    ).scalars().all()
    assert events
    assert events[0].payload["admission"]["state"] == "admitted"
    assert events[0].payload["admission"]["blocking_open"] == 0
    assert events[0].event_hash
