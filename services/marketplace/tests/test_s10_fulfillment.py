"""S10: исполнение, получение, расхождения, отмена и возврат.

S10.01 — получение подтверждается только при выбранном способе; порядок этапов.
S10.02 — самовывоз/перевозчик/доставка; опасный груз только вручную; строгий приоритет.
S10.03 — спор уведомляет вторую сторону и связан с версиями в аудите.
S10.04 — отмена после частичного исполнения освобождает фактический остаток; без новых заказов.
S10.05 — отзыв только после подтверждённого исполнения с чистым остатком; без дублей.
"""
import uuid
from datetime import date, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.models import Deal, DealCheckpoint, DealExecutionEvent, DeliveryAddress, Need, Notification, Offer, Product
from conftest import make_company, make_token, make_user


@pytest.fixture
async def order(db_session):
    buyer = await make_user(db_session)
    seller = await make_user(db_session)
    bc = await make_company(db_session, buyer, can_sell=False)
    sc = await make_company(db_session, seller, can_buy=False)
    address = DeliveryAddress(company_id=bc, address="г. Москва, ул. Синтетическая, д. 1",
                              city="Москва", region="Москва")
    db_session.add(address)
    await db_session.flush()
    need = Need(company_id=bc, created_by_user_id=buyer, category="Мебель", characteristics={},
                volume_units=10, budget_rub=20000, deadline_date=date.today() + timedelta(days=20),
                delivery_address_id=address.id, visibility="public", status="matched")
    db_session.add(need)
    await db_session.flush()
    offer = Offer(need_id=need.id, company_id=sc, created_by_user_id=seller, price_rub=1000,
                  available_units=10, lead_time_days=2, delivery_cost_rub=0, moq_units=1,
                  price_tiers=[], status="selected")
    db_session.add(offer)
    await db_session.flush()
    deal = Deal(offer_id=offer.id, need_id=need.id, buyer_company_id=bc, seller_company_id=sc,
                units=10, total_price_rub=10000, unit_price_rub=Decimal("1000"),
                delivery_price_rub=0, status="created")
    db_session.add(deal)
    await db_session.commit()
    return {"deal": deal.id, "bc": bc, "sc": sc,
            "bh": {"Authorization": f"Bearer {make_token(buyer)}"},
            "sh": {"Authorization": f"Bearer {make_token(seller)}"}}


async def complete_checkpoint(client, order, kind, headers, company):
    return await client.patch(f"/api/v1/deals/{order['deal']}/timeline/{kind}", headers=headers,
                              json={"company_id": str(company), "completed": True,
                                    "note": "Подтверждено", "human_approved": True})


@pytest.mark.asyncio
async def test_delivery_requires_arrangement(client, order):
    deal, bc, sc, bh, sh = order["deal"], order["bc"], order["sc"], order["bh"], order["sh"]
    assert (await complete_checkpoint(client, order, "production", sh, sc)).status_code == 200
    assert (await complete_checkpoint(client, order, "shipment", sh, sc)).status_code == 200
    denied = await complete_checkpoint(client, order, "delivery", bh, bc)
    assert denied.status_code == 409
    assert "способ получения" in denied.text
    saved = await client.put(f"/api/v1/deals/{deal}/delivery", headers=bh,
                             json={"company_id": str(bc), "weight_kg": 100, "volume_m3": 0.5,
                                   "method": "self_pickup", "human_approved": True})
    assert saved.status_code == 200, saved.text
    assert saved.json()["cargo_class"] == "small"
    assert (await complete_checkpoint(client, order, "delivery", bh, bc)).status_code == 200


