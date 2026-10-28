"""Public popularity uses confirmed net purchases, never units or provisional orders."""
import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import pytest
from sqlalchemy import select, text

from app.models import Deal, DealExecutionEvent, DeliveryAddress, Need, Offer, Product, ProductImage
from conftest import grant_packaging_documents, make_company, make_token, make_user


@pytest.fixture
async def catalogue(client, db_session):
    seller = await make_user(db_session)
    sc = await make_company(db_session, seller, can_buy=False, can_sell=True)
    buyer = await make_user(db_session)
    bc = await make_company(db_session, buyer, can_buy=True, can_sell=False)
    await grant_packaging_documents(db_session, sc, decision_user_id=seller,
                                   confirms={"material": ["крафт-картон"]})
    address = DeliveryAddress(company_id=bc, address="г. Москва, ул. Синтетическая, д. 1", city="Москва", region="Москва")
    db_session.add(address)
    await db_session.flush()
    products = []
    headers = {"Authorization": "Bearer " + make_token(seller)}
    for i in range(3):
        response = await client.post(f"/api/v1/companies/{sc}/products", headers=headers, json={
            "name": f"Стакан {400+i} мл", "category": "бумажные стаканы",
            "characteristics": {"volume_ml": 400+i, "material": "крафт-картон"},
            "price_rub": "10.00", "moq_units": 1, "lead_time_days": 2,
        })
        assert response.status_code == 201, response.text
        pid = uuid.UUID(response.json()["id"])
        response = await client.post(f"/api/v1/products/{pid}/publish", headers=headers, json={"published": True})
        assert response.status_code == 200, response.text
        product = await db_session.get(Product, pid)
        product.created_at = datetime(2025, 1, 1, tzinfo=timezone.utc) + timedelta(days=i)
        products.append(product)
    await db_session.commit()

    async def purchase(index, events, *, need=None, status="fulfilled", units=100):
        if need is None:
            need = Need(company_id=bc, created_by_user_id=buyer, category=products[index].category,
                        characteristics={}, volume_units=units, deadline_date=date.today()+timedelta(days=30),
                        delivery_address_id=address.id, visibility="open_anonymized", status="matched")
            db_session.add(need)
            await db_session.flush()
        offer = Offer(need_id=need.id, company_id=sc, created_by_user_id=seller, product_id=products[index].id,
                      price_rub=Decimal("10"), available_units=units, lead_time_days=2, delivery_cost_rub=0,
                      moq_units=1, price_tiers=[], status="selected")
        db_session.add(offer)
        await db_session.flush()
        deal = Deal(offer_id=offer.id, need_id=need.id, buyer_company_id=bc, seller_company_id=sc,
                    performed_by_user_id=buyer, units=units, total_price_rub=Decimal(10)*units,
                    unit_price_rub=10, delivery_price_rub=0, status=status, execution_contract="execution-v1")
        db_session.add(deal)
        await db_session.flush()
        for kind, amount, event_status in events:
            db_session.add(DealExecutionEvent(deal_id=deal.id, actor_company_id=bc, actor_user_id=buyer,
                idempotency_key=uuid.uuid4(), kind=kind, units=amount, note="Синтетический акт",
                status=event_status, decided_by_user_id=buyer))
        await db_session.commit()
        return need

    return products, purchase, sc


