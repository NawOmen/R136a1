"""S06: общий учёт склада/мощности, жизненный цикл и сверка ledger.

S06.01 — свободно = подтверждённая доступность − удержания − обязательства.
S06.02 — атомарные переходы под блокировкой компании; oversell исключён.
S06.03 — held/committed/consumed/released, TTL, возврат только по решению о качестве.
S06.04 — сверка выявляет orphan/double/negative/expired; ремонт идемпотентен и пишется в аудит.
"""
import uuid
from datetime import date, datetime, timedelta, timezone

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from app.models import CapacityEntry, Deal, Offer, Product, ResourceReservation
from app.resource_scopes import prepare_conversions
from test_commerce import order
from app.resources import (
    activate_hold,
    consume,
    free_stock,
    reconcile_company,
    release,
    reserve,
    return_stock,
    sweep_expired_holds,
)
from conftest import grant_capacity, make_company, make_token, make_user


@pytest.fixture
async def warehouse(db_session):
    user = await make_user(db_session)
    company = await make_company(db_session, user, can_buy=False)
    product = Product(
        company_id=company, name="Стол", category="Мебель", characteristics={},
        price_rub=1000, price_tiers=[], moq_units=1, lead_time_days=1,
        stock_units=10, stock_updated_at=datetime.now(timezone.utc),
    )
    db_session.add(product)
    await db_session.commit()
    return user, company, product.id


@pytest.mark.asyncio
async def test_release_is_idempotent(warehouse, db_session):
    _, company, product_id = warehouse
    anchor = uuid.uuid4()
    await reserve(db_session, company_id=company, anchor_type="deal", anchor_id=anchor,
                  units=4, deadline=date.today(), resource_kind="stock", product_id=product_id)
    assert await release(db_session, company_id=company, anchor_type="deal", anchor_id=anchor) == 4
    assert await release(db_session, company_id=company, anchor_type="deal", anchor_id=anchor) == 0
    product = await db_session.get(Product, product_id)
    assert await free_stock(db_session, product) == 10


@pytest.mark.asyncio
async def test_expired_hold_sweep_is_idempotent(warehouse, db_session):
    _, company, product_id = warehouse
    anchor = uuid.uuid4()
    await reserve(db_session, company_id=company, anchor_type="reserve", anchor_id=anchor,
                  units=5, deadline=date.today(), resource_kind="stock", product_id=product_id,
                  expires_at=datetime.now(timezone.utc) - timedelta(seconds=1))
    report = await reconcile_company(db_session, company_id=company)
    assert any(issue["code"] == "expired_hold" for issue in report["issues"])
    assert await sweep_expired_holds(db_session, company_id=company) == 1
    assert await sweep_expired_holds(db_session, company_id=company) == 0
    report = await reconcile_company(db_session, company_id=company)
    assert not any(issue["code"] == "expired_hold" for issue in report["issues"])
    with pytest.raises(HTTPException):
        await activate_hold(db_session, company_id=company, anchor_id=anchor, units=1)


@pytest.mark.asyncio
async def test_return_requires_quality_decision(warehouse, db_session):
    _, company, product_id = warehouse
    with pytest.raises(HTTPException) as exc:
        await return_stock(db_session, company_id=company, product_id=product_id, units=3, quality_accepted=False)
    assert exc.value.status_code == 409
    product = await db_session.get(Product, product_id)
    assert product.stock_units == 10
    with pytest.raises(HTTPException) as exc:
        await return_stock(db_session, company_id=company, product_id=product_id, units=3, quality_accepted=True)
    assert exc.value.status_code == 409
    assert product.stock_units == 10
    with pytest.raises(HTTPException):
        await return_stock(db_session, company_id=company, product_id=product_id, units=0, quality_accepted=True)


@pytest.mark.asyncio
async def test_reconcile_detects_company_mismatch(warehouse, db_session):
    _, company, product_id = warehouse
    stranger = await make_user(db_session)
    other_company = await make_company(db_session, stranger, can_buy=False)
    db_session.add(ResourceReservation(
        company_id=other_company, product_id=product_id, anchor_type="deal",
        anchor_id=uuid.uuid4(), units=1, status="committed",
    ))
    await db_session.commit()
    report = await reconcile_company(db_session, company_id=other_company)
    assert any(issue["code"] == "orphan_reservation" for issue in report["issues"])


