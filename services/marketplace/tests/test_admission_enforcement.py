"""Проверки допуска на всех путях принятия обязательств.

Отдельно фиксируем то, что раньше было дефектом: применимость документа
сравнивается структурно, ограниченные категории требуют классификации,
а обязательства невозможны без подтверждённых доказательств.
"""

from datetime import date, timedelta

from sqlalchemy import text

from conftest import grant_packaging_documents, make_company, make_token, make_marketplace_admin, make_user

from test_category_admission import _auth, _seller_with_product, _upload_document

CONFIRMS = {"material": ["крафт-картон"], "coating": ["PE"]}


def test_document_applies_only_to_matching_subcategory():
    """Чистая проверка применимости: общая категория не заменяет совпадение подкатегории."""
    from app.category_admission import canonical_scope, document_applies_to
    from app.models import Document

    def make_document(scope_category, scope_subcategory):
        return Document(
            company_id=None,
            name="Тест",
            document_type="declaration",
            file_key="tests/none",
            content_type="application/pdf",
            scope_category=scope_category,
            scope_subcategory=scope_subcategory,
        )

    cups = canonical_scope("Упаковка и тара", "Бумажные стаканы")
    legacy = canonical_scope("бумажные стаканы", None)
    assert legacy == ("упаковка и тара", "бумажные стаканы")

    applies, _ = document_applies_to(make_document("Упаковка и тара", "Бумажные стаканы"), cups)
    assert applies is True

    applies, _ = document_applies_to(make_document("Упаковка и тара", "Картонные коробки"), cups)
    assert applies is False

    applies, _ = document_applies_to(make_document("Продукты питания", "Напитки"), cups)
    assert applies is False

    # Документ без подкатегории — явное решение проверяющего о применении ко всей категории.
    applies, note = document_applies_to(make_document("Упаковка и тара", None), cups)
    assert applies is True
    assert note is None

    # Товар назван точным именем вместо ветки каталога.
    applies, _ = document_applies_to(make_document("Упаковка и тара", "Бумажные стаканы"), legacy)
    assert applies is True

    # Документ без области действия доказательством не считается.
    applies, _ = document_applies_to(make_document(None, None), cups)
    assert applies is False


async def test_wide_scope_requires_verifier_decision(client, db_session):
    """Документ, подтверждённый без подкатегории, действует на всю категорию с пояснением."""
    _, company, token, product_id = await _seller_with_product(client, db_session)
    admin_token = make_token(await make_marketplace_admin(db_session))

    for document_type in ("declaration", "test_report"):
        document = await _upload_document(client, token, company, document_type=document_type)
        verified = await client.post(
            f"/api/v1/documents/{document['id']}/verification",
            json={
                "decision": "verified",
                "scope_category": "Упаковка и тара",
                "confirms": {"material": ["крафт-картон"], "coating": ["PE"]},
                "note": "Подтверждено применение ко всей категории упаковки.",
            },
            headers=_auth(admin_token),
        )
        assert verified.status_code == 200, verified.text

    report = await client.get(
        f"/api/v1/companies/{company}/category-admission",
        params={"category": "Упаковка и тара", "subcategory": "Бумажные стаканы"},
        headers=_auth(token),
    )
    assert report.json()["state"] == "admitted"

    publish = await client.post(
        f"/api/v1/products/{product_id}/publish", json={"published": True}, headers=_auth(token)
    )
    assert publish.status_code == 200


async def test_unrefined_specification_gets_scope_note(client, db_session):
    """Потребность без подкатегории получает пояснение, а не молчаливое подтверждение."""
    user, company, token, product_id = await _seller_with_product(client, db_session)
    await grant_packaging_documents(
        db_session, company, decision_user_id=user, confirms={"material": ["крафт-картон"], "coating": ["PE"]}
    )

    # Товар без подкатегории, документы подтверждены для стаканов.
    changed = await client.patch(
        f"/api/v1/products/{product_id}", json={"subcategory": None}, headers=_auth(token)
    )
    assert changed.status_code == 200

    report = await client.get(
        f"/api/v1/companies/{company}/category-admission",
        params={"category": "Упаковка и тара"},
        headers=_auth(token),
    )
    body = report.json()
    assert body["state"] == "admitted"
    notes = [item["scope_note"] for item in body["requirements"] if item["scope_note"]]
    assert notes and "Подкатегория товара не указана" in notes[0]


def _verified_document(document_type: str, confirms: dict, *, scope_subcategory="Бумажные стаканы"):
    from app.models import Document

    return Document(
        company_id=__import__("uuid").uuid4(),
        name=f"Документ {document_type}",
        document_type=document_type,
        file_key="tests/admission",
        content_type="application/pdf",
        verification_status="verified",
        scope_category="Упаковка и тара",
        scope_subcategory=scope_subcategory,
        confirms=confirms,
    )


