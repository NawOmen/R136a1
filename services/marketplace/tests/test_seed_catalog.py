"""Clean synthetic startup uses the same publication guards as the seller UI."""
from decimal import Decimal

import pytest
from sqlalchemy import select, text

import seed
from app.assortment import ASSORTMENT
from app.models import Document, Product, ProductPriceObservation, TrustAuditEvent
from conftest import make_company, make_marketplace_admin, make_user, make_token


async def seller_fixture(db, monkeypatch, *, verified=True, admin=True):
    monkeypatch.setenv("ENABLE_DEMO_SEED", "true")
    monkeypatch.setattr(seed, "SELLER_USER_EMAIL", "seller@demo.ru")
    if admin:
        await make_marketplace_admin(db)
    user = await make_user(db, "seller@demo.ru")
    company = await make_company(db, user, can_buy=False, verified=verified)
    await db.execute(text("UPDATE auth.companies SET display_name=:name WHERE id=:id"),
                     {"name": seed.SELLER_COMPANY_NAME, "id": company})
    await db.commit()
    return company


async def test_clean_seed_publishes_admitted_cups_and_preserves_rerun(client, db_session, session_factory, monkeypatch):
    company = await seller_fixture(db_session, monkeypatch)
    monkeypatch.setattr(seed, "SessionLocal", session_factory)
    await seed.seed()
    response = await client.get("/api/v3/products")
    assert response.status_code == 200, response.text
    catalog = response.json()
    assert {item["name"] for item in catalog} == {"Стакан 400 мл PE", "Стакан 350 мл PE"}
    assert {Decimal(item["price_rub"]) for item in catalog} == {Decimal("11.2"), Decimal("10.5")}
    products = (await db_session.scalars(select(Product).where(Product.company_id == company))).all()
    assert len(products) == 2 + len(ASSORTMENT)
    assert sum(product.is_published for product in products) == 2
    assert len((await db_session.scalars(select(ProductPriceObservation))).all()) == 2
    events = (await db_session.scalars(select(TrustAuditEvent).where(
        TrustAuditEvent.event_type == "product_published_with_admission"))).all()
    assert len(events) == 2

    # A seller's subsequent unpublication/stock/price edits survive repeat seed.
    cups = [product for product in products if product.is_published]
    for cup in cups:
        cup.is_published = False
        cup.price_rub = Decimal("12.34")
        cup.stock_units = 7
    await db_session.commit()
    await seed.seed()
    assert (await client.get("/api/v3/products")).json() == []
    await db_session.refresh(cups[0])
    assert cups[0].price_rub == Decimal("12.34") and cups[0].stock_units == 7
    assert len((await db_session.scalars(select(Product))).all()) == 2 + len(ASSORTMENT)
    assert len((await db_session.scalars(select(ProductPriceObservation))).all()) == 2


@pytest.mark.parametrize("verified,admin", [(False, True), (True, False)])
async def test_seed_does_not_bypass_company_or_document_guard(client, db_session, session_factory, monkeypatch, verified, admin):
    await seller_fixture(db_session, monkeypatch, verified=verified, admin=admin)
    monkeypatch.setattr(seed, "SessionLocal", session_factory)
    await seed.seed()
    assert (await client.get("/api/v3/products")).json() == []
    assert len((await db_session.scalars(select(ProductPriceObservation))).all()) == 0
    if not admin:
        documents = (await db_session.scalars(select(Document))).all()
        assert documents and all(doc.verification_status == "unverified" for doc in documents)


async def test_seed_requires_explicit_synthetic_flag(monkeypatch):
    monkeypatch.delenv("ENABLE_DEMO_SEED", raising=False)
    with pytest.raises(RuntimeError, match="ENABLE_DEMO_SEED=true"):
        await seed.seed()


async def test_seeded_capability_scopes_are_readable_and_stable(client, db_session, session_factory, monkeypatch):
    company = await seller_fixture(db_session, monkeypatch)
    monkeypatch.setattr(seed, "SessionLocal", session_factory)
    await seed.seed()
    user = (await db_session.execute(text("SELECT id FROM auth.users WHERE email='seller@demo.ru'"))).scalar_one()
    headers = {"Authorization": f"Bearer {make_token(user)}"}
    for _ in range(2):
        private = await client.get(f"/api/v3/companies/{company}/capability-passport", headers=headers)
        public = await client.get(f"/api/v3/producers/{company}")
        assert private.status_code == 200, private.text
        assert public.status_code == 200, public.text
        scopes = private.json()["details"]["category_scopes"]
        assert len(scopes) == 1 + len(ASSORTMENT)
        assert public.json()["capability_details"]["category_scopes"] == scopes
        await seed.seed()


def test_capability_scopes_remain_bounded():
    from app.schemas import CapabilityDetails
    from pydantic import ValidationError
    scope = {"category_id": "construction.fasteners", "unit": "шт"}
    assert len(CapabilityDetails(category_scopes=[scope] * 128).category_scopes) == 128
    with pytest.raises(ValidationError):
        CapabilityDetails(category_scopes=[scope] * 129)


async def test_seeded_seller_feed_includes_moscow_but_not_outside_district(client, db_session, session_factory, monkeypatch):
    from datetime import date, timedelta
    from app.models import DeliveryAddress
    company = await seller_fixture(db_session, monkeypatch)
    monkeypatch.setattr(seed, "SessionLocal", session_factory)
    await seed.seed()
    seller = (await db_session.execute(text("SELECT id FROM auth.users WHERE email='seller@demo.ru'"))).scalar_one()
    buyer = await make_user(db_session)
    buyer_company = await make_company(db_session, buyer, can_buy=True, can_sell=False)
    buyer_headers = {"Authorization": f"Bearer {make_token(buyer)}"}
    ids = []
    for region in ("г. Москва", "Свердловская область"):
        address = DeliveryAddress(company_id=buyer_company, address="ул. Синтетическая, д. 1", city="Синтетический город", region=region)
        db_session.add(address)
        await db_session.commit()
        created = await client.post("/api/v3/needs", headers=buyer_headers, json={
            "company_id": str(buyer_company), "category": "Строительство", "subcategory": "Крепёж",
            "characteristics": {"unit": "шт", "thread": "М8"}, "volume_units": 200,
            "budget_rub": "5000", "deadline_date": str(date.today() + timedelta(days=30)),
            "delivery_address_id": str(address.id), "visibility": "open_anonymized",
        })
        assert created.status_code == 201, created.text
        need_id = created.json()["id"]
        published = await client.post(f"/api/v3/needs/{need_id}/publish", headers=buyer_headers)
        assert published.status_code == 200, published.text
        ids.append(need_id)
    feed = await client.get(f"/api/v3/needs?seller_company_id={company}", headers={"Authorization": f"Bearer {make_token(seller)}"})
    assert feed.status_code == 200, feed.text
    visible = {item["id"] for item in feed.json()}
    assert ids[0] in visible
    assert ids[1] not in visible