@pytest.mark.asyncio
async def test_repair_endpoint_sweeps_and_audits(warehouse, db_session, client):
    user, company, product_id = warehouse
    anchor = uuid.uuid4()
    await reserve(db_session, company_id=company, anchor_type="reserve", anchor_id=anchor,
                  units=4, deadline=date.today(), resource_kind="stock", product_id=product_id,
                  expires_at=datetime.now(timezone.utc) - timedelta(seconds=1))
    await db_session.commit()
    headers = {"Authorization": f"Bearer {make_token(user)}"}
    before = await client.get(f"/api/v1/companies/{company}/resources/reconciliation", headers=headers)
    assert before.status_code == 200, before.text
    assert any(issue["code"] == "expired_hold" for issue in before.json()["issues"])
    repair = await client.post(f"/api/v1/companies/{company}/resources/repair", headers=headers)
    assert repair.status_code == 200, repair.text
    assert repair.json()["swept"] == 1
    again = await client.post(f"/api/v1/companies/{company}/resources/repair", headers=headers)
    assert again.status_code == 200, again.text
    assert again.json()["swept"] == 0
    assert not any(issue["code"] == "expired_hold" for issue in again.json()["remaining_issues"])
    from app.models import HumanApprovalRecord
    audits = (await db_session.scalars(
        select(HumanApprovalRecord).where(HumanApprovalRecord.action == "resource_repair")
    )).all()
    assert len(audits) == 2


@pytest.mark.asyncio
async def test_consume_does_not_double_spend(warehouse, db_session):
    _, company, product_id = warehouse
    anchor = uuid.uuid4()
    await reserve(db_session, company_id=company, anchor_type="deal", anchor_id=anchor,
                  units=6, deadline=date.today(), resource_kind="stock", product_id=product_id)
    await consume(db_session, company_id=company, anchor_type="deal", anchor_id=anchor)
    await consume(db_session, company_id=company, anchor_type="deal", anchor_id=anchor)
    product = await db_session.get(Product, product_id)
    assert product.stock_units == 4


@pytest.mark.asyncio
async def test_stale_stock_read_cannot_oversell(warehouse, db_session, session_factory):
    """P1: предчтение остатка → чужая отгрузка → новое обязательство даёт 409."""
    _, company, product_id = warehouse
    stale = await db_session.get(Product, product_id)
    assert stale.stock_units == 10
    stranger = uuid.uuid4()
    async with session_factory() as other:
        await reserve(other, company_id=company, anchor_type="deal", anchor_id=stranger,
                      units=7, deadline=date.today(), resource_kind="stock", product_id=product_id)
        await consume(other, company_id=company, anchor_type="deal", anchor_id=stranger)
        await other.commit()
    with pytest.raises(HTTPException) as exc:
        await reserve(db_session, company_id=company, anchor_type="deal", anchor_id=uuid.uuid4(),
                      units=7, deadline=date.today(), resource_kind="stock", product_id=product_id)
    assert exc.value.status_code == 409
    await db_session.rollback()


@pytest.mark.asyncio
async def test_multiday_allocation_is_not_duplicate(warehouse, db_session):
    """P2: заказ 5+5 по двум дням — нормальное распределение, не дубль."""
    _, company, _ = warehouse
    day1 = date.today() + timedelta(days=1)
    day2 = date.today() + timedelta(days=2)
    await grant_capacity(db_session, company, 5, day1)
    await grant_capacity(db_session, company, 5, day2)
    await reserve(db_session, company_id=company, anchor_type="deal", anchor_id=uuid.uuid4(),
                  units=10, deadline=day2, category="Упаковка и тара", subcategory="Бумажные стаканы")
    await db_session.commit()
    report = await reconcile_company(db_session, company_id=company)
    assert not any(issue["code"] == "duplicate_anchor" for issue in report["issues"])