def test_confirmed_coating_must_match_product():
    """Подтверждённое покрытие PE не закрывает требование к товару с PLA."""
    from app.category_admission import evaluate_admission

    documents = [
        _verified_document("declaration", {}),
        _verified_document("test_report", {"coating": ["PE"], "material": ["крафт-картон"]}),
    ]

    admitted = evaluate_admission(
        category="Упаковка и тара",
        subcategory="Бумажные стаканы",
        characteristics={"volume_ml": 400, "coating": "PE", "material": "крафт-картон 300 г/м²"},
        documents=documents,
    )
    assert admitted.state == "admitted"
    states = {item.code: item.state for item in admitted.requirements}
    assert states["food_contact"] == "satisfied"

    blocked = evaluate_admission(
        category="Упаковка и тара",
        subcategory="Бумажные стаканы",
        characteristics={"volume_ml": 400, "coating": "PLA", "material": "крафт-картон 300 г/м²"},
        documents=documents,
    )
    assert blocked.state == "blocked"
    requirement = next(item for item in blocked.requirements if item.code == "food_contact")
    assert requirement.state == "attribute_mismatch"
    assert "PLA" in (requirement.scope_note or "")
    assert "PE" in (requirement.scope_note or "")


def test_unconfirmed_characteristics_block_requirement():
    """Если проверяющий не сопоставил документ с характеристикой, требование не закрыто."""
    from app.category_admission import evaluate_admission

    report = evaluate_admission(
        category="Упаковка и тара",
        subcategory="Бумажные стаканы",
        characteristics={"volume_ml": 400, "coating": "PE"},
        documents=[
            _verified_document("declaration", {}),
            _verified_document("test_report", {}),
        ],
    )
    assert report.state == "blocked"
    requirement = next(item for item in report.requirements if item.code == "food_contact")
    assert requirement.state == "needs_confirmation"
    assert "покрытие" in (requirement.scope_note or "")

    # Без указанного покрытия требование закрывается: сравнивать нечего.
    without_attribute = evaluate_admission(
        category="Упаковка и тара",
        subcategory="Бумажные стаканы",
        characteristics={"volume_ml": 400},
        documents=[
            _verified_document("declaration", {}),
            _verified_document("test_report", {}),
        ],
    )
    assert without_attribute.state == "admitted"


async def test_published_product_rejects_unconfirmed_coating(client, db_session):
    """Опубликованный товар нельзя перевести на покрытие, которое документы не подтверждают."""
    user, company, token, product_id = await _seller_with_product(client, db_session)
    await grant_packaging_documents(
        db_session, company, decision_user_id=user, confirms={"material": ["крафт-картон"], "coating": ["PE"]}
    )

    published = await client.post(
        f"/api/v1/products/{product_id}/publish", json={"published": True}, headers=_auth(token)
    )
    assert published.status_code == 200, published.text

    changed = await client.patch(
        f"/api/v1/products/{product_id}",
        json={"characteristics": {"volume_ml": 400, "coating": "PLA"}},
        headers=_auth(token),
    )
    assert changed.status_code == 409
    assert "покрытие" in changed.json()["detail"]

    # Товар остался на прежней спецификации: отклонённое изменение не применилось.
    current = await client.get(
        f"/api/v1/companies/{company}/products", headers=_auth(token)
    )
    stored = next(item for item in current.json() if item["id"] == product_id)
    assert stored["characteristics"]["coating"] == "PE"


async def test_restricted_category_requires_classification(client, db_session):
    """Ограниченная категория без подкатегории не публикуется, с подкатегорией — проверяется."""
    _, _, token, product_id = await _seller_with_product(
        client, db_session, category="Медицина и гигиена", subcategory=None
    )
    requirements = await client.get(
        "/api/v1/category-requirements", params={"category": "Медицина и гигиена"}
    )
    assert requirements.status_code == 200
    assert "Укажите подкатегорию" in requirements.json()["summary"]

    publish = await client.post(
        f"/api/v1/products/{product_id}/publish", json={"published": True}, headers=_auth(token)
    )
    assert publish.status_code == 409
    assert "не подтверждён" in publish.json()["detail"] or "подкатегорию" in publish.json()["detail"]

    # Немедицинская гигиеническая продукция сохраняет отдельный путь через документы.
    report = await client.get(
        "/api/v1/category-requirements",
        params={"category": "Медицина и гигиена", "subcategory": "Средства защиты"},
    )
    assert report.json()["profile_title"] == "Средства защиты и гигиеническая продукция"
    assert report.json()["checklist"]


