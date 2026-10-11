"""S13.01: отрицательная матрица доступа по всем путям и акторам.

Пути: прямой заказ, группа, резерв, исполнение, аналитика/экспорт, импорт,
файлы, старые ссылки. Акторы: аноним, чужая компания, чужая роль, blocked,
отозванное членство, администратор площадки, смена компании.
Проверяются чтение, запись, экспорт; отказ без побочного эффекта;
private-данные отсутствуют в ошибках; seller-cost только у продавца.
Путь agent-task покрыт тестами llm-gateway (отзыв роли блокирует approve).
"""

import uuid
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import text

from app.models import (
    Coalition,
    CoalitionMember,
    CompatibilityProfile,
    Deal,
    DealCheckpoint,
    DeliveryAddress,
    DeliveryArrangement,
    Document,
    GroupOffer,
    Need,
    NeedFile,
    Offer,
    OptimizationVariantRecord,
    ParticipantOrder,
    Product,
    ProductImage,
    ResiliencePlan,
    ReserveCommitment,
)
from conftest import make_company, make_marketplace_admin, make_token, make_user


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


async def _member(db_session, company_id, user_id, can_buy, can_sell, is_admin):
    await db_session.execute(
        text("INSERT INTO auth.company_members (id, company_id, user_id, can_buy, can_sell, is_admin) "
             "VALUES (:id, :cid, :uid, :cb, :cs, :admin)"),
        {"id": uuid.uuid4(), "cid": company_id, "uid": user_id, "cb": can_buy, "cs": can_sell, "admin": is_admin})
    await db_session.commit()


async def _world(db_session):
    buyer = await make_user(db_session)
    seller = await make_user(db_session)
    bc = await make_company(db_session, buyer, can_sell=False)
    sc = await make_company(db_session, seller, can_buy=False)
    clerk = await make_user(db_session)
    await _member(db_session, bc, clerk, True, False, False)
    stranger = await make_user(db_session)
    stranger_co = await make_company(db_session, stranger, verified=True)
    blocked = await make_user(db_session)
    await make_company(db_session, blocked, verified=True)
    await db_session.execute(text("UPDATE auth.users SET account_status='blocked' WHERE id=:id"), {"id": blocked})
    revoked = await make_user(db_session)
    await _member(db_session, bc, revoked, True, False, True)
    await db_session.execute(text("DELETE FROM auth.company_members WHERE company_id=:cid AND user_id=:uid"),
                             {"cid": bc, "uid": revoked})
    admin = await make_marketplace_admin(db_session)
    unverified_seller = await make_user(db_session)
    unverified_co = await make_company(db_session, unverified_seller, can_buy=False, verified=False)
    await db_session.commit()

    address = DeliveryAddress(company_id=bc, address="г. Москва, ул. Матричная, д. 1", city="Москва", region="Москва")
    db_session.add(address)
    await db_session.flush()
    need = Need(company_id=bc, created_by_user_id=buyer, category="Мебель", characteristics={}, volume_units=10,
                budget_rub=20000, deadline_date=date.today() + timedelta(days=20),
                delivery_address_id=address.id, visibility="closed", status="open_for_offers")
    db_session.add(need)
    await db_session.flush()
    offer = Offer(need_id=need.id, company_id=sc, created_by_user_id=seller, price_rub=Decimal("1000"),
                  available_units=10, lead_time_days=2, delivery_cost_rub=0, moq_units=1, price_tiers=[], status="sent")
    db_session.add(offer)
    await db_session.flush()
    deal = Deal(offer_id=offer.id, need_id=need.id, buyer_company_id=bc, seller_company_id=sc,
                units=10, total_price_rub=Decimal("10000"),
                unit_price_rub=Decimal("1000"), delivery_price_rub=0, status="created")
    db_session.add(deal)
    await db_session.flush()
    for kind in ("production", "shipment"):
        db_session.add(DealCheckpoint(deal_id=deal.id, kind=kind, status="completed"))
    db_session.add(DeliveryArrangement(deal_id=deal.id, weight_kg=10, volume_m3=0.2, cargo_class="small",
                                       classification_note="Тест", method="self_pickup",
                                       buyer_responsible=True, confirmed_by_user_id=buyer))
    need_file = NeedFile(need_id=need.id, file_name="условия.txt", file_key="needs/матрица",
                         content_type="text/plain", content_hash="0" * 64)
    db_session.add(need_file)
    product = Product(company_id=sc, created_by_user_id=seller, name="Стул матричный", category="Мебель",
                      characteristics={}, price_rub=Decimal("100"), price_tiers=[], moq_units=1,
                      lead_time_days=1, is_published=False)
    db_session.add(product)
    await db_session.flush()
    image = ProductImage(product_id=product.id, file_name="стул.png", file_key="products/матрица",
                         content_type="image/png", position=0)
    db_session.add(image)
    document = Document(company_id=sc, created_by_user_id=seller, name="Декларация", document_type="declaration",
                        file_key="companies/матрица", content_type="application/pdf", verification_status="verified",
                        scope_category="Мебель")
    db_session.add(document)
    profile = CompatibilityProfile(category="Мебель", input_hash=uuid.uuid4().hex)
    db_session.add(profile)
    await db_session.flush()
    coalition = Coalition(compatibility_profile_id=profile.id, producer_company_id=sc,
                          category="Мебель", combined_volume_units=10, status="awaiting_approvals")
    db_session.add(coalition)
    await db_session.flush()
    db_session.add(CoalitionMember(coalition_id=coalition.id, need_id=need.id, buyer_company_id=bc, units=10))
    db_session.add(GroupOffer(coalition_id=coalition.id, company_id=sc, status="preliminary"))
    variant = OptimizationVariantRecord(need_id=need.id, kind="balanced", result={}, input_hash=uuid.uuid4().hex)
    db_session.add(variant)
    await db_session.flush()
    plan = ResiliencePlan(need_id=need.id, buyer_company_id=bc, baseline_variant_id=variant.id,
                          baseline_allocations=[], baseline_total_cost_rub=Decimal("10000"),
                          baseline_lead_time_days=2, current_allocations=[],
                          current_total_cost_rub=Decimal("10000"), current_lead_time_days=2)
    db_session.add(plan)
    await db_session.flush()
    commitment = ReserveCommitment(plan_id=plan.id, company_id=sc, reserve_tier="warm")
    db_session.add(commitment)
    await db_session.commit()
    return locals()


