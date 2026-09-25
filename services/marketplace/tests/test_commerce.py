import uuid
from datetime import date, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import select
from app.models import Deal, DealCheckpoint, DealExecutionEvent, DeliveryAddress, Need, Offer, Product
from conftest import make_company, make_token, make_user


@pytest.fixture
async def order(db_session):
    buyer = await make_user(db_session)
    seller = await make_user(db_session)
    bc = await make_company(db_session, buyer, can_sell=False)
    sc = await make_company(db_session, seller, can_buy=False)
    address = DeliveryAddress(company_id=bc, address="г. Москва, ул. Синтетическая, д. 1", city="Москва", region="Москва")
    db_session.add(address); await db_session.flush()
    need = Need(company_id=bc, created_by_user_id=buyer, category="Мебель", characteristics={}, volume_units=10,
                budget_rub=20000, deadline_date=date.today()+timedelta(days=20), delivery_address_id=address.id, visibility="public", status="matched")
    db_session.add(need); await db_session.flush()
    offer = Offer(need_id=need.id, company_id=sc, created_by_user_id=seller, price_rub=1000,
                  available_units=10, lead_time_days=2, delivery_cost_rub=0, moq_units=1, price_tiers=[], status="selected")
    db_session.add(offer); await db_session.flush()
    deal = Deal(offer_id=offer.id, need_id=need.id, buyer_company_id=bc, seller_company_id=sc,
                units=10, total_price_rub=10000, unit_price_rub=Decimal("1000"), delivery_price_rub=0, status="shipped")
    db_session.add(deal); await db_session.flush()
    for kind in ("production", "shipment"):
        db_session.add(DealCheckpoint(deal_id=deal.id, kind=kind, status="completed"))
    await db_session.commit()
    return deal.id, bc, sc, {"Authorization": f"Bearer {make_token(buyer)}"}, {"Authorization": f"Bearer {make_token(seller)}"}


async def event(client, order, kind, units, **overrides):
    deal, buyer, seller, bh, sh = order
    payload = {"company_id": str(buyer), "kind": kind, "units": units, "note": "Подтверждение по акту", "human_approved": True, "idempotency_key": str(uuid.uuid4()), **overrides}
    return await client.post(f"/api/v1/deals/{deal}/execution", headers=bh, json=payload)


async def decision(client, order, event_id, approved=True):
    deal, buyer, seller, bh, sh = order
    return await client.post(f"/api/v1/deals/{deal}/execution/{event_id}/decision", headers=sh,
                            json={"company_id": str(seller), "approved": approved, "human_approved": True})


@pytest.mark.asyncio
async def test_control_example_partial_delivery_return_profit_and_privacy(client, order):
    deal, buyer, seller, bh, sh = order
    assert (await event(client, order, "acceptance", 6)).status_code == 201
    request = await event(client, order, "return", 1)
    assert request.status_code == 201
    assert (await decision(client, order, request.json()["id"])).status_code == 200
    cost = await client.put(f"/api/v1/deals/{deal}/costs", headers=sh, json={"company_id": str(seller), "expected_revision": 0,
        "unit_cost_rub": "600.00", "attributable_expenses_rub": "200.00", "note": "Учётные затраты продавца", "human_approved": True})
    assert cost.status_code == 200, cost.text
    report = (await client.get(f"/api/v1/companies/{seller}/commercial-analytics?role=seller", headers=sh)).json()
    row = report["orders"][0]
    assert row["unit"] == "шт"
    assert (row["ordered_units"], row["accepted_units"], row["returned_units"], row["net_units"], row["open_units"]) == (10, 6, 1, 5, 4)
    for key, value in {"net_goods_revenue_rub":5000, "cost_of_goods_rub":3000, "gross_profit_rub":2000, "contribution_rub":1800}.items():
        assert Decimal(str(row[key])) == value
    assert row["payments_rub"] is None
    bv = (await client.get(f"/api/v1/deals/{deal}/execution?company_id={buyer}", headers=bh)).json()
    assert "cost_revision" not in bv and "cost_of_goods_rub" not in bv["financials"]
    br = (await client.get(f"/api/v1/companies/{buyer}/commercial-analytics?role=buyer", headers=bh)).json()
    assert "gross_profit_rub" not in br["orders"][0]
    assert (await client.get(f"/api/v1/companies/{seller}/commercial-analytics?role=seller", headers=bh)).status_code == 404
    assert (await client.patch(f"/api/v1/deals/{deal}/timeline/shipment", headers=sh, json={"company_id":str(seller),"completed":False,"human_approved":True})).status_code == 409


@pytest.mark.asyncio
async def test_idempotency_quantity_and_bilateral_decision(client, order, db_session):
    key = str(uuid.uuid4())
    first = await event(client, order, "acceptance", 6, idempotency_key=key)
    again = await event(client, order, "acceptance", 6, idempotency_key=key)
    assert first.json()["id"] == again.json()["id"]
    assert (await event(client, order, "acceptance", 7, idempotency_key=key)).status_code == 409
    assert (await event(client, order, "acceptance", 5)).status_code == 409
    pending = await event(client, order, "cancellation", 4)
    deal, buyer, seller, bh, sh = order
    own = await client.post(f"/api/v1/deals/{deal}/execution/{pending.json()['id']}/decision", headers=bh,json={"company_id":str(buyer),"approved":True,"human_approved":True})
    assert own.status_code == 403
    assert (await decision(client, order, pending.json()["id"])).status_code == 200
    assert (await decision(client, order, pending.json()["id"])).status_code == 200
    assert (await decision(client, order, pending.json()["id"], False)).status_code == 409
    assert (await event(client, order, "return", 7)).status_code == 409
    state = (await client.get(f"/api/v1/deals/{deal}/execution?company_id={seller}", headers=sh)).json()
    assert state["open_units"] == 0 and state["status"] == "fulfilled"
    assert state["financials"]["gross_profit_rub"] is None
    assert len((await db_session.scalars(select(DealExecutionEvent))).all()) == 2


