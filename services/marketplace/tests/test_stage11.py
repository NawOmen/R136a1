"""Этап 11: повтор закупки, шаблоны продавца, персональный шаг, поддержка и подписки."""

import uuid
from datetime import date, timedelta

from sqlalchemy import text

from conftest import make_company, make_marketplace_admin, make_token, make_user


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _future(days: int = 30) -> str:
    return (date.today() + timedelta(days=days)).isoformat()


async def _make_need(client, buyer_user, buyer_company):
    r = await client.post(
        "/api/v1/needs",
        json={
            "request_key": str(uuid.uuid4()),
            "company_id": str(buyer_company),
            "category": "Мебель",
            "characteristics": {"material": "дерево"},
            "volume_units": 5,
            "budget_rub": 100000,
            "deadline_date": _future(30),
            "visibility": "closed",
        },
        headers=_auth(make_token(buyer_user)),
    )
    assert r.status_code == 201, r.text
    return r.json()


async def test_repeat_preview_does_not_create_and_explains_not_carried(client, db_session):
    buyer = await make_user(db_session)
    company = await make_company(db_session, buyer, can_buy=True, can_sell=False)
    original = await _make_need(client, buyer, company)
    before = (await db_session.execute(text("SELECT COUNT(*) FROM marketplace.needs"))).scalar_one()
    r = await client.post(f"/api/v1/needs/{original['id']}/repeat-preview", headers=_auth(make_token(buyer)))
    assert r.status_code == 200, r.text
    payload = r.json()
    assert payload["changes"]
    assert any("Сроки" in c["field"] for c in payload["changes"])
    assert "Файлы и исходные материалы" in payload["not_carried"]
    after = (await db_session.execute(text("SELECT COUNT(*) FROM marketplace.needs"))).scalar_one()
    assert after == before


async def test_repeat_preview_never_treats_buyer_capacity_as_supplier_resource(client, db_session):
    buyer = await make_user(db_session)
    company = await make_company(db_session, buyer, can_buy=True, can_sell=False)
    original = await _make_need(client, buyer, company)
    await db_session.execute(
        text(
            "INSERT INTO marketplace.capacity_entries (id, company_id, date, category, unit, available_units) "
            "VALUES (gen_random_uuid(), :cid, :day, '', 'шт', 1000)"
        ),
        {"cid": company, "day": date.today() + timedelta(days=5)},
    )
    await db_session.commit()
    r = await client.post(f"/api/v1/needs/{original['id']}/repeat-preview", headers=_auth(make_token(buyer)))
    assert r.status_code == 200, r.text
    fields = [c["field"] for c in r.json()["changes"]]
    assert "Свободная мощность" not in fields
    assert not any(c["now"] == "1000" for c in r.json()["changes"])


async def test_repeat_with_valid_until_returns_new_draft(client, db_session):
    buyer = await make_user(db_session)
    company = await make_company(db_session, buyer, can_buy=True, can_sell=False)
    original = await _make_need(client, buyer, company)
    deadline = _future(45)
    valid_until = _future(40)
    # срок актуальности позже срока поставки запрещён
    bad = await client.post(
        f"/api/v1/needs/{original['id']}/repeat",
        json={"deadline_date": deadline, "valid_until": _future(50), "request_key": str(uuid.uuid4())},
        headers=_auth(make_token(buyer)),
    )
    assert bad.status_code == 422
    r = await client.post(
        f"/api/v1/needs/{original['id']}/repeat",
        json={"deadline_date": deadline, "valid_until": valid_until, "request_key": str(uuid.uuid4())},
        headers=_auth(make_token(buyer)),
    )
    assert r.status_code == 201, r.text
    copy = r.json()
    assert copy["id"] != original["id"]
    assert copy["status"] == "draft"
    assert copy["deadline_date"] == deadline
    assert copy["valid_until"] == valid_until
    assert copy["files"] == []


async def test_repeat_requires_rights_and_future_dates(client, db_session):
    buyer = await make_user(db_session)
    company = await make_company(db_session, buyer, can_buy=True, can_sell=False)
    original = await _make_need(client, buyer, company)
    stranger = await make_user(db_session)
    r = await client.post(
        f"/api/v1/needs/{original['id']}/repeat",
        json={"deadline_date": _future(10), "request_key": str(uuid.uuid4())},
        headers=_auth(make_token(stranger)),
    )
    assert r.status_code in (403, 404)
    bad = await client.post(
        f"/api/v1/needs/{original['id']}/repeat",
        json={"deadline_date": "2020-01-01", "request_key": str(uuid.uuid4())},
        headers=_auth(make_token(buyer)),
    )
    assert bad.status_code == 422


async def test_duplicate_product_creates_unpublished_draft(client, db_session):
    seller = await make_user(db_session)
    company = await make_company(db_session, seller, can_buy=False, can_sell=True)
    token = make_token(seller)
    r = await client.post(
        f"/api/v1/companies/{company}/products",
        json={
            "name": "Стул рабочий",
            "category": "Строительство",
            "subcategory": "Крепёж",
            "characteristics": {"unit": "шт"},
            "price_rub": 5,
            "moq_units": 10,
            "lead_time_days": 1,
        },
        headers=_auth(token),
    )
    assert r.status_code == 201, r.text
    product_id = r.json()["id"]
    await db_session.execute(
        text(
            "INSERT INTO marketplace.product_images (id, product_id, file_name, file_key, content_type, position) "
            "VALUES (gen_random_uuid(), :pid, 'фото.png', 'products/шаблон', 'image/png', 0)"
        ),
        {"pid": product_id},
    )
    await db_session.commit()
    r = await client.post(f"/api/v1/products/{product_id}/duplicate", headers=_auth(token))
    assert r.status_code == 201, r.text
    copy = r.json()
    assert copy["id"] != product_id
    assert copy["is_published"] is False
    assert copy["name"].startswith("Копия")
    assert len(copy["images"]) == 1
    assert copy["images"][0]["file_name"] == "фото.png"