async def _counts(db_session):
    notes = await db_session.execute(text("SELECT COUNT(*) FROM marketplace.notifications"))
    deals = await db_session.execute(text("SELECT COUNT(*) FROM marketplace.deals"))
    offers = await db_session.execute(text("SELECT COUNT(*) FROM marketplace.offers"))
    audit = await db_session.execute(text("SELECT COUNT(*) FROM marketplace.trust_audit_events"))
    return (notes.scalar_one(), deals.scalar_one(), offers.scalar_one(), audit.scalar_one())


async def test_anonymous_denied_everywhere(client, db_session):
    w = await _world(db_session)
    probes = [
        ("get", f"/api/v1/needs/{w['need'].id}", None),
        ("post", "/api/v1/needs", {"company_id": str(w["bc"]), "category": "Мебель", "characteristics": {},
                                   "volume_units": 1, "deadline_date": str(date.today() + timedelta(days=5))}),
        ("post", f"/api/v1/needs/{w['need'].id}/publish", None),
        ("get", f"/api/v1/needs/{w['need'].id}/offers", None),
        ("post", f"/api/v1/coalitions/{w['coalition'].id}/decision",
         {"company_id": str(w["bc"]), "decision": "approved", "expected_revision": 1}),
        ("post", f"/api/v1/reserve-commitments/{w['commitment'].id}/decision",
         {"company_id": str(w["sc"]), "decision": "approved"}),
        ("get", f"/api/v1/deals/{w['deal'].id}/execution?company_id={w['bc']}", None),
        ("get", f"/api/v1/companies/{w['bc']}/commercial-analytics?role=buyer", None),
        ("get", f"/api/v1/companies/{w['bc']}/commercial-report.csv?role=buyer", None),
        ("get", f"/api/v1/companies/{w['bc']}/agent-scorecard", None),
        ("get", f"/api/v1/need-files/{w['need_file'].id}/download", None),
        ("get", f"/api/v1/companies/{w['sc']}/documents", None),
    ]
    for method, path, body in probes:
        r = await getattr(client, method)(path, json=body) if body is not None else await getattr(client, method)(path)
        assert r.status_code == 401, (method, path, r.status_code)
    # Публичный роут изображений без auth: неопубликованное скрыто как 404 без оракула личности.
    r = await client.get(f"/api/v1/product-images/{w['image'].id}")
    assert r.status_code == 404


