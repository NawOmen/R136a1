"""Настоящие HTTP-переходы заказа на синтетическом, отдельно поднятом стенде."""
import os
import uuid
from datetime import date, timedelta
from decimal import Decimal

import httpx
import pytest

pytestmark = pytest.mark.skipif(os.getenv("RUN_DOCKER_INTEGRATION") != "1", reason="Только выделенный Docker-стенд")


def ok(response, status=200):
    try:
        body = response.json()
    except ValueError:
        body = {"detail": response.text[:500]}
    assert response.status_code == status, f"HTTP {response.status_code}: {body.get('detail', '') if isinstance(body, dict) else ''}"
    return body


def rows(body):
    if isinstance(body, list):
        return body
    for key in ("items", "products", "addresses", "companies"):
        if key in body:
            return body[key]
    raise AssertionError("Ответ не содержит ожидаемого списка")


def account(email, password, role):
    with httpx.Client(base_url="http://gateway-auth:8001", timeout=15) as auth:
        login = ok(auth.post("/api/v1/auth/login", json={"email": email, "password": password}))
        headers = {"Authorization": "Bearer " + login["access_token"]}
        me = ok(auth.get("/api/v1/auth/me", headers=headers))
        matches = [c for c in me["companies"] if c.get("membership", {}).get(role)]
        assert matches, f"У тестового аккаунта {email} нет роли {role}"
        company = matches[0]
        assert company["inn"].startswith("000"), "Компания не соответствует синтетическому seed-контракту"
    return headers, company["id"]


def test_classified_order_partial_acceptance_return_costs_and_privacy():
    buyer_headers, buyer = account("demo@demo.ru", os.environ["E2E_BUYER_PASSWORD"], "can_buy")
    seller_headers, seller = account("seller@demo.ru", os.environ["E2E_SELLER_PASSWORD"], "can_sell")
    with httpx.Client(base_url="http://marketplace:8002", timeout=15) as market:
        products = rows(ok(market.get(f"/api/v1/companies/{seller}/products", headers=seller_headers)))
        product = next(p for p in products if p["name"] == "Гайка М8 оцинкованная")
        addresses = rows(ok(market.get(f"/api/v1/companies/{buyer}/addresses", headers=buyer_headers)))
        # API поддерживает точную классификацию. Общая категория формы проверяется
        # отдельно браузерным тестом; её блокировку нельзя скрывать этим сценарием.
        need = ok(market.post("/api/v1/needs", headers=buyer_headers, json={
            "company_id": buyer, "category": "Крепёж", "characteristics": {"unit": "шт", "thread": "М8"},
            "volume_units": 500, "budget_rub": 5000, "deadline_date": (date.today()+timedelta(days=30)).isoformat(),
            "delivery_address_id": addresses[0]["id"], "visibility": "open_anonymized",
        }), 201)
        ok(market.post(f"/api/v1/needs/{need['id']}/publish", headers=buyer_headers))
        offer = ok(market.post(f"/api/v1/needs/{need['id']}/offers", headers=seller_headers, json={
            "company_id": seller, "resource_kind": "stock", "product_id": product["id"],
            "price_rub": 5, "available_units": 500, "lead_time_days": 1, "delivery_cost_rub": 0, "moq_units": 500,
        }), 201)
        # Обязательство без согласия не создаётся.
        response = market.post(f"/api/v1/offers/{offer['id']}/select", headers=buyer_headers, json={"expected_revision": offer["revision"]})
        assert response.status_code in (400, 422, 428)
        deal = ok(market.post(f"/api/v1/offers/{offer['id']}/select", headers=buyer_headers,
            json={"expected_revision": offer["revision"], "human_approved": True}), 201)
        deal_id = deal["id"]
        assert Decimal(str(deal["total_price_rub"])) == Decimal("2500")
        for stage in ("production", "shipment"):
            ok(market.patch(f"/api/v1/deals/{deal_id}/timeline/{stage}", headers=seller_headers,
                json={"company_id": seller, "completed": True, "human_approved": True}))
        acceptance = {"company_id": buyer, "kind": "acceptance", "units": 300, "note": "Синтетический акт приёмки",
            "idempotency_key": str(uuid.uuid4()), "human_approved": True}
        first = ok(market.post(f"/api/v1/deals/{deal_id}/execution", headers=buyer_headers, json=acceptance), 201)
        repeated = market.post(f"/api/v1/deals/{deal_id}/execution", headers=buyer_headers, json=acceptance)
        assert repeated.status_code in (200, 201)
        assert repeated.json()["id"] == first["id"]
        request = ok(market.post(f"/api/v1/deals/{deal_id}/execution", headers=buyer_headers, json={
            "company_id": buyer, "kind": "return", "units": 50, "note": "Синтетический возврат части партии",
            "idempotency_key": str(uuid.uuid4()), "human_approved": True,
        }), 201)
        ok(market.post(f"/api/v1/deals/{deal_id}/execution/{request['id']}/decision", headers=seller_headers,
            json={"company_id": seller, "approved": True, "human_approved": True}))
        ok(market.put(f"/api/v1/deals/{deal_id}/costs", headers=seller_headers, json={
            "company_id": seller, "expected_revision": 0, "unit_cost_rub": "3.00", "attributable_expenses_rub": "100.00",
            "note": "Синтетическая смета", "human_approved": True,
        }))
        report = ok(market.get(f"/api/v1/companies/{seller}/commercial-analytics?role=seller", headers=seller_headers))
        row = next(row for row in report["orders"] if row["deal_id"] == deal_id)
        assert (row["ordered_units"], row["accepted_units"], row["returned_units"], row["net_units"], row["open_units"]) == (500,300,50,250,200)
        assert Decimal(str(row["net_goods_revenue_rub"])) == Decimal("1250")
        assert Decimal(str(row["gross_profit_rub"])) == Decimal("500")
        assert Decimal(str(row["contribution_rub"])) == Decimal("400")
        assert row["payments_rub"] is None
        buyer_view = ok(market.get(f"/api/v1/deals/{deal_id}/execution?company_id={buyer}", headers=buyer_headers))
        assert "cost_revision" not in buyer_view
        assert "cost_of_goods_rub" not in buyer_view["financials"]
        assert market.get(f"/api/v1/companies/{seller}/commercial-analytics?role=seller", headers=buyer_headers).status_code == 404