@pytest.mark.asyncio
async def test_same_resource_twice_is_rejected(warehouse, db_session):
    """Дубль одного ресурса под одним основанием запрещён уже ограничением БД."""
    from sqlalchemy.exc import IntegrityError
    _, company, product_id = warehouse
    anchor = uuid.uuid4()
    await reserve(db_session, company_id=company, anchor_type="deal", anchor_id=anchor,
                  units=2, deadline=date.today(), resource_kind="stock", product_id=product_id)
    await db_session.commit()
    db_session.add(ResourceReservation(company_id=company, product_id=product_id,
                                       anchor_type="deal", anchor_id=anchor, units=2, status="committed"))
    with pytest.raises(IntegrityError):
        await db_session.commit()
    await db_session.rollback()
    report = await reconcile_company(db_session, company_id=company)
    assert not any(issue["code"] == "duplicate_anchor" for issue in report["issues"])


@pytest.mark.asyncio
async def test_orphan_business_anchor_per_type(warehouse, db_session):
    """P2: активные записи без сущности deal/coalition/reserve/resilience_primary выявляются."""
    _, company, product_id = warehouse
    for anchor_type in ("deal", "coalition", "reserve", "resilience_primary"):
        await reserve(db_session, company_id=company, anchor_type=anchor_type, anchor_id=uuid.uuid4(),
                      units=1, deadline=date.today(), resource_kind="stock", product_id=product_id)
    await db_session.commit()
    report = await reconcile_company(db_session, company_id=company)
    orphans = [issue for issue in report["issues"] if issue["code"] == "orphan_anchor"]
    assert {issue["anchor_type"] for issue in orphans} == {"deal", "coalition", "reserve", "resilience_primary"}
    assert all(obligation["business_exists"] is False for obligation in report["obligations"])


@pytest.mark.asyncio
async def test_cancelled_deal_is_stale_obligation(db_session):
    """Отменённая сделка с активными удержаниями — stale, а не молча занятый ресурс."""
    from app.models import Deal, DeliveryAddress, Need, Offer
    buyer = await make_user(db_session)
    seller = await make_user(db_session)
    bc = await make_company(db_session, buyer, can_sell=False)
    sc = await make_company(db_session, seller, can_buy=False)
    address = DeliveryAddress(company_id=bc, address="г. Москва, ул. Синтетическая, д. 1", city="Москва", region="Москва")
    db_session.add(address)
    await db_session.flush()
    product = Product(company_id=sc, name="Стол", category="Мебель", characteristics={}, price_rub=1000,
                      price_tiers=[], moq_units=1, lead_time_days=1, stock_units=10,
                      stock_updated_at=datetime.now(timezone.utc))
    db_session.add(product)
    await db_session.flush()
    need = Need(company_id=bc, created_by_user_id=buyer, category="Мебель", characteristics={}, volume_units=5,
                budget_rub=20000, deadline_date=date.today() + timedelta(days=20),
                delivery_address_id=address.id, visibility="public", status="matched")
    db_session.add(need)
    await db_session.flush()
    offer = Offer(need_id=need.id, company_id=sc, created_by_user_id=seller, price_rub=1000,
                  available_units=5, lead_time_days=2, delivery_cost_rub=0, moq_units=1,
                  price_tiers=[], status="selected", product_id=product.id)
    db_session.add(offer)
    await db_session.flush()
    deal = Deal(offer_id=offer.id, need_id=need.id, buyer_company_id=bc, seller_company_id=sc,
                units=5, total_price_rub=5000, status="cancelled")
    db_session.add(deal)
    await db_session.flush()
    await reserve(db_session, company_id=sc, anchor_type="deal", anchor_id=deal.id,
                  units=5, deadline=date.today(), resource_kind="stock", product_id=product.id)
    await db_session.commit()
    report = await reconcile_company(db_session, company_id=sc)
    assert any(issue["code"] == "stale_obligation" for issue in report["issues"])
    obligation = next(item for item in report["obligations"] if item["anchor_type"] == "deal")
    assert obligation["business_exists"] is True
    assert obligation["business_status"] == "cancelled"