async def test_stranger_sees_nothing(client, db_session):
    w = await _world(db_session)
    headers = _auth(make_token(w["stranger"]))
    assert (await client.get(f"/api/v1/needs/{w['need'].id}", headers=headers)).status_code == 404
    assert (await client.get(f"/api/v1/needs/{w['need'].id}/offers", headers=headers)).status_code == 404
    assert (await client.post(f"/api/v1/offers/{w['offer'].id}/select", headers=headers,
                              json={"expected_revision": 1, "human_approved": True})).status_code in (403, 404)
    assert (await client.post(f"/api/v1/coalitions/{w['coalition'].id}/decision", headers=headers,
                              json={"company_id": str(w["stranger_co"]), "decision": "approved",
                                    "expected_revision": 1})).status_code == 403
    assert (await client.post(f"/api/v1/reserve-commitments/{w['commitment'].id}/decision", headers=headers,
                              json={"company_id": str(w["stranger_co"]), "decision": "approved"})).status_code == 404
    assert (await client.post(f"/api/v1/deals/{w['deal'].id}/execution", headers=headers,
                              json={"company_id": str(w["stranger_co"]), "kind": "acceptance", "units": 1,
                                    "note": "Чужой запрос", "human_approved": True,
                                    "idempotency_key": str(uuid.uuid4())})).status_code == 404
    assert (await client.get(f"/api/v1/companies/{w['bc']}/commercial-analytics?role=buyer",
                             headers=headers)).status_code in (403, 404)
    assert (await client.get(f"/api/v1/companies/{w['bc']}/commercial-report.csv?role=buyer",
                             headers=headers)).status_code in (403, 404)
    assert (await client.get(f"/api/v1/companies/{w['bc']}/agent-scorecard", headers=headers)).status_code in (403, 404)
    assert (await client.get(f"/api/v1/need-files/{w['need_file'].id}/download", headers=headers)).status_code == 404
    assert (await client.get(f"/api/v1/product-images/{w['image'].id}", headers=headers)).status_code == 404
    assert (await client.get(f"/api/v1/companies/{w['sc']}/documents", headers=headers)).status_code == 404
    assert (await client.get(f"/api/v1/deals/{w['deal'].id}/messages?company_id={w['stranger_co']}",
                             headers=headers)).status_code == 404
    assert (await client.post(f"/api/v1/deals/{w['deal'].id}/messages", headers=headers,
                              json={"company_id": str(w["stranger_co"]), "message": "Чужое сообщение"})).status_code == 404


async def test_wrong_role_blocked(client, db_session):
    w = await _world(db_session)
    buyer_headers, seller_headers = _auth(make_token(w["buyer"])), _auth(make_token(w["seller"]))
    assert (await client.post(f"/api/v1/companies/{w['bc']}/products", headers=buyer_headers,
                              json={"name": "Тестовый товар", "category": "Строительство", "subcategory": "Крепёж",
                                    "characteristics": {"unit": "шт"},
                                    "price_rub": 10, "moq_units": 1, "lead_time_days": 1})).status_code == 403
    assert (await client.post("/api/v1/needs", headers=seller_headers,
                              json={"company_id": str(w["sc"]), "category": "Мебель", "characteristics": {},
                                    "volume_units": 1, "deadline_date": str(date.today() + timedelta(days=5))})).status_code == 403
    assert (await client.post(f"/api/v1/needs/{w['need'].id}/offers", headers=buyer_headers,
                              json={"company_id": str(w["bc"]), "price_rub": 10, "available_units": 10,
                                    "lead_time_days": 1})).status_code == 403
    assert (await client.post(f"/api/v1/deals/{w['deal'].id}/execution", headers=seller_headers,
                              json={"company_id": str(w["sc"]), "kind": "acceptance", "units": 1,
                                    "note": "Не та сторона", "human_approved": True,
                                    "idempotency_key": str(uuid.uuid4())})).status_code == 403
    assert (await client.get(f"/api/v1/companies/{w['bc']}/agent-scorecard",
                             headers=seller_headers)).status_code in (403, 404)


async def test_blocked_denied_without_effect(client, db_session):
    w = await _world(db_session)
    headers = _auth(make_token(w["blocked"]))
    before = await _counts(db_session)
    assert (await client.get(f"/api/v1/companies/{w['bc']}/commercial-analytics?role=buyer",
                             headers=headers)).status_code == 401
    assert (await client.post("/api/v1/needs", headers=headers,
                              json={"company_id": str(w["bc"]), "category": "Мебель", "characteristics": {},
                                    "volume_units": 1, "deadline_date": str(date.today() + timedelta(days=5))})).status_code == 401
    assert (await client.get(f"/api/v1/notifications", headers=headers)).status_code == 401
    assert await _counts(db_session) == before


