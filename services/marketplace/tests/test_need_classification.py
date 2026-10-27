from conftest import confirmed_quote_terms
from datetime import date, timedelta

from sqlalchemy import select

from conftest import make_company, make_token, make_user, grant_category_capability, make_marketplace_admin
from app.models import CapabilityPassport, Coalition, Need, Product, Document


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
    attributes={"unit":"шт","thread":"М8","material":"сталь","standard":"СИН-Б8","product_kind":"болт","diameter_mm":8,"length_mm":40}
    from datetime import datetime,timezone
    db_session.add(Document(company_id=seller,name="Синтетическая проверка спецификации",document_type="specification_review",file_key="synthetic/fastener",content_type="text/plain",verification_status="verified",scope_category="Строительство",scope_subcategory="Крепёж",confirms={key:[value] for key,value in attributes.items()},verified_by_user_id=await make_marketplace_admin(db_session),verified_at=datetime.now(timezone.utc),valid_until=date.today()+timedelta(days=30)))
    await db_session.commit()
    response = await client.post(f"/api/v1/companies/{seller}/products", headers=seller_auth, json={
        "name": "Синтетический болт М8", "category": "Строительство", "subcategory": "Крепёж",
        "characteristics": attributes, "price_rub": 10,
        "moq_units": 1, "lead_time_days": 1, "stock_units": 500,
    })
    assert response.status_code == 201, response.text
    product = response.json()
    response = await client.post(f"/api/v1/products/{product['id']}/publish", json={"published": True}, headers=seller_auth)
    assert response.status_code == 200, response.text
    response = await client.post("/api/v1/needs", headers=buyer_auth, json={
        "company_id": str(buyer), "category": "Строительство", "subcategory": "Крепёж",
        "characteristics": attributes, "volume_units": 100,
        "budget_rub": 5000, "deadline_date": (date.today()+timedelta(days=30)).isoformat(),
    })
    assert response.status_code == 201, response.text
    need = response.json()
    assert need["category"] == "Строительство" and need["subcategory"] == "Крепёж"
    assert (await client.post(f"/api/v1/needs/{need['id']}/publish", headers=buyer_auth)).status_code == 200
    response = await client.post(f"/api/v1/needs/{need['id']}/offers", headers=seller_auth, json={'commercial_terms': confirmed_quote_terms(),
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
    await grant_category_capability(db_session,seller,"construction.fasteners",{},min_units=1000)
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
    assert known.state == legacy.state == "blocked"
    assert known.blocking_open > 0 and legacy.blocking_open > 0
    for category, subtype in [("Строительство", "Выдуманный вид"), ("Медицина и гигиена", "Расходные материалы"), ("Продукты питания", "Напитки")]:
        report = evaluate_admission(category=category, subcategory=subtype, characteristics={}, documents=[])
        assert report.blocking_open > 0


def test_web_and_backend_category_tree_contract():
    import json
    from pathlib import Path
    from app.category_tree import CATALOG_TREE
    from app.category_registry import REGISTRY_VERSION, registry_snapshot
    source = Path(__file__).resolve().parents[3] / "apps/web/app/lib/category-registry.generated.json"
    snapshot = json.loads(source.read_text())
    assert snapshot["tree"] == CATALOG_TREE
    assert snapshot["registry_version"] == REGISTRY_VERSION
    for group in registry_snapshot()["groups"]:
        for leaf in group["leaves"]:
            assert snapshot["leaf_ids"][group["label"]][leaf["label"]] == leaf["id"]


async def test_reviewed_ai_specification_reaches_seller_feed_and_custom_constraints_stay_strict(client, db_session):
    """Regression for the exact extra keys seen in the live Qwen walkthrough."""
    seller_user = await make_user(db_session)
    seller = await make_company(db_session, seller_user, can_buy=False, can_sell=True)
    buyer_user = await make_user(db_session)
    buyer = await make_company(db_session, buyer_user, can_buy=True, can_sell=False)
    attributes = {"unit":"шт", "thread":"М8", "material":"сталь", "standard":"синтетическая спецификация Б-01",
                  "length_mm":"40", "diameter_mm":"8", "product_kind":"болт", "strength_class":"8.8"}
    await grant_category_capability(db_session, seller, "construction.fasteners", attributes, min_units=200, max_units=12000)
    ids = []
    for extra in ({}, {"grade":"8.8"}, {"delivery_date":"26.11.26"}, {"особое требование":"согласовать образец"}):
        response = await client.post("/api/v3/needs", headers=auth(make_token(buyer_user)), json={
            "company_id":str(buyer), "category":"Строительство", "subcategory":"Крепёж",
            "characteristics":{**attributes, **extra}, "volume_units":200, "budget_rub":5000,
            "deadline_date":(date.today()+timedelta(days=30)).isoformat()})
        assert response.status_code == 201, response.text
        need = response.json()
        assert need["matching_warnings"] and "обязательны при подборе" in need["matching_warnings"][0]
        assert need["characteristics"] == {**attributes, **extra}  # Never weaken API constraints.
        published = await client.post(f"/api/v3/needs/{need['id']}/publish", headers=auth(make_token(buyer_user)))
        assert published.status_code == 200, published.text
        ids.append(need["id"])
    feed = await client.get("/api/v3/needs", params={"seller_company_id":str(seller)}, headers=auth(make_token(seller_user)))
    assert feed.status_code == 200, feed.text
    visible = {need["id"] for need in feed.json()}
    assert ids[0] in visible
    assert not visible.intersection(ids[1:])


async def test_matching_preview_and_saved_need_use_the_same_common_and_hard_rules(client, db_session):
    buyer_user = await make_user(db_session)
    buyer = await make_company(db_session, buyer_user, can_buy=True, can_sell=False)
    headers = auth(make_token(buyer_user))
    for key, value, warned in [("food_contact",True,True), ("mandatory_requirements",["согласовать образец"],True),
                               ("свой параметр","значение",True), ("material","сталь",False),
                               ("print","логотип",False), ("volume_tolerance",5,False)]:
        values = {"category":"Строительство","subcategory":"Крепёж","characteristics":{"unit":"шт",key:value},"volume_units":200}
        preview = await client.post('/api/v2/physical-quantities/preview',json={"kind":"need","values":{
            **values,"category_profile":{"fields":{key:{"label":"Клиентское определение"}}}}})
        assert preview.status_code == 200, preview.text
        created = await client.post('/api/v3/needs',headers=headers,json={**values,"company_id":str(buyer),
            "deadline_date":(date.today()+timedelta(days=30)).isoformat(),"budget_rub":5000})
        assert created.status_code == 201, created.text
        assert preview.json()["matching_warnings"] == created.json()["matching_warnings"]
        assert bool(created.json()["matching_warnings"]) is warned