async def test_reserve_commitment_requires_documents(client, db_session, monkeypatch):
    """Резерв — обязательство: без подтверждённых документов решение отклоняется."""
    from app.models import Need, Offer, OptimizationVariantRecord
    from test_stage6 import fake_resilience

    monkeypatch.setattr("app.api.resilience.calculate_resilience", fake_resilience)

    buyer_user = await make_user(db_session)
    buyer = await make_company(db_session, buyer_user, can_buy=True, can_sell=False)
    buyer_token = make_token(buyer_user)
    primary_user = await make_user(db_session)
    primary = await make_company(db_session, primary_user, can_buy=False, can_sell=True)
    reserve_user = await make_user(db_session)
    reserve = await make_company(db_session, reserve_user, can_buy=False, can_sell=True)
    reserve_token = make_token(reserve_user)

    need = Need(
        company_id=buyer,
        created_by_user_id=buyer_user,
        category="бумажные стаканы",
        characteristics={"volume_ml": 400},
        volume_units=5_000,
        deadline_date=date.today() + timedelta(days=30),
        status="open_for_offers",
    )
    db_session.add(need)
    await db_session.flush()
    # Приглашение в резерв получает компания, которая уже откликнулась на потребность.
    db_session.add(
        Offer(
            need_id=need.id,
            company_id=reserve,
            created_by_user_id=reserve_user,
            price_rub=12,
            available_units=5_000,
            lead_time_days=8,
            delivery_cost_rub=2_000,
            moq_units=1_000,
            price_tiers=[],
            status="sent",
        )
    )
    variant = OptimizationVariantRecord(
        need_id=need.id,
        kind="reliable",
        input_hash="admission-check",
        result={
            "feasible": True,
            "total_cost_rub": 52_000,
            "max_lead_time_days": 10,
            "allocations": [
                {
                    "company_id": str(primary),
                    "units": 5_000,
                    "unit_price_rub": 10,
                    "delivery_cost_rub": 2_000,
                    "total_cost_rub": 52_000,
                    "lead_time_days": 10,
                }
            ],
        },
    )
    db_session.add(variant)
    await db_session.commit()

    plan_response = await client.post(
        f"/api/v1/needs/{need.id}/resilience-plans",
        json={"variant_id": str(variant.id), "max_price_increase_pct": 5, "max_delay_days": 2},
        headers=_auth(buyer_token),
    )
    assert plan_response.status_code == 201, plan_response.text
    plan_id = plan_response.json()["id"]

    confirmed = await client.post(
        f"/api/v1/resilience-plans/{plan_id}/confirm",
        json={"approved": True},
        headers=_auth(buyer_token),
    )
    assert confirmed.status_code == 200, confirmed.text

    invitation = (
        await client.get(f"/api/v1/reserve-invitations/{reserve}", headers=_auth(reserve_token))
    ).json()[0]

    decision = {
        "company_id": str(reserve),
        "decision": "approved",
        "capacity_units": 5_000,
        "moq_units": 1_000,
        "unit_price_rub": 12,
        "delivery_cost_rub": 2_000,
        "lead_time_days": 8,
        "held_until": str(date.today() + timedelta(days=7)),
    }
    blocked = await client.post(
        f"/api/v1/reserve-commitments/{invitation['id']}/decision",
        json=decision,
        headers=_auth(reserve_token),
    )
    assert blocked.status_code == 409
    assert "не предоставлено" in blocked.json()["detail"]

    await grant_packaging_documents(db_session, reserve, decision_user_id=reserve_user)
    allowed = await client.post(
        f"/api/v1/reserve-commitments/{invitation['id']}/decision",
        json=decision,
        headers=_auth(reserve_token),
    )
    assert allowed.status_code == 200, allowed.text


async def test_documents_endpoints_work_end_to_end(client, db_session):
    """Список, отчёт о допуске и очередь проверки не должны падать на живом API."""
    _, company, token, _ = await _seller_with_product(client, db_session)
    document = await _upload_document(
        client, token, company, scope_category="Упаковка и тара", scope_subcategory="Бумажные стаканы"
    )

    listed = await client.get(f"/api/v1/companies/{company}/documents", headers=_auth(token))
    assert listed.status_code == 200, listed.text
    assert [item["id"] for item in listed.json()] == [document["id"]]
    assert listed.json()[0]["confirms"] == {}

    report = await client.get(
        f"/api/v1/companies/{company}/category-admission",
        params={"category": "Упаковка и тара", "subcategory": "Бумажные стаканы"},
        headers=_auth(token),
    )
    assert report.status_code == 200, report.text
    assert report.json()["blocking_open"] == 2
    assert report.json()["blocking_reasons"]

    admin_token = make_token(await make_marketplace_admin(db_session))
    queue = await client.get("/api/v1/admin/documents/pending", headers=_auth(admin_token))
    assert queue.status_code == 200, queue.text
    assert any(item["id"] == document["id"] for item in queue.json())

    deleted = await client.delete(f"/api/v1/documents/{document['id']}", headers=_auth(token))
    assert deleted.status_code == 204