@pytest.mark.asyncio
async def test_hazard_and_strict_classification(client, order):
    deal, bc, bh = order["deal"], order["bc"], order["bh"]
    hazmat = await client.put(f"/api/v1/deals/{deal}/delivery", headers=bh,
                              json={"company_id": str(bc), "weight_kg": 10, "volume_m3": 0.1,
                                    "method": "buyer_carrier", "carrier_name": "Деловые Линии",
                                    "hazard_class": "3", "human_approved": True})
    assert hazmat.status_code == 200, hazmat.text
    assert hazmat.json()["cargo_class"] == "manual_review"
    assert "Опасный груз" in hazmat.json()["classification_note"]
    heavy = await client.put(f"/api/v1/deals/{deal}/delivery", headers=bh,
                             json={"company_id": str(bc), "weight_kg": 100, "volume_m3": 20,
                                   "method": "self_pickup", "hazard_class": None, "human_approved": True})
    assert heavy.json()["cargo_class"] == "large"
    borderline = await client.put(f"/api/v1/deals/{deal}/delivery", headers=bh,
                                  json={"company_id": str(bc), "weight_kg": 100, "volume_m3": 13,
                                        "method": "self_pickup", "hazard_class": None, "human_approved": True})
    assert borderline.json()["cargo_class"] == "manual_review"
    no_carrier = await client.put(f"/api/v1/deals/{deal}/delivery", headers=bh,
                                  json={"company_id": str(bc), "weight_kg": 100, "volume_m3": 0.5,
                                        "method": "buyer_carrier", "human_approved": True})
    assert no_carrier.status_code == 422


@pytest.mark.asyncio
async def test_hazard_flag_survives_reedit_and_clears_explicitly(client, order):
    deal, bc, bh = order["deal"], order["bc"], order["bh"]
    base = {"company_id": str(bc), "weight_kg": 10, "volume_m3": 0.1,
            "method": "self_pickup", "human_approved": True}
    marked = await client.put(f"/api/v1/deals/{deal}/delivery", headers=bh,
                              json={**base, "hazard_class": "3"})
    assert marked.status_code == 200, marked.text
    assert marked.json()["cargo_class"] == "manual_review"
    assert marked.json()["hazard_class"] == "3"
    reedited = await client.put(f"/api/v1/deals/{deal}/delivery", headers=bh,
                                json={**base, "weight_kg": 11})
    assert reedited.status_code == 200, reedited.text
    assert reedited.json()["cargo_class"] == "manual_review"
    assert reedited.json()["hazard_class"] == "3"
    cleared = await client.put(f"/api/v1/deals/{deal}/delivery", headers=bh,
                               json={**base, "hazard_class": None})
    assert cleared.status_code == 200, cleared.text
    assert cleared.json()["cargo_class"] == "small"
    assert cleared.json()["hazard_class"] is None


@pytest.mark.asyncio
async def test_dispute_notifies_counterparty_and_pins_versions(client, order, db_session):
    deal, bc, sc, bh, sh = order["deal"], order["bc"], order["sc"], order["bh"], order["sh"]
    assert (await complete_checkpoint(client, order, "production", sh, sc)).status_code == 200
    assert (await complete_checkpoint(client, order, "shipment", sh, sc)).status_code == 200
    bypass = await client.post(f"/api/v1/deals/{deal}/execution", headers=bh,
                               json={"company_id": str(bc), "kind": "acceptance", "units": 10,
                                     "note": "Без способа получения", "human_approved": True,
                                     "idempotency_key": str(uuid.uuid4())})
    assert bypass.status_code == 409
    saved = await client.put(f"/api/v1/deals/{deal}/delivery", headers=bh,
                             json={"company_id": str(bc), "weight_kg": 100, "volume_m3": 0.5,
                                   "method": "self_pickup", "human_approved": True})
    assert saved.status_code == 200
    accepted = await client.post(f"/api/v1/deals/{deal}/execution", headers=bh,
                                 json={"company_id": str(bc), "kind": "acceptance", "units": 10,
                                       "note": "Принято по акту", "human_approved": True,
                                       "idempotency_key": str(uuid.uuid4())})
    assert accepted.status_code == 201, accepted.text
    returned = await client.post(f"/api/v1/deals/{deal}/execution", headers=bh,
                                 json={"company_id": str(bc), "kind": "return", "units": 3,
                                       "note": "Бой, партия А", "human_approved": True,
                                       "idempotency_key": str(uuid.uuid4())})
    assert returned.status_code == 201, returned.text
    notes = (await db_session.scalars(
        select(Notification).where(Notification.type == "deal_execution_requested"))).all()
    assert notes, "вторая сторона уведомлена о споре"
    assert any(str(deal) in note.message and returned.json()["id"] in note.message
               and "возврат" in note.message for note in notes)
    from app.models import TrustAuditEvent
    audits = (await db_session.scalars(select(TrustAuditEvent).where(
        TrustAuditEvent.event_type == "human_approval_recorded"))).all()
    record_approvals = [event for event in audits
                        if (event.payload.get("decision_payload") or {}).get("event_id") == returned.json()["id"]]
    assert record_approvals, "запись спора связана с событием"
    assert "need_revision" in (record_approvals[0].payload.get("decision_payload") or {})


