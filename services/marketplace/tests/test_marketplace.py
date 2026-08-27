import uuid

import jwt
from sqlalchemy import text

from app.config import settings


def _token(user_id: uuid.UUID) -> str:
    return jwt.encode({"sub": str(user_id)}, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


async def _make_user(db_session) -> uuid.UUID:
    uid = uuid.uuid4()
    await db_session.execute(text("INSERT INTO auth.users (id) VALUES (:id)"), {"id": uid})
    await db_session.commit()
    return uid


async def _make_company(db_session, user_id: uuid.UUID, can_buy=True, can_sell=True, verified=True) -> uuid.UUID:
    cid = uuid.uuid4()
    status = "verified" if verified else "draft"
    await db_session.execute(
        text("INSERT INTO auth.companies (id, verification_status) VALUES (:id, :s)"),
        {"id": cid, "s": status},
    )
    await db_session.execute(
        text(
            "INSERT INTO auth.company_members (id, company_id, user_id, can_buy, can_sell, is_admin) "
            "VALUES (:id, :cid, :uid, :cb, :cs, true)"
        ),
        {"id": uuid.uuid4(), "cid": cid, "uid": user_id, "cb": can_buy, "cs": can_sell},
    )
    await db_session.commit()
    return cid


async def test_full_flow(client, db_session):
    seller_user = await _make_user(db_session)
    seller_company = await _make_company(db_session, seller_user, can_buy=False, can_sell=True)
    seller_token = _token(seller_user)

    buyer_user = await _make_user(db_session)
    buyer_company = await _make_company(db_session, buyer_user, can_buy=True, can_sell=False)
    buyer_token = _token(buyer_user)

    # продавец создаёт и публикует товар
    r = await client.post(
        f"/api/v1/companies/{seller_company}/products",
        json={"name": "Стакан 400 мл PE", "category": "бумажные стаканы", "characteristics": {"volume_ml": 400}, "price_rub": 11.2, "moq_units": 20000, "lead_time_days": 9},
        headers=_auth(seller_token),
    )
    assert r.status_code == 201
    product_id = r.json()["id"]

    r = await client.post(f"/api/v1/products/{product_id}/publish", json={"published": True}, headers=_auth(seller_token))
    assert r.status_code == 200

    r = await client.get("/api/v1/products")
    assert any(p["id"] == product_id for p in r.json())

    # покупатель создаёт адрес и потребность
    r = await client.post(
        f"/api/v1/companies/{buyer_company}/addresses",
        json={"address": "г. Москва, ул. Тестовая, 1", "city": "Москва", "region": "г. Москва", "is_default": True},
        headers=_auth(buyer_token),
    )
    assert r.status_code == 201
    address_id = r.json()["id"]

    r = await client.post(
        "/api/v1/needs",
        json={"company_id": str(buyer_company), "category": "бумажные стаканы", "characteristics": {"volume_ml": 400}, "volume_units": 120000, "budget_rub": 1900000, "deadline_date": "2026-10-30", "delivery_address_id": str(address_id), "visibility": "open_anonymized"},
        headers=_auth(buyer_token),
    )
    assert r.status_code == 201
    need_id = r.json()["id"]

    # продавец отвечает предложением
    r = await client.post(
        f"/api/v1/needs/{need_id}/offers",
        json={"company_id": str(seller_company), "price_rub": 11.0, "available_units": 50000, "lead_time_days": 9},
        headers=_auth(seller_token),
    )
    assert r.status_code == 201
    offer_id = r.json()["id"]

    # покупатель выбирает предложение
    r = await client.post(f"/api/v1/offers/{offer_id}/select", headers=_auth(buyer_token))
    assert r.status_code == 201
    assert r.json()["status"] == "created"

    r = await client.get(f"/api/v1/needs/{need_id}", headers=_auth(buyer_token))
    assert r.json()["status"] == "matched"


async def test_unverified_company_cannot_create_need(client, db_session):
    user = await _make_user(db_session)
    company = await _make_company(db_session, user, can_buy=True, can_sell=False, verified=False)
    r = await client.post(
        "/api/v1/needs",
        json={"company_id": str(company), "category": "бумажные стаканы", "characteristics": {}, "volume_units": 1000, "deadline_date": "2026-10-30", "visibility": "open_anonymized"},
        headers=_auth(_token(user)),
    )
    assert r.status_code == 403


async def test_company_without_seller_cannot_create_product(client, db_session):
    user = await _make_user(db_session)
    company = await _make_company(db_session, user, can_buy=True, can_sell=False)
    r = await client.post(
        f"/api/v1/companies/{company}/products",
        json={"name": "Стакан", "category": "бумажные стаканы", "characteristics": {}, "price_rub": 10, "moq_units": 1000, "lead_time_days": 5},
        headers=_auth(_token(user)),
    )
    assert r.status_code == 403