async def test_popularity_counts_distinct_net_purchases_not_volume_or_order_status(client, db_session, catalogue):
    products, purchase, _ = catalogue
    # A large one-off order has one purchase. Split receipt events do not multiply it.
    await purchase(0, [("acceptance", 400, "confirmed"), ("acceptance", 600, "confirmed")], units=1000)
    need = await purchase(1, [("acceptance", 10, "confirmed"), ("return", 2, "confirmed")])
    await purchase(1, [("acceptance", 5, "confirmed")], need=need)  # same procurement still counts once
    await purchase(1, [("acceptance", 1, "confirmed")])  # second distinct procurement ranks first
    for _ in range(4):
        await purchase(2, [("acceptance", 10, "confirmed"), ("return", 10, "confirmed")], status="returned")
        await purchase(2, [("acceptance", 100, "pending")], status="created")
        await purchase(2, [("shipment", 100, "confirmed")], status="shipped")
        await purchase(2, [("cancellation", 100, "confirmed")], status="cancelled")
    ranked = await client.get("/api/v1/products?sort=popular")
    assert ranked.status_code == 200, ranked.text
    assert [x["id"] for x in ranked.json()] == [str(products[i].id) for i in [1, 0, 2]]
    assert all("purchases" not in x and "popularity" not in x for x in ranked.json())
    # A subsequent full return removes the second product's lead without changing the deal manually.
    deals = (await db_session.scalars(select(Deal).join(Offer, Deal.offer_id == Offer.id)
        .where(Offer.product_id == products[1].id))).all()
    for deal in deals:
        events = (await db_session.scalars(select(DealExecutionEvent)
            .where(DealExecutionEvent.deal_id == deal.id))).all()
        remaining = sum(e.units if e.kind == "acceptance" else -e.units
                        for e in events if e.status == "confirmed" and e.kind in {"acceptance", "return"})
        db_session.add(DealExecutionEvent(deal_id=deal.id, actor_company_id=deal.buyer_company_id,
            actor_user_id=deal.performed_by_user_id, idempotency_key=uuid.uuid4(), kind="return",
            units=remaining, note="Синтетический полный возврат", status="confirmed"))
    await db_session.commit()
    reranked = await client.get("/api/v1/products?sort=popular")
    assert [x["id"] for x in reranked.json()] == [str(products[i].id) for i in [0, 2, 1]]
    legacy = await client.get("/api/v1/products")
    assert [x["id"] for x in legacy.json()] == [str(products[i].id) for i in [2, 1, 0]]
    assert (await client.get("/api/v1/products?sort=unknown")).status_code == 422


async def test_popularity_ties_prefer_images_then_stable_catalogue_order(client, db_session, catalogue):
    products, _, _ = catalogue
    db_session.add(ProductImage(product_id=products[0].id, file_name="Синтетический стакан.webp",
        content_type="image/webp", file_key="synthetic/catalogue/cup.webp", position=0))
    await db_session.commit()
    first = (await client.get("/api/v1/products?sort=popular")).json()
    second = (await client.get("/api/v1/products?sort=popular")).json()
    assert [p["id"] for p in first] == [str(products[i].id) for i in [0, 2, 1]]
    assert [p["id"] for p in second] == [p["id"] for p in first]


async def test_popularity_does_not_bypass_publication_or_company_admission(client, db_session, catalogue):
    products, purchase, sc = catalogue
    await purchase(0, [("acceptance", 10, "confirmed")])
    products[0].is_published = False
    await db_session.commit()
    assert str(products[0].id) not in [p["id"] for p in (await client.get("/api/v1/products?sort=popular")).json()]
    await db_session.execute(text("UPDATE auth.companies SET verification_status='rejected' WHERE id=:id"), {"id":sc})
    await db_session.commit()
    assert (await client.get("/api/v1/products?sort=popular")).json() == []


async def test_catalogue_query_count_does_not_grow_per_product(client, db_session, catalogue, engine):
    from sqlalchemy import event
    products, _, seller = catalogue
    for index in range(47):
        db_session.add(Product(company_id=seller, name=f"Синтетический стакан {index}", category=products[0].category,
            characteristics=dict(products[0].characteristics), price_rub=10, moq_units=1,
            lead_time_days=2, is_published=True))
    await db_session.commit()
    queries = []
    def count(conn, cursor, statement, parameters, context, executemany):
        if statement.lstrip().upper().startswith('SELECT'): queries.append(statement)
    event.listen(engine.sync_engine, 'before_cursor_execute', count)
    try:
        response = await client.get('/api/v3/products?sort=popular')
    finally:
        event.remove(engine.sync_engine, 'before_cursor_execute', count)
    assert response.status_code == 200, response.text
    assert len(response.json()) == 50
    print(f"catalogue_select_queries={len(queries)}")
    assert len(queries) <= 6  # Constant query budget for 50 products, including current admission.
