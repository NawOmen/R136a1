from datetime import date, timedelta

from sqlalchemy import select

from conftest import make_company, make_token, make_user
from app.models import CapabilityPassport, Coalition, Need, Product


def auth(token):
    return {"Authorization": f"Bearer {token}"}


async def test_seller_feed_matches_parent_and_child_without_leaking_private_needs(client, db_session):
    seller_user = await make_user(db_session)
    seller = await make_company(db_session, seller_user, can_buy=False, can_sell=True)
    buyer_user = await make_user(db_session)
    buyer = await make_company(db_session, buyer_user, can_buy=True, can_sell=False)
    db_session.add(Product(company_id=seller, name="Синтетический крепёж", category="Строительство",
                           subcategory="Крепёж", characteristics={"unit": "шт"}, price_rub=10, moq_units=1, lead_time_days=1))
    visible = []
    for category, subtype, visibility, expired in [
        ("Строительство", None, "open_anonymized", False),
        ("Строительство", "Крепёж", "open_anonymized", False),
        ("крепеж", None, "open_anonymized", False),
        ("Строительство", "Инструмент", "open_anonymized", False),
        ("Продукты питания", "Напитки", "open_anonymized", False),
        ("Строительство", "Крепёж", "closed", False),
        ("Строительство", "Крепёж", "open_anonymized", True),
    ]:
        need = Need(company_id=buyer, category=category, subcategory=subtype, characteristics={"unit": "шт"},
                    volume_units=100, budget_rub=10000, deadline_date=date.today()+timedelta(days=30),
                    valid_until=date.today()+timedelta(days=-1 if expired else 30),
                    status="open_for_offers", visibility=visibility)
        db_session.add(need)
        await db_session.flush()
        if len(visible) < 3 and subtype != "Инструмент" and not expired and category != "Продукты питания" and visibility == "open_anonymized":
            visible.append(str(need.id))
    await db_session.commit()
    response = await client.get("/api/v1/needs", params={"seller_company_id": str(seller)}, headers=auth(make_token(seller_user)))
    assert response.status_code == 200, response.text
    assert {row["id"] for row in response.json()} == set(visible)
    assert all("company_id" not in row and "budget_rub" not in row for row in response.json())
    denied = await client.get("/api/v1/needs", params={"seller_company_id": str(seller)}, headers=auth(make_token(buyer_user)))
    assert denied.status_code == 404


async def test_explicit_parent_child_order_keeps_approval_and_category_admission(client, db_session):
    seller_user = await make_user(db_session)
    seller = await make_company(db_session, seller_user, can_buy=False, can_sell=True)
    buyer_user = await make_user(db_session)
    buyer = await make_company(db_session, buyer_user, can_buy=True, can_sell=False)
    seller_auth, buyer_auth = auth(make_token(seller_user)), auth(make_token(buyer_user))
    response = await client.post(f"/api/v1/companies/{seller}/products", headers=seller_auth, json={
        "name": "Синтетический болт М8", "category": "Строительство", "subcategory": "Крепёж",
        "characteristics": {"unit": "шт", "thread": "М8"}, "price_rub": 10,
        "moq_units": 1, "lead_time_days": 1, "stock_units": 500,
    })
    assert response.status_code == 201, response.text
    product = response.json()
    response = await client.post(f"/api/v1/products/{product['id']}/publish", json={"published": True}, headers=seller_auth)
    assert response.status_code == 200, response.text
    response = await client.post("/api/v1/needs", headers=buyer_auth, json={
        "company_id": str(buyer), "category": "Строительство", "subcategory": "Крепёж",
        "characteristics": {"unit": "шт", "thread": "М8"}, "volume_units": 100,
        "budget_rub": 5000, "deadline_date": (date.today()+timedelta(days=30)).isoformat(),
    })
    assert response.status_code == 201, response.text
    need = response.json()
    assert need["category"] == "Строительство" and need["subcategory"] == "Крепёж"
    assert (await client.post(f"/api/v1/needs/{need['id']}/publish", headers=buyer_auth)).status_code == 200
    response = await client.post(f"/api/v1/needs/{need['id']}/offers", headers=seller_auth, json={
        "company_id": str(seller), "product_id": product["id"], "resource_kind": "stock", "price_rub": 10,
        "available_units": 100, "moq_units": 1, "lead_time_days": 1, "delivery_cost_rub": 0,
    })
    assert response.status_code == 201, response.text
    offer = response.json()
    url = f"/api/v1/offers/{offer['id']}/select"
    assert (await client.post(url, headers=buyer_auth, json={"expected_revision": offer["revision"]})).status_code == 422
    response = await client.post(url, headers=buyer_auth, json={"expected_revision": offer["revision"], "human_approved": True})
    assert response.status_code == 201, response.text


async def test_different_subcategories_are_not_combined_in_coalition(client, db_session):
    seller_user = await make_user(db_session)
    seller = await make_company(db_session, seller_user, can_buy=False, can_sell=True)
    db_session.add(CapabilityPassport(company_id=seller, technologies=["Строительство"], min_order_units=1000))
    await db_session.commit()
    for subtype in ("Крепёж", "Инструмент"):
        user = await make_user(db_session)
        buyer = await make_company(db_session, user, can_buy=True, can_sell=False)
        response = await client.post("/api/v1/needs", headers=auth(make_token(user)), json={
            "company_id": str(buyer), "category": "Строительство", "subcategory": subtype,
            "characteristics": {"unit": "шт"}, "volume_units": 500,
            "deadline_date": (date.today()+timedelta(days=30)).isoformat(),
        })
        assert response.status_code == 201
        response = await client.post(f"/api/v1/needs/{response.json()['id']}/publish", headers=auth(make_token(user)))
        assert response.status_code == 200, response.text
    assert (await db_session.scalars(select(Coalition))).all() == []


def test_catalog_classification_does_not_bypass_regulated_or_unknown_subtypes():
    from app.category_admission import evaluate_admission
    known = evaluate_admission(category="Строительство", subcategory="Крепёж", characteristics={}, documents=[])
    legacy = evaluate_admission(category="Крепёж", subcategory=None, characteristics={}, documents=[])
    assert known.state == legacy.state == "not_configured"
    assert known.blocking_open == legacy.blocking_open == 0
    for category, subtype in [("Строительство", "Выдуманный вид"), ("Медицина и гигиена", "Расходные материалы"), ("Продукты питания", "Напитки")]:
        report = evaluate_admission(category=category, subcategory=subtype, characteristics={}, documents=[])
        assert report.blocking_open > 0


def test_web_and_backend_category_tree_contract():
    import json
    import re
    from pathlib import Path
    from app.category_tree import CATALOG_TREE
    source = (Path(__file__).resolve().parents[3] / "apps/web/app/lib/marketplace.ts").read_text()
    body = source.split("export const PRODUCT_CATEGORY_TREE: Record<string, string[]> = ", 1)[1].split(";", 1)[0]
    assert json.loads(re.sub(r",\s*}", "}", body)) == CATALOG_TREE