@pytest.mark.asyncio
async def test_partial_consume_stock_and_capacity(warehouse, db_session):
    _, company, product_id = warehouse
    anchor = uuid.uuid4()
    await reserve(db_session, company_id=company, anchor_type="deal", anchor_id=anchor,
                  units=10, deadline=date.today(), resource_kind="stock", product_id=product_id)
    await db_session.commit()
    assert await consume(db_session, company_id=company, anchor_type="deal", anchor_id=anchor, units=4) == 4
    await db_session.commit()
    product = await db_session.get(Product, product_id)
    assert product.stock_units == 6
    with pytest.raises(HTTPException):
        await consume(db_session, company_id=company, anchor_type="deal", anchor_id=anchor, units=7)
    assert await consume(db_session, company_id=company, anchor_type="deal", anchor_id=anchor) == 6
    await db_session.commit()
    product = await db_session.get(Product, product_id)
    assert product.stock_units == 0

    day = date.today() + timedelta(days=3)
    await grant_capacity(db_session, company, 10, day)
    await db_session.commit()
    cap_anchor = uuid.uuid4()
    await reserve(db_session, company_id=company, anchor_type="coalition", anchor_id=cap_anchor,
                  units=10, deadline=day, category="Упаковка и тара", subcategory="Бумажные стаканы")
    assert await consume(db_session, company_id=company, anchor_type="coalition", anchor_id=cap_anchor, units=4) == 4
    from app.models import CapacityEntry
    from app.resources import free_capacity_for_entry
    entry = (await db_session.scalars(select(CapacityEntry).where(CapacityEntry.company_id == company))).first()
    assert entry.available_units == 6
    assert await free_capacity_for_entry(db_session, entry) == 0


@pytest.mark.asyncio
async def test_capacity_overlap_guard_rejects_double_counting(warehouse, client):
    user, company, _ = warehouse
    headers = {"Authorization": f"Bearer {make_token(user)}"}
    day = str(date.today() + timedelta(days=4))
    response = await client.put(f"/api/v1/companies/{company}/capacity", headers=headers, json={"entries": [
        {"date": day, "available_units": 5},
        {"date": day, "category": "business-supplies.furniture", "unit": "шт", "available_units": 5},
    ]})
    assert response.status_code == 422, response.text