async def test_buyer_checklist_shows_applicability_explanation(client, db_session):
    """Покупатель видит, к чему именно применён документ, а не только статус."""
    user, company, token, product_id = await _seller_with_product(client, db_session)
    await grant_packaging_documents(
        db_session, company, decision_user_id=user, confirms=CONFIRMS
    )

    published = await client.post(
        f"/api/v1/products/{product_id}/publish", json={"published": True}, headers=_auth(token)
    )
    assert published.status_code == 200, published.text

    # Товар без подкатегории: документы подтверждены для стаканов.
    changed = await client.patch(
        f"/api/v1/products/{product_id}", json={"subcategory": None}, headers=_auth(token)
    )
    assert changed.status_code == 200, changed.text

    checklist = await client.get(f"/api/v1/products/{product_id}/admission")
    assert checklist.status_code == 200, checklist.text
    notes = [item["scope_note"] for item in checklist.json()["checklist"] if item["scope_note"]]
    assert notes and "Подкатегория товара не указана" in notes[0]
    assert all(item["document_ids"] == [] for item in checklist.json()["checklist"])


async def test_evidence_change_notifies_active_deal(client, db_session):
    """Изменение допуска по действующей сделке требует ручного решения, а не молчаливой отмены."""
    seller_user = await make_user(db_session)
    seller_company = await make_company(db_session, seller_user, can_buy=False, can_sell=True)
    seller_token = make_token(seller_user)
    buyer_user = await make_user(db_session)
    buyer_company = await make_company(db_session, buyer_user, can_buy=True, can_sell=False)
    buyer_token = make_token(buyer_user)
    admin_token = make_token(await make_marketplace_admin(db_session))

    await grant_packaging_documents(
        db_session, seller_company, decision_user_id=seller_user, confirms={"material": ["крафт-картон"], "coating": ["PE"]}
    )
    product = await client.post(
        f"/api/v1/companies/{seller_company}/products",
        json={
            "name": "Стакан 400 мл PE",
            "category": "Упаковка и тара",
            "subcategory": "Бумажные стаканы",
            "characteristics": {"volume_ml": 400, "coating": "PE"},
            "price_rub": 11.2,
            "moq_units": 1_000,
            "lead_time_days": 9,
        },
        headers=_auth(seller_token),
    )
    assert product.status_code == 201
    assert (
        await client.post(
            f"/api/v1/products/{product.json()['id']}/publish",
            json={"published": True},
            headers=_auth(seller_token),
        )
    ).status_code == 200

    address = await client.post(
        f"/api/v1/companies/{buyer_company}/addresses",
        json={"address": "г. Москва, ул. Тестовая, 1", "city": "Москва", "region": "г. Москва", "is_default": True},
        headers=_auth(buyer_token),
    )
    need = await client.post(
        "/api/v1/needs",
        json={
            "company_id": str(buyer_company),
            "category": "бумажные стаканы",
            "characteristics": {"volume_ml": 400},
            "volume_units": 1_000,
            "budget_rub": 20_000,
            "deadline_date": str(date.today() + timedelta(days=30)),
            "delivery_address_id": address.json()["id"],
            "visibility": "open_anonymized",
        },
        headers=_auth(buyer_token),
    )
    await client.post(f"/api/v1/needs/{need.json()['id']}/publish", headers=_auth(buyer_token))
    offer = await client.post(
        f"/api/v1/needs/{need.json()['id']}/offers",
        json={
            "company_id": str(seller_company),
            "price_rub": 10,
            "available_units": 1_000,
            "moq_units": 1_000,
            "delivery_cost_rub": 0,
            "lead_time_days": 7,
        },
        headers=_auth(seller_token),
    )
    assert offer.status_code == 201, offer.text
    deal = await client.post(f"/api/v1/offers/{offer.json()['id']}/select", headers=_auth(buyer_token))
    assert deal.status_code == 201, deal.text

    document_id = (
        await db_session.execute(
            text(
                "SELECT id FROM marketplace.documents WHERE company_id = :cid "
                "AND document_type = 'test_report'"
            ),
            {"cid": seller_company},
        )
    ).scalar_one()
    rejected = await client.post(
        f"/api/v1/documents/{document_id}/verification",
        json={"decision": "rejected", "scope_category": "Упаковка и тара", "note": "Отозван изготовителем."},
        headers=_auth(admin_token),
    )
    assert rejected.status_code == 200

    messages = (
        await db_session.execute(
            text(
                "SELECT user_id, message FROM marketplace.notifications "
                "WHERE message LIKE '%не отменяются автоматически%'"
            )
        )
    ).mappings().all()
    assert messages
    receivers = {row["user_id"] for row in messages}
    assert seller_user in receivers
    assert buyer_user in receivers