async def test_next_step_ordering(client, db_session):
    admin = await make_marketplace_admin(db_session)
    r = await client.get("/api/v1/next-step", headers=_auth(make_token(admin)))
    assert r.status_code == 200
    assert r.json()["href"] == "/admin"
    lonely = await make_user(db_session)
    r = await client.get("/api/v1/next-step", headers=_auth(make_token(lonely)))
    assert r.json()["href"] == "/company/new"
    user = await make_user(db_session)
    pending_company = await make_company(db_session, user, can_buy=True, can_sell=False, verified=False)
    r = await client.get("/api/v1/next-step", headers=_auth(make_token(user)))
    assert r.json()["href"] == "/needs/new"
    buyer = await make_user(db_session)
    await make_company(db_session, buyer, can_buy=True, can_sell=False, verified=True)
    r = await client.get("/api/v1/next-step", headers=_auth(make_token(buyer)))
    assert r.json()["href"] == "/needs/new"
    r = await client.get("/api/v1/next-step?company_id=" + str(pending_company) + "&mode=buy", headers=_auth(make_token(user)))
    assert r.json()["href"] == "/needs/new"
    seller = await make_user(db_session)
    await make_company(db_session, seller, can_buy=False, can_sell=True, verified=True)
    r = await client.get("/api/v1/next-step", headers=_auth(make_token(seller)))
    assert r.json()["href"] == "/seller/profile"


async def test_blocked_user_cannot_repeat_preview_or_next_step(client, db_session):
    buyer = await make_user(db_session)
    company = await make_company(db_session, buyer, can_buy=True, can_sell=False)
    original = await _make_need(client, buyer, company)
    await db_session.execute(text("UPDATE auth.users SET account_status='blocked' WHERE id=:id"), {"id": buyer})
    await db_session.commit()
    token = make_token(buyer)
    assert (await client.post(f"/api/v1/needs/{original['id']}/repeat-preview", headers=_auth(token))).status_code == 401
    assert (await client.post(f"/api/v1/needs/{original['id']}/repeat", json={"deadline_date": _future(10), "request_key": str(uuid.uuid4())}, headers=_auth(token))).status_code == 401
    assert (await client.get("/api/v1/next-step", headers=_auth(token))).status_code == 401


async def test_support_ticket_notifies_admin_and_response_notifies_user(client, db_session):
    admin = await make_marketplace_admin(db_session)
    user = await make_user(db_session)
    company = await make_company(db_session, user, can_buy=True, can_sell=False)
    user_token = make_token(user)
    admin_token = make_token(admin)
    r = await client.post(
        "/api/v1/support/tickets",
        json={"company_id": str(company), "subject": "Не входит в сделку", "message": "Опишите проблему подробнее здесь."},
        headers=_auth(user_token),
    )
    assert r.status_code == 201, r.text
    ticket_id = r.json()["id"]
    r = await client.get("/api/v1/notifications", headers=_auth(admin_token))
    assert r.status_code == 200
    assert any(n["type"] == "support_ticket_created" and "Не входит в сделку" in n["message"] for n in r.json())
    r = await client.patch(
        f"/api/v1/admin/support/tickets/{ticket_id}",
        json={"status": "resolved", "admin_response": "Проверили, всё в порядке."},
        headers=_auth(admin_token),
    )
    assert r.status_code == 200
    r = await client.get("/api/v1/notifications", headers=_auth(user_token))
    assert r.status_code == 200
    assert any(n["type"] == "support_ticket_updated" and "Не входит в сделку" in n["message"] for n in r.json())
    r = await client.get("/api/v1/support/tickets/mine", headers=_auth(user_token))
    mine = [t for t in r.json() if t["id"] == ticket_id]
    assert mine and mine[0]["admin_response"] == "Проверили, всё в порядке."


async def test_market_watch_dedup_and_read_does_not_change_business(client, db_session):
    user = await make_user(db_session)
    await make_company(db_session, user, can_buy=True, can_sell=False)
    token = make_token(user)
    r = await client.post("/api/v1/market-watches", json={"category": "Мебель"}, headers=_auth(token))
    assert r.status_code == 201
    first_id = r.json()["id"]
    r = await client.post("/api/v1/market-watches", json={"category": "Мебель"}, headers=_auth(token))
    assert r.status_code == 201
    assert r.json()["id"] == first_id
    await db_session.execute(
        text("INSERT INTO marketplace.notifications (id, user_id, message, type) VALUES (gen_random_uuid(), :uid, :msg, 'info')"),
        {"uid": user, "msg": "Тестовое уведомление"},
    )
    await db_session.commit()
    r = await client.get("/api/v1/notifications", headers=_auth(token))
    target = [n for n in r.json() if n["message"] == "Тестовое уведомление"][0]
    r = await client.post(f"/api/v1/notifications/{target['id']}/read", headers=_auth(token))
    assert r.status_code == 200
    assert r.json()["is_read"] is True
