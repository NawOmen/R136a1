"""Настоящие HTTP-переходы заказа на синтетическом, отдельно поднятом стенде."""
import os
import io
from pypdf import PdfWriter
import uuid
from datetime import date, timedelta
from decimal import Decimal

import httpx
import pytest

pytestmark = pytest.mark.skipif(os.getenv("RUN_DOCKER_INTEGRATION") != "1", reason="Только выделенный Docker-стенд")


def synthetic_pdf():
    writer = PdfWriter()
    writer.add_blank_page(width=200, height=200)
    writer.add_metadata({"/Title": "Synthetic acceptance fixture"})
    stream = io.BytesIO()
    writer.write(stream)
    return stream.getvalue()


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
        # Synthetic specification reviewed by the seeded platform editor through the real API.
        with httpx.Client(base_url="http://gateway-auth:8001", timeout=15) as auth:
            editor = ok(auth.post("/api/v1/auth/login", json={"email": "admin@demo.ru", "password": os.environ["SEED_ADMIN_PASSWORD"]}))
        editor_headers = {"Authorization": "Bearer " + editor["access_token"]}
        document = ok(market.post(f"/api/v1/companies/{seller}/documents", headers=seller_headers,
            data={"name": "Синтетическое заключение по спецификации крепежа", "document_type": "specification_review",
                  "scope_category": product["category"], "scope_subcategory": product.get("subcategory") or ""},
            files={"file": ("synthetic-specification.pdf", synthetic_pdf(), "application/pdf")}), 201)
        ok(market.post(f"/api/v1/documents/{document['id']}/verification", headers=editor_headers, json={
            "decision": "verified", "scope_category": product["category"], "scope_subcategory": product.get("subcategory"),
            "valid_until": (date.today()+timedelta(days=60)).isoformat(),
            "confirms": {key: [str(value)] for key, value in product["characteristics"].items()},
            "note": "Проверка только синтетического стенда по указанной спецификации"}))
        addresses = rows(ok(market.get(f"/api/v1/companies/{buyer}/addresses", headers=buyer_headers)))
        # API поддерживает точную классификацию. Общая категория формы проверяется
        # отдельно браузерным тестом; её блокировку нельзя скрывать этим сценарием.
        need = ok(market.post("/api/v1/needs", headers=buyer_headers, json={
            "company_id": buyer, "category": product["category"], "subcategory": product.get("subcategory"), "characteristics": product["characteristics"],
            "volume_units": 500, "budget_rub": 5000, "deadline_date": (date.today()+timedelta(days=30)).isoformat(),
            "delivery_address_id": addresses[0]["id"], "visibility": "open_anonymized",
        }), 201)
        ok(market.post(f"/api/v1/needs/{need['id']}/publish", headers=buyer_headers))
        offer = ok(market.post(f"/api/v1/needs/{need['id']}/offers", headers=seller_headers, json={
            "company_id": seller, "resource_kind": "stock", "product_id": product["id"],
            "commercial_terms": {"delivery_method": "separate", "tax_basis": "no_vat", "vat_rate_pct": None,
                                 "delivery_conditions": "Синтетический адрес получателя, Россия", "expenses": []},
            "price_rub": 5, "available_units": 500, "lead_time_days": 1, "delivery_cost_rub": 0, "moq_units": 500,
        }), 201)
        # Обязательство без согласия не создаётся.
        response = market.post(f"/api/v1/offers/{offer['id']}/select", headers=buyer_headers, json={"expected_revision": offer["revision"]})
        assert response.status_code in (400, 422, 428)
        deal = ok(market.post(f"/api/v1/offers/{offer['id']}/select", headers=buyer_headers,
            json={"expected_revision": offer["revision"], "human_approved": True}), 201)
        deal_id = deal["id"]
        assert Decimal(str(deal["total_price_rub"])) == Decimal("2500")
        expected = (date.today()+timedelta(days=5)).isoformat()
        proof = {"note": "Синтетический акт исполнения", "attachments": []}
        def perform(action, payload, company=buyer, headers=buyer_headers):
            current = ok(market.get(f"/api/v3/deals/{deal_id}/fulfillment?company_id={company}", headers=headers))
            command = {"company_id": company, "expected_revision": current["revision"], "terms_version": current["terms_version"],
                "human_approved": True, "idempotency_key": str(uuid.uuid4()), "action": action, "payload": payload}
            return ok(market.post(f"/api/v3/deals/{deal_id}/fulfillment", headers=headers, json=command)), command
        material_bytes = synthetic_pdf()
        material = ok(market.post(f"/api/v3/deals/{deal_id}/attachments", headers=seller_headers,
            data={"company_id": seller, "terms_version": "1"},
            files={"file": ("synthetic-act.pdf", material_bytes, "application/pdf")}), 201)
        downloaded = market.get(f"/api/v3/deals/{deal_id}/attachments/{material['id']}?company_id={buyer}", headers=buyer_headers)
        assert downloaded.status_code == 200 and downloaded.content == material_bytes
        perform("prepare", {**proof, "attachments": [material["id"]], "expected_date": expected, "address": "г. Москва, ул. Синтетическая, 1",
            "city": "Москва", "region": "Москва", "packaging": "Коробка", "weight_kg": 5, "volume_m3": 0.1, "places": 1}, seller, seller_headers)
        perform("production", {**proof, "expected_date": expected}, seller, seller_headers)
        perform("logistics", {**proof, "expected_date": expected, "method": "self_pickup", "cost_rub": "0.00"})
        shipped, _ = perform("shipment", {**proof, "expected_date": expected, "batch": "Партия крепежа", "units": 500}, seller, seller_headers)
        batch = shipped["batches"][0]["id"]
        perform("receipt", {**proof, "expected_date": expected, "batch_id": batch, "line_id": need["id"], "received": 300, "missing": 0})
        first, acceptance = perform("inspection", {**proof, "expected_date": expected, "batch_id": batch, "line_id": need["id"], "accepted": 300, "rejected": 0})
        repeated = ok(market.post(f"/api/v3/deals/{deal_id}/fulfillment", headers=buyer_headers, json=acceptance))
        assert repeated["revision"] == first["revision"] and repeated["totals"]["accepted_units"] == 300
        pending, _ = perform("request", {**proof, "kind": "return", "units": 50})
        request = pending["requests"][-1]["id"]
        agreed, _ = perform("decision", {**proof, "event_id": request, "approved": True}, seller, seller_headers)
        assert agreed["totals"]["returned_units"] == 0  # approval is not physical completion
        perform("return_complete", {**proof, "event_id": request, "restock_accepted": False}, seller, seller_headers)
        ok(market.put(f"/api/v1/deals/{deal_id}/costs", headers=seller_headers, json={
            "company_id": seller, "expected_revision": 0, "unit_cost_rub": "3.00", "attributable_expenses_rub": "100.00",
            "note": "Синтетическая смета", "tax_basis": "no_vat", "human_approved": True,
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