@pytest.mark.asyncio
async def test_return_restock_requires_confirmed_event_and_is_idempotent(client, db_session):
    """S06.03: возврат на склад — только по подтверждённому событию, повтор не начисляет."""
    from decimal import Decimal
    from app.models import Deal, DealCheckpoint, DeliveryAddress, Need, Offer
    buyer = await make_user(db_session)
    seller = await make_user(db_session)
    bc = await make_company(db_session, buyer, can_sell=False)
    sc = await make_company(db_session, seller, can_buy=False)
    address = DeliveryAddress(company_id=bc, address="г. Москва, ул. Синтетическая, д. 1", city="Москва", region="Москва")
    db_session.add(address)
    await db_session.flush()
    product = Product(company_id=sc, name="Стол", category="Мебель", characteristics={}, price_rub=1000,
                      price_tiers=[], moq_units=1, lead_time_days=1, stock_units=10,
                      stock_updated_at=datetime.now(timezone.utc))
    db_session.add(product)
    await db_session.flush()
    need = Need(company_id=bc, created_by_user_id=buyer, category="Мебель", characteristics={}, volume_units=10,
                budget_rub=20000, deadline_date=date.today() + timedelta(days=20),
                delivery_address_id=address.id, visibility="public", status="matched")
    db_session.add(need)
    await db_session.flush()
    offer = Offer(need_id=need.id, company_id=sc, created_by_user_id=seller, price_rub=1000,
                  available_units=10, lead_time_days=2, delivery_cost_rub=0, moq_units=1,
                  price_tiers=[], status="selected", product_id=product.id)
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
    await reserve(db_session, company_id=sc, anchor_type="deal", anchor_id=deal.id,
                  units=10, deadline=date.today(), resource_kind="stock", product_id=product.id)
    await consume(db_session, company_id=sc, anchor_type="deal", anchor_id=deal.id)
    await db_session.commit()
    assert (await db_session.get(Product, product.id)).stock_units == 0

    buyer_headers = {"Authorization": f"Bearer {make_token(buyer)}"}
    seller_headers = {"Authorization": f"Bearer {make_token(seller)}"}
    accepted = await client.post(f"/api/v1/deals/{deal.id}/execution", headers=buyer_headers, json={
        "company_id": str(bc), "kind": "acceptance", "units": 10, "note": "Принято по акту",
        "human_approved": True, "idempotency_key": str(uuid.uuid4()),
    })
    assert accepted.status_code == 201, accepted.text
    created = await client.post(f"/api/v1/deals/{deal.id}/execution", headers=buyer_headers, json={
        "company_id": str(bc), "kind": "return", "units": 3, "note": "Бой при перевозке",
        "human_approved": True, "idempotency_key": str(uuid.uuid4()),
    })
    assert created.status_code == 201, created.text
    event_id = created.json()["id"]
    restock = await client.post(f"/api/v1/deals/{deal.id}/execution/{event_id}/decision", headers=seller_headers,
                                json={"company_id": str(sc), "approved": True, "human_approved": True,
                                      "restock_accepted": True})
    assert restock.status_code == 200, restock.text
    await db_session.refresh(product)
    assert product.stock_units == 3
    repeat = await client.post(f"/api/v1/deals/{deal.id}/execution/{event_id}/decision", headers=seller_headers,
                               json={"company_id": str(sc), "approved": True, "human_approved": True,
                                     "restock_accepted": True})
    assert repeat.status_code == 200, repeat.text
    await db_session.refresh(product)
    assert product.stock_units == 3
    second = await client.post(f"/api/v1/deals/{deal.id}/execution", headers=buyer_headers, json={
        "company_id": str(bc), "kind": "return", "units": 2, "note": "Царапины на корпусе",
        "human_approved": True, "idempotency_key": str(uuid.uuid4()),
    })
    assert second.status_code == 201, second.text
    written_off = await client.post(f"/api/v1/deals/{deal.id}/execution/{second.json()['id']}/decision",
                                    headers=seller_headers,
                                    json={"company_id": str(sc), "approved": True, "human_approved": True})
    assert written_off.status_code == 200, written_off.text
    await db_session.refresh(product)
    assert product.stock_units == 3