@pytest.mark.asyncio
async def test_notifications_distinguish_two_deals(client, db_session):
    """P2-3: уведомления разных сделок различимы: сделка, запрос, компания, единица."""
    from conftest import make_company as _make_company, make_token as _make_token, make_user as _make_user
    buyer = await _make_user(db_session)
    seller = await _make_user(db_session)
    bc = await _make_company(db_session, buyer, can_sell=False)
    sc = await _make_company(db_session, seller, can_buy=False)
    bh = {"Authorization": f"Bearer {_make_token(buyer)}"}
    deal_ids = []
    for _ in range(2):
        address = DeliveryAddress(company_id=bc, address="г. Москва, ул. Синтетическая, д. 1",
                                  city="Москва", region="Москва")
        db_session.add(address)
        await db_session.flush()
        need = Need(company_id=bc, created_by_user_id=buyer, category="Мебель",
                    characteristics={"unit": "компл."}, volume_units=10, budget_rub=20000,
                    deadline_date=date.today() + timedelta(days=20),
                    delivery_address_id=address.id, visibility="public", status="matched")
        db_session.add(need)
        await db_session.flush()
        offer = Offer(need_id=need.id, company_id=sc, created_by_user_id=seller, price_rub=1000,
                      available_units=10, lead_time_days=2, delivery_cost_rub=0, moq_units=1,
                      price_tiers=[], status="selected")
        db_session.add(offer)
        await db_session.flush()
        deal = Deal(offer_id=offer.id, need_id=need.id, buyer_company_id=bc, seller_company_id=sc,
                    units=10, total_price_rub=10000, unit_price_rub=Decimal("1000"),
                    delivery_price_rub=0, status="shipped")
        db_session.add(deal)
        await db_session.flush()
        for kind in ("production", "shipment"):
            db_session.add(DealCheckpoint(deal_id=deal.id, kind=kind, status="completed"))
        await db_session.commit()
        arrangement = await client.put(f"/api/v1/deals/{deal.id}/delivery", headers=bh,
                                       json={"company_id": str(bc), "weight_kg": 100, "volume_m3": 0.5,
                                             "method": "self_pickup", "human_approved": True})
        assert arrangement.status_code == 200
        accepted = await client.post(f"/api/v1/deals/{deal.id}/execution", headers=bh,
                                     json={"company_id": str(bc), "kind": "acceptance", "units": 10,
                                           "note": "Принято по акту", "human_approved": True,
                                           "idempotency_key": str(uuid.uuid4())})
        assert accepted.status_code == 201
        returned = await client.post(f"/api/v1/deals/{deal.id}/execution", headers=bh,
                                     json={"company_id": str(bc), "kind": "return", "units": 2,
                                           "note": "Часть партии", "human_approved": True,
                                           "idempotency_key": str(uuid.uuid4())})
        assert returned.status_code == 201
        deal_ids.append((str(deal.id), returned.json()["id"]))
    notes = (await db_session.scalars(
        select(Notification).where(Notification.type == "deal_execution_requested"))).all()
    assert len(notes) == 2
    for (deal_id, event_id), note in zip(deal_ids, sorted(notes, key=lambda item: item.created_at)):
        assert deal_id in note.message and event_id in note.message
        assert "возврат" in note.message
        assert "комплект" in note.message


@pytest.mark.asyncio
async def test_cancel_after_partial_frees_actual_remainder(client, db_session):
    from datetime import datetime, timezone
    from app.resources import consume, free_stock, reserve
    buyer = await make_user(db_session)
    seller = await make_user(db_session)
    bc = await make_company(db_session, buyer, can_sell=False)
    sc = await make_company(db_session, seller, can_buy=False)
    product = Product(company_id=sc, name="Стол", category="Мебель", characteristics={}, price_rub=1000,
                      price_tiers=[], moq_units=1, lead_time_days=1, stock_units=10,
                      stock_updated_at=datetime.now(timezone.utc))
    db_session.add(product)
    await db_session.commit()
    anchor = uuid.uuid4()
    await reserve(db_session, company_id=sc, anchor_type="deal", anchor_id=anchor,
                  units=10, deadline=date.today(), resource_kind="stock", product_id=product.id)
    assert await consume(db_session, company_id=sc, anchor_type="deal", anchor_id=anchor, units=6) == 6
    await db_session.commit()
    from app.resources import release
    assert await release(db_session, company_id=sc, anchor_type="deal", anchor_id=anchor) == 4
    await db_session.commit()
    assert await free_stock(db_session, await db_session.get(Product, product.id)) == 4


