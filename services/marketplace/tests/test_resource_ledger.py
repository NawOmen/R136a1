import asyncio
import uuid
from datetime import date, datetime, timedelta, timezone

import pytest
from fastapi import HTTPException
from sqlalchemy import select
from app.models import CapacityEntry, Product, ResourceReservation
from app.resources import activate_hold, consume, free_stock, release, reserve
from conftest import make_company, make_user, make_token, grant_capacity


@pytest.fixture
async def warehouse(db_session):
    user = await make_user(db_session)
    company = await make_company(db_session, user, can_buy=False)
    product = Product(company_id=company, name="Стол", category="Мебель", characteristics={}, price_rub=1000,
                      price_tiers=[], moq_units=1, lead_time_days=1, stock_units=10, stock_updated_at=datetime.now(timezone.utc))
    db_session.add(product); await db_session.commit()
    return user, company, product.id


@pytest.mark.asyncio
async def test_concurrent_buyers_cannot_reserve_same_stock(warehouse, session_factory):
    _, company, product = warehouse
    async def allocate():
        async with session_factory() as db:
            try:
                await reserve(db, company_id=company, anchor_type="deal", anchor_id=uuid.uuid4(), units=7,
                              deadline=date.today(), resource_kind="stock", product_id=product)
                await db.commit()
                return True
            except HTTPException as exc:
                await db.rollback()
                assert exc.status_code == 409
                return False
    assert sorted(await asyncio.gather(allocate(), allocate())) == [False, True]
    async with session_factory() as db:
        assert await free_stock(db, await db.get(Product, product)) == 3


@pytest.mark.asyncio
async def test_expiry_release_and_consumption(warehouse, db_session):
    _, company, product_id = warehouse
    anchor = uuid.uuid4()
    await reserve(db_session, company_id=company, anchor_type="reserve", anchor_id=anchor, units=8, deadline=date.today(),
                  resource_kind="stock", product_id=product_id, expires_at=datetime.now(timezone.utc)+timedelta(hours=1))
    product = await db_session.get(Product, product_id)
    assert await free_stock(db_session, product) == 2
    await activate_hold(db_session, company_id=company, anchor_id=anchor, units=6)
    assert await free_stock(db_session, product) == 4
    await consume(db_session, company_id=company, anchor_type="reserve", anchor_id=anchor)
    await consume(db_session, company_id=company, anchor_type="reserve", anchor_id=anchor)
    assert product.stock_units == 4
    assert await free_stock(db_session, product) == 4
    expired = uuid.uuid4()
    await reserve(db_session, company_id=company, anchor_type="reserve", anchor_id=expired, units=4, deadline=date.today(),
                  resource_kind="stock", product_id=product_id, expires_at=datetime.now(timezone.utc)-timedelta(seconds=1))
    assert await free_stock(db_session, product) == 4
    with pytest.raises(HTTPException):
        await activate_hold(db_session, company_id=company, anchor_id=expired, units=1)


@pytest.mark.asyncio
async def test_capacity_shared_by_deal_and_coalition_and_cannot_shrink(warehouse, db_session, client):
    user, company, _ = warehouse
    day = date.today()+timedelta(days=1)
    await grant_capacity(db_session,company,10,day)
    anchor = uuid.uuid4()
    await reserve(db_session, company_id=company, anchor_type="deal", anchor_id=anchor, units=6, deadline=day, category="Упаковка и тара",subcategory="Бумажные стаканы")
    await db_session.commit()
    with pytest.raises(HTTPException):
        await reserve(db_session, company_id=company, anchor_type="coalition", anchor_id=uuid.uuid4(), units=5, deadline=day, category="Упаковка и тара",subcategory="Бумажные стаканы")
    await db_session.rollback()
    response = await client.put(f"/api/v1/companies/{company}/capacity",headers={"Authorization":f"Bearer {make_token(user)}"},json={"entries":[{"date":str(day),"available_units":5}]})
    assert response.status_code == 409
    await release(db_session, company_id=company, anchor_type="deal", anchor_id=anchor, units=2)
    await db_session.commit()
    await reserve(db_session, company_id=company, anchor_type="coalition", anchor_id=uuid.uuid4(), units=6, deadline=day, category="Упаковка и тара",subcategory="Бумажные стаканы")
    await db_session.commit()
    rows=(await db_session.scalars(select(ResourceReservation).where(ResourceReservation.status=="committed"))).all()
    assert sum(r.units for r in rows)==10


@pytest.mark.asyncio
async def test_capacity_scopes_keep_categories_and_units_separate(warehouse, db_session, client):
    user, company, _ = warehouse
    day = date.today() + timedelta(days=1)
    headers = {"Authorization": f"Bearer {make_token(user)}"}
    payload = {"entries": [
        {"date": str(day), "category": "business-supplies.furniture", "unit": "шт", "available_units": 5},
        {"date": str(day), "category": "materials.textile", "unit": "м", "available_units": 8},
    ]}
    response = await client.put(f"/api/v1/companies/{company}/capacity", headers=headers, json=payload)
    assert response.status_code == 200, response.text
    rows = (await client.get(f"/api/v1/companies/{company}/capacity", headers=headers)).json()
    assert {(row["category"], row["unit"], row["available_units"]) for row in rows} == {
        ("business-supplies.furniture", "шт", 5), ("materials.textile", "м", 8),
    }
    await reserve(db_session, company_id=company, anchor_type="deal", anchor_id=uuid.uuid4(),
                  units=5, deadline=day, category="Мебель", unit="шт")
    await db_session.commit()
    with pytest.raises(HTTPException):
        await reserve(db_session, company_id=company, anchor_type="deal", anchor_id=uuid.uuid4(),
                      units=1, deadline=day, category="Упаковка и тара", unit="шт")
    await db_session.rollback()
    await reserve(db_session, company_id=company, anchor_type="deal", anchor_id=uuid.uuid4(),
                  units=8, deadline=day, category="Сырьё и материалы", subcategory="Текстиль", unit="м")


@pytest.mark.asyncio
async def test_catalog_stock_tracks_holds_and_stale_updates(warehouse, db_session):
    from app.resources import catalog_available_stock
    _, company, product_id = warehouse
    product = await db_session.get(Product, product_id)
    assert await catalog_available_stock(db_session, product) == 10
    anchor = uuid.uuid4()
    await reserve(db_session, company_id=company, anchor_type="reserve", anchor_id=anchor, units=8,
                  deadline=date.today(), resource_kind="stock", product_id=product_id,
                  expires_at=datetime.now(timezone.utc)+timedelta(hours=1))
    assert await catalog_available_stock(db_session, product) == 2
    rows = await db_session.scalars(select(ResourceReservation).where(ResourceReservation.anchor_id == anchor))
    for row in rows:
        row.expires_at = datetime.now(timezone.utc)-timedelta(seconds=1)
    await db_session.flush()
    assert await catalog_available_stock(db_session, product) == 10
    product.stock_updated_at = datetime.now(timezone.utc)-timedelta(days=8)
    assert await catalog_available_stock(db_session, product) is None
    product.stock_updated_at = datetime.now(timezone.utc)
    product.stock_units = None
    assert await catalog_available_stock(db_session, product) is None
