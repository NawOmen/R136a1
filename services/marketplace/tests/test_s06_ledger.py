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

from app.models import Product, ResourceReservation
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
from conftest import make_company, make_token, make_user


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
    assert await return_stock(db_session, company_id=company, product_id=product_id, units=3, quality_accepted=True) == 13
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
