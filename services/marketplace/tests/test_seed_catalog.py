"""Clean synthetic startup uses the same publication guards as the seller UI."""
from decimal import Decimal

import pytest
from sqlalchemy import select, text

import seed
from app.assortment import ASSORTMENT
from app.models import Document, Product, ProductPriceObservation, TrustAuditEvent
from conftest import make_company, make_marketplace_admin, make_user


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