@pytest.mark.asyncio
async def test_review_requires_performance_and_no_duplicates(client, order):
    deal, bc, bh = order["deal"], order["bc"], order["bh"]
    early = await client.post(f"/api/v1/deals/{deal}/reviews", headers=bh,
                              json={"company_id": str(bc), "rating": 5, "comment": "Отличная поставка, всё в срок"})
    assert early.status_code == 409
    sc, sh = order["sc"], order["sh"]
    assert (await complete_checkpoint(client, order, "production", sh, sc)).status_code == 200
    assert (await complete_checkpoint(client, order, "shipment", sh, sc)).status_code == 200
    saved = await client.put(f"/api/v1/deals/{deal}/delivery", headers=bh,
                             json={"company_id": str(bc), "weight_kg": 100, "volume_m3": 0.5,
                                   "method": "self_pickup", "human_approved": True})
    assert saved.status_code == 200
    assert (await complete_checkpoint(client, order, "delivery", bh, bc)).status_code == 200
    no_performance = await client.post(f"/api/v1/deals/{deal}/reviews", headers=bh,
                                       json={"company_id": str(bc), "rating": 5, "comment": "Отличная поставка, всё в срок"})
    assert no_performance.status_code == 409
    accepted = await client.post(f"/api/v1/deals/{deal}/execution", headers=bh,
                                 json={"company_id": str(bc), "kind": "acceptance", "units": 10,
                                       "note": "Принято полностью", "human_approved": True,
                                       "idempotency_key": str(uuid.uuid4())})
    assert accepted.status_code == 201
    first = await client.post(f"/api/v1/deals/{deal}/reviews", headers=bh,
                              json={"company_id": str(bc), "rating": 5, "comment": "Отличная поставка, всё в срок"})
    assert first.status_code == 201, first.text
    duplicate = await client.post(f"/api/v1/deals/{deal}/reviews", headers=bh,
                                  json={"company_id": str(bc), "rating": 4, "comment": "Второй отзыв по той же сделке"})
    assert duplicate.status_code == 409


@pytest.mark.asyncio
async def test_full_return_blocks_review(client, order):
    deal, bc, sc, bh, sh = order["deal"], order["bc"], order["sc"], order["bh"], order["sh"]
    assert (await complete_checkpoint(client, order, "production", sh, sc)).status_code == 200
    assert (await complete_checkpoint(client, order, "shipment", sh, sc)).status_code == 200
    saved = await client.put(f"/api/v1/deals/{deal}/delivery", headers=bh,
                             json={"company_id": str(bc), "weight_kg": 100, "volume_m3": 0.5,
                                   "method": "self_pickup", "human_approved": True})
    assert saved.status_code == 200
    assert (await complete_checkpoint(client, order, "delivery", bh, bc)).status_code == 200
    accepted = await client.post(f"/api/v1/deals/{deal}/execution", headers=bh,
                                 json={"company_id": str(bc), "kind": "acceptance", "units": 10,
                                       "note": "Принято", "human_approved": True,
                                       "idempotency_key": str(uuid.uuid4())})
    assert accepted.status_code == 201
    returned = await client.post(f"/api/v1/deals/{deal}/execution", headers=bh,
                                 json={"company_id": str(bc), "kind": "return", "units": 10,
                                       "note": "Возврат всего объёма", "human_approved": True,
                                       "idempotency_key": str(uuid.uuid4())})
    assert returned.status_code == 201
    decided = await client.post(f"/api/v1/deals/{deal}/execution/{returned.json()['id']}/decision",
                                headers=sh,
                                json={"company_id": str(sc), "approved": True, "human_approved": True})
    assert decided.status_code == 200, decided.text
    blocked = await client.post(f"/api/v1/deals/{deal}/reviews", headers=bh,
                                json={"company_id": str(bc), "rating": 2, "comment": "Вернули весь объём поставки"})
    assert blocked.status_code == 409