@pytest.mark.asyncio
@pytest.mark.parametrize("path", ["full", "partial_then_full", "partial_then_cancel"])
async def test_capacity_consumption_preserves_resource_units(warehouse, db_session, path):
    from app.resources import free_capacity_for_entry
    _, company, _ = warehouse
    day = date.today() + timedelta(days=1)
    entry = CapacityEntry(company_id=company, date=day, unit="мин", available_units=20,
                          category_conversions=prepare_conversions([{
                              "category_id": "business-supplies.furniture", "order_unit": "шт",
                              "resource_units_per_order_unit": 3,
                          }], True))
    db_session.add(entry)
    await db_session.commit()
    anchor = uuid.uuid4()
    await reserve(db_session, company_id=company, anchor_type="deal", anchor_id=anchor,
                  units=4, deadline=day, category="Мебель")
    if path == "full":
        assert await consume(db_session, company_id=company, anchor_type="deal", anchor_id=anchor) == 4
        assert entry.available_units == 20
    else:
        assert await consume(db_session, company_id=company, anchor_type="deal", anchor_id=anchor, units=1) == 1
        assert entry.available_units == 17
        assert await free_capacity_for_entry(db_session, entry) == 8
        if path == "partial_then_full":
            assert await consume(db_session, company_id=company, anchor_type="deal", anchor_id=anchor) == 3
        else:
            assert await release(db_session, company_id=company, anchor_type="deal", anchor_id=anchor) == 3
    await db_session.commit()
    expected_free = 17 if path == "partial_then_cancel" else 8
    assert await free_capacity_for_entry(db_session, entry) == expected_free
    assert not any(issue["code"] == "negative_capacity" for issue in (await reconcile_company(db_session, company_id=company))["issues"])
    assert await consume(db_session, company_id=company, anchor_type="deal", anchor_id=anchor) == 0
    assert await free_capacity_for_entry(db_session, entry) == expected_free
    with pytest.raises(HTTPException) as exc:
        await reserve(db_session, company_id=company, anchor_type="reserve", anchor_id=uuid.uuid4(),
                      units=expected_free // 3 + 1, deadline=day, category="Мебель")
    assert exc.value.status_code == 409


@pytest.mark.asyncio
async def test_capacity_is_reloaded_after_calendar_change(warehouse, db_session, session_factory):
    from app.resources import lock_company
    _, company, _ = warehouse
    day = date.today() + timedelta(days=1)
    await grant_capacity(db_session, company, 10, day)
    entry = (await db_session.scalars(select(CapacityEntry).where(CapacityEntry.company_id == company))).one()
    async with session_factory() as other:
        await lock_company(other, company)
        current = await other.get(CapacityEntry, entry.id)
        current.available_units = 3
        await other.commit()
    with pytest.raises(HTTPException) as exc:
        await reserve(db_session, company_id=company, anchor_type="deal", anchor_id=uuid.uuid4(),
                      units=7, deadline=day, category="Упаковка и тара", subcategory="Бумажные стаканы")
    assert exc.value.status_code == 409


@pytest.mark.asyncio
async def test_overlap_is_checked_against_saved_calendar(warehouse, client):
    user, company, _ = warehouse
    headers = {"Authorization": f"Bearer {make_token(user)}"}
    day = str(date.today() + timedelta(days=1))
    shared = {"date": day, "unit": "мин", "available_units": 10, "conversions_approved": True,
              "category_conversions": [{"category_id": "business-supplies.furniture",
                                        "order_unit": "шт", "resource_units_per_order_unit": 3}]}
    endpoint = f"/api/v1/companies/{company}/capacity"
    assert (await client.put(endpoint, headers=headers, json={"entries": [shared]})).status_code == 200
    response = await client.put(endpoint, headers=headers, json={"entries": [
        {"date": day, "category": "business-supplies.furniture", "unit": "шт", "available_units": 5},
    ]})
    assert response.status_code == 422, response.text
    shared["available_units"] = 12
    assert (await client.put(endpoint, headers=headers, json={"entries": [shared]})).status_code == 200
    rows = (await client.get(endpoint, headers=headers)).json()
    assert len(rows) == 1 and rows[0]["available_units"] == 12


@pytest.fixture
async def shipped_stock_return(order, client, db_session, request):
    deal_id, buyer, seller, buyer_headers, seller_headers = order
    product = Product(company_id=seller, name="Стол", category="Мебель", characteristics={},
                      price_rub=1000, price_tiers=[], moq_units=1, lead_time_days=1,
                      stock_units=10, stock_updated_at=datetime.now(timezone.utc))
    db_session.add(product)
    await db_session.flush()
    deal = await db_session.get(Deal, deal_id)
    offer = await db_session.get(Offer, deal.offer_id)
    offer.product_id, offer.resource_kind = product.id, "stock"
    await reserve(db_session, company_id=seller, anchor_type="deal", anchor_id=deal_id,
                  units=10, deadline=date.today(), resource_kind="stock", product_id=product.id)
    partial = getattr(request, "param", False)
    if partial:
        await consume(db_session, company_id=seller, anchor_type="deal", anchor_id=deal_id, units=4)
    await consume(db_session, company_id=seller, anchor_type="deal", anchor_id=deal_id)
    await db_session.commit()
    endpoint = f"/api/v1/deals/{deal_id}/execution"
    payload = {"company_id": str(buyer), "kind": "acceptance", "units": 10,
               "note": "Принято по акту", "human_approved": True, "idempotency_key": str(uuid.uuid4())}
    assert (await client.post(endpoint, headers=buyer_headers, json=payload)).status_code == 201
    payload.update(kind="return", units=10 if partial else 3, idempotency_key=str(uuid.uuid4()))
    response = await client.post(endpoint, headers=buyer_headers, json=payload)
    assert response.status_code == 201, response.text
    return deal, offer, product, uuid.UUID(response.json()["id"]), seller_headers


@pytest.mark.asyncio
async def test_return_uses_shipped_product_and_preserves_quality_decision(shipped_stock_return, client, db_session):
    deal, offer, original, event_id, headers = shipped_stock_return
    changed = Product(company_id=deal.seller_company_id, name="Другой стол", category="Мебель",
                      characteristics={}, price_rub=1000, price_tiers=[], moq_units=1, lead_time_days=1, stock_units=20)
    db_session.add(changed)
    await db_session.flush()
    offer.product_id = changed.id
    await db_session.commit()
    endpoint = f"/api/v1/deals/{deal.id}/execution/{event_id}/decision"
    payload = {"company_id": str(deal.seller_company_id), "approved": True,
               "human_approved": True, "restock_accepted": True}
    response = await client.post(endpoint, headers=headers, json=payload)
    assert response.status_code == 200, response.text
    assert (await client.post(endpoint, headers=headers, json=payload)).status_code == 200
    payload["restock_accepted"] = False
    assert (await client.post(endpoint, headers=headers, json=payload)).status_code == 409
    await db_session.refresh(original)
    await db_session.refresh(changed)
    assert original.stock_units == 3 and changed.stock_units == 20


@pytest.mark.asyncio
async def test_return_event_cannot_credit_other_company(shipped_stock_return, warehouse, client, db_session):
    deal, _, _, event_id, headers = shipped_stock_return
    _, company, product_id = warehouse
    endpoint = f"/api/v1/deals/{deal.id}/execution/{event_id}/decision"
    response = await client.post(endpoint, headers=headers, json={
        "company_id": str(deal.seller_company_id), "approved": True, "human_approved": True,
    })
    assert response.status_code == 200, response.text
    with pytest.raises(HTTPException) as exc:
        await return_stock(db_session, company_id=company, product_id=product_id,
                           units=3, quality_accepted=True, return_event_id=event_id)
    assert exc.value.status_code == 409
    product = await db_session.get(Product, product_id)
    assert product.stock_units == 10


@pytest.mark.asyncio
async def test_reconciliation_hides_foreign_business_anchor(warehouse, order, db_session):
    _, company, product_id = warehouse
    deal_id, _, _, _, _ = order
    await reserve(db_session, company_id=company, anchor_type="deal", anchor_id=deal_id,
                  units=1, deadline=date.today(), resource_kind="stock", product_id=product_id)
    await db_session.commit()
    report = await reconcile_company(db_session, company_id=company)
    assert any(issue["code"] == "foreign_anchor" for issue in report["issues"])
    obligation = report["obligations"][0]
    assert obligation["business_status"] is None and obligation["business_version"] is None


@pytest.mark.asyncio
@pytest.mark.parametrize("shipped_stock_return", [True], indirect=True)
async def test_return_keeps_entire_partial_shipment_history(shipped_stock_return, client, db_session):
    from app.models import TrustAuditEvent
    deal, _, product, event_id, headers = shipped_stock_return
    response = await client.post(f"/api/v1/deals/{deal.id}/execution/{event_id}/decision", headers=headers, json={
        "company_id": str(deal.seller_company_id), "approved": True,
        "human_approved": True, "restock_accepted": True,
    })
    assert response.status_code == 200, response.text
    await db_session.refresh(product)
    assert product.stock_units == 10
    events = (await db_session.scalars(select(TrustAuditEvent).where(
        TrustAuditEvent.event_type == "resource_consumed",
        TrustAuditEvent.payload["anchor_id"].astext == str(deal.id),
    ))).all()
    assert sorted(event.payload["units"] for event in events) == [4, 6]


@pytest.mark.asyncio
async def test_return_rejects_changed_stock_unit(shipped_stock_return, client, db_session):
    deal, _, product, event_id, headers = shipped_stock_return
    deal.commercial_snapshot = {"need": {"characteristics": {"unit": "шт"}}}
    product.characteristics = {"unit": "кг"}
    product.stock_units = 5
    await db_session.commit()
    response = await client.post(f"/api/v1/deals/{deal.id}/execution/{event_id}/decision", headers=headers, json={
        "company_id": str(deal.seller_company_id), "approved": True,
        "human_approved": True, "restock_accepted": True,
    })
    assert response.status_code == 409, response.text
    await db_session.refresh(product)
    assert product.stock_units == 5