@pytest.mark.asyncio
async def test_pending_revalidation_and_cost_revision(client, order):
    one = await event(client, order, "cancellation", 8)
    two = await event(client, order, "cancellation", 8)
    assert (await decision(client, order, one.json()["id"])).status_code == 200
    assert (await decision(client, order, two.json()["id"])).status_code == 409
    deal, buyer, seller, bh, sh = order
    p = {"company_id":str(seller),"expected_revision":0,"unit_cost_rub":None,"attributable_expenses_rub":None,"note":"Пока не известны","human_approved":True}
    assert (await client.put(f"/api/v1/deals/{deal}/costs",headers=sh,json=p)).status_code == 200
    assert (await client.put(f"/api/v1/deals/{deal}/costs",headers=sh,json=p)).status_code == 409
    p.update(expected_revision=1, unit_cost_rub="NaN")
    assert (await client.put(f"/api/v1/deals/{deal}/costs",headers=sh,json=p)).status_code == 422


@pytest.mark.asyncio
async def test_product_patch_preserves_stock(client, order, db_session):
    _, _, seller, _, sh = order
    product = Product(company_id=seller,name="Стол рабочий",category="Мебель",characteristics={},price_rub=1000,price_tiers=[],moq_units=1,lead_time_days=1,stock_units=17,is_published=False)
    db_session.add(product); await db_session.commit()
    r = await client.patch(f"/api/v1/products/{product.id}",headers=sh,json={"name":"Стол письменный"})
    assert r.status_code == 200, r.text
    assert r.json()["stock_units"] == 17


@pytest.mark.asyncio
async def test_need_retry_and_file_retry_do_not_duplicate(client, order, db_session):
    _, buyer, _, bh, _ = order
    payload = {"request_key": str(uuid.uuid4()), "company_id": str(buyer), "category": "Мебель", "characteristics": {"material":"дерево"}, "volume_units":2,
               "deadline_date":(date.today()+timedelta(days=10)).isoformat(), "visibility":"closed"}
    first = await client.post("/api/v1/needs", headers=bh, json=payload)
    again = await client.post("/api/v1/needs", headers=bh, json=payload)
    assert first.status_code == 201, first.text
    assert first.json()["id"] == again.json()["id"]
    payload["volume_units"] = 3
    assert (await client.post("/api/v1/needs", headers=bh, json=payload)).status_code == 409
    url = f"/api/v1/needs/{first.json()['id']}/files"
    for _ in range(2):
        upload = await client.post(url, headers=bh, files={"file": ("условия.txt", b"Specification", "text/plain")})
        assert upload.status_code == 201, upload.text
        assert len(upload.json()["files"]) == 1
    publish = f"/api/v1/needs/{first.json()['id']}/publish"
    assert (await client.post(publish, headers=bh)).status_code == 200
    assert (await client.post(publish, headers=bh)).status_code == 200


@pytest.mark.asyncio
async def test_offer_revision_prevents_stale_purchase_and_update(client, order, db_session):
    deal_id, buyer, seller, bh, sh = order
    deal = await db_session.get(Deal, deal_id)
    offer = await db_session.get(Offer, deal.offer_id)
    need = await db_session.get(Need, deal.need_id)
    offer.status = "sent"; need.status = "open_for_offers"
    # Keep an existing deal to exercise repeat selection after the version checks.
    await db_session.commit()
    response = await client.patch(f"/api/v1/offers/{offer.id}", headers=sh, json={"expected_revision":1,"price_rub":1100})
    assert response.status_code == 200, response.text
    assert response.json()["revision"] == 2
    assert (await client.patch(f"/api/v1/offers/{offer.id}", headers=sh, json={"expected_revision":1,"price_rub":1200})).status_code == 409
    endpoint = f"/api/v1/offers/{offer.id}/select"
    assert (await client.post(endpoint, headers=bh)).status_code == 428
    assert (await client.post(endpoint, headers=bh, json={"expected_revision":1,"human_approved":True})).status_code == 409
    assert (await client.post(endpoint, headers=bh, json={"expected_revision":2,"human_approved":True})).json()["id"] == str(deal_id)


async def test_need_draft_edit_revision_and_publication_guard(client, db_session):
    from datetime import date, timedelta
    from conftest import make_user, make_company, make_token
    user = await make_user(db_session)
    company = await make_company(db_session, user, can_buy=True, can_sell=False)
    headers = {"Authorization": f"Bearer {make_token(user)}"}
    payload = {"company_id": str(company), "category": "Мебель", "characteristics": {"material": "дерево"},
               "volume_units": 30, "budget_rub": 300000, "deadline_date": str(date.today() + timedelta(days=20))}
    created = await client.post("/api/v1/needs", json=payload, headers=headers)
    assert created.status_code == 201, created.text
    path = f"/api/v1/needs/{created.json()['id']}"
    changed = await client.put(path, json={**payload, "volume_units": 40, "expected_revision": 1}, headers=headers)
    assert changed.status_code == 200, changed.text
    assert changed.json()["revision"] == 2
    assert changed.json()["volume_units"] == 40
    stale = await client.put(path, json={**payload, "expected_revision": 1}, headers=headers)
    assert stale.status_code == 409
    published = await client.post(path + "/publish", headers=headers)
    assert published.status_code == 200, published.text
    blocked = await client.put(path, json={**payload, "expected_revision": 2}, headers=headers)
    assert blocked.status_code == 409