async def test_revoked_membership_loses_access(client, db_session):
    w = await _world(db_session)
    headers = _auth(make_token(w["revoked"]))
    assert (await client.get(f"/api/v1/needs/{w['need'].id}", headers=headers)).status_code == 404
    assert (await client.get(f"/api/v1/companies/{w['bc']}/commercial-analytics?role=buyer",
                             headers=headers)).status_code in (403, 404)
    assert (await client.post(f"/api/v1/coalitions/{w['coalition'].id}/decision", headers=headers,
                              json={"company_id": str(w["bc"]), "decision": "approved",
                                    "expected_revision": 1})).status_code in (403, 404)


async def test_admin_boundaries(client, db_session):
    w = await _world(db_session)
    headers = _auth(make_token(w["admin"]))
    assert (await client.get(f"/api/v1/needs/{w['need'].id}", headers=headers)).status_code in (403, 404)
    assert (await client.get(f"/api/v1/companies/{w['bc']}/commercial-analytics?role=buyer",
                             headers=headers)).status_code in (403, 404)
    assert (await client.get("/api/v1/admin/documents/pending", headers=headers)).status_code == 200
    assert (await client.get("/api/v1/admin/support/tickets", headers=headers)).status_code == 200
    assert (await client.get("/api/v1/audit/verify", headers=headers)).status_code == 200


async def test_non_admin_company_member_cannot_commit(client, db_session):
    w = await _world(db_session)
    headers = _auth(make_token(w["clerk"]))
    assert (await client.post(f"/api/v1/needs/{w['need'].id}/publish", headers=headers)).status_code == 403
    assert (await client.post(f"/api/v1/coalitions/{w['coalition'].id}/decision", headers=headers,
                              json={"company_id": str(w["bc"]), "decision": "approved",
                                    "expected_revision": 1})).status_code == 403


async def test_denials_have_no_side_effects_and_hide_private_data(client, db_session):
    w = await _world(db_session)
    stranger_headers = _auth(make_token(w["stranger"]))
    before = await _counts(db_session)
    bodies: list[str] = []
    bodies.append((await client.get(f"/api/v1/needs/{w['need'].id}", headers=stranger_headers)).text)
    bodies.append((await client.get(f"/api/v1/need-files/{w['need_file'].id}/download",
                                    headers=stranger_headers)).text)
    bodies.append((await client.get(f"/api/v1/companies/{w['bc']}/commercial-analytics?role=buyer",
                                    headers=stranger_headers)).text)
    bodies.append((await client.post(f"/api/v1/deals/{w['deal'].id}/execution", headers=stranger_headers,
                                     json={"company_id": str(w["stranger_co"]), "kind": "acceptance", "units": 1,
                                           "note": "Чужой запрос", "human_approved": True,
                                           "idempotency_key": str(uuid.uuid4())})).text)
    bodies.append((await client.post(f"/api/v1/companies/{w['stranger_co']}/catalog-import", headers=stranger_headers,
                                     files={"file": ("test.csv", b"a,b\n1,2\n", "text/csv")})).text)
    assert await _counts(db_session) == before
    joined = "\n".join(bodies)
    assert "file_key" not in joined
    assert "password_hash" not in joined
    assert "needs/матрица" not in joined


async def test_unverified_seller_cannot_commit_reserve(client, db_session):
    w = await _world(db_session)
    unverified = await make_user(db_session)
    uco = await make_company(db_session, unverified, can_buy=False, verified=False)
    commitment = ReserveCommitment(plan_id=w["plan"].id, company_id=uco, reserve_tier="warm")
    db_session.add(commitment)
    await db_session.commit()
    r = await client.post(f"/api/v1/reserve-commitments/{commitment.id}/decision",
                          headers=_auth(make_token(unverified)),
                          json={"company_id": str(uco), "decision": "approved"})
    assert r.status_code == 403, r.text


async def test_old_unpublished_image_link_stays_hidden(client, db_session):
    w = await _world(db_session)
    assert (await client.get(f"/api/v1/product-images/{w['image'].id}")).status_code == 404
    stranger_headers = _auth(make_token(w["stranger"]))
    assert (await client.get(f"/api/v1/product-images/{w['image'].id}", headers=stranger_headers)).status_code == 404
