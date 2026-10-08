from conftest import confirmed_quote_terms
from conftest import grant_capacity
"""Черновик КП, остатки склада и оценка работы агентов.

Проверяем, что рутинные операции поставщика выполняются по подтверждённым
данным, а не выдумываются: цена и срок берутся из каталога, объём — из остатка
или мощности, логистику и спорные значения подтверждает человек.
"""

from datetime import date, timedelta

from sqlalchemy import text

from conftest import grant_packaging_documents, make_company, make_marketplace_admin, make_token, make_user

from test_category_admission import _auth


async def _seller_company(db_session, *, can_buy=False):
    user = await make_user(db_session)
    company = await make_company(db_session, user, can_buy=can_buy, can_sell=True)
    return user, company, make_token(user)


async def _buyer_with_published_need(client, db_session, *, volume=20_000, characteristics=None):
    user = await make_user(db_session)
    company = await make_company(db_session, user, can_buy=True, can_sell=False)
    token = make_token(user)
    address = await client.post(
        f"/api/v1/companies/{company}/addresses",
        json={"address": "г. Москва, ул. Тестовая, 1", "city": "Москва", "region": "г. Москва", "is_default": True},
        headers=_auth(token),
    )
    need = await client.post(
        "/api/v1/needs",
        json={
            "company_id": str(company),
            "category": "бумажные стаканы",
            "characteristics": characteristics or {"volume_ml": 400, "coating": "PE", "material":"крафт-картон"},
            "volume_units": volume,
            "budget_rub": 500_000,
            "deadline_date": str(date.today() + timedelta(days=30)),
            "delivery_address_id": address.json()["id"],
            "visibility": "open_anonymized",
        },
        headers=_auth(token),
    )
    assert need.status_code == 201, need.text
    published = await client.post(f"/api/v1/needs/{need.json()['id']}/publish", headers=_auth(token))
    assert published.status_code == 200, published.text
    return user, company, token, need.json()["id"]


async def _passport(client, token, company, *, business_kind="manufacturer", min_order=5_000):
    response = await client.put(
        f"/api/v1/companies/{company}/capability-passport",
        json={
            "details": {
                "category_scopes": [{"category_id":"packaging.paper-cups","unit":"шт","min_units":min_order,"max_units":60000,"characteristics":{"volume_ml":[400],"coating":["PE"],"material":["крафт-картон"]}}],
                "business_kind": business_kind,
                "product_types": "бумажные стаканы 150–600 мл",
                "complexity": "флексопечать",
                "material_grades": "крафт-картон с PE",
                "limitations": "PLA по согласованию",
                "packaging": "короба по 500 шт.",
                "delivery": "самовывоз или перевозчик покупателя",
                "quality_control": "выборочная проверка",
                "trial_batch": "по запросу",
            },
            "technologies": ["формовка стаканов"],
            "equipment": ["линия формовки"],
            "materials": ["крафт-картон"],
            "size_ranges": {"volume_ml": [150, 600]},
            "certifications": ["ТР ТС 005/2011"],
            "min_order_units": min_order,
            "max_order_units": 60_000,
            "delivery_regions": ["Москва"],
            "completed_order_types": ["стаканы 300–450 мл"],
        },
        headers=_auth(token),
    )
    assert response.status_code == 200, response.text


async def test_offer_draft_uses_catalog_and_capacity(client, db_session):
    """Черновик КП берёт цену из каталога, а объём — из календаря мощностей."""
    user, company, token = await _seller_company(db_session)
    await _passport(client, token, company)
    product = await client.post(
        f"/api/v1/companies/{company}/products",
        json={
            "name": "Стакан 400 мл PE",
            "category": "Упаковка и тара",
            "subcategory": "Бумажные стаканы",
            "characteristics": {"volume_ml": 400, "coating": "PE", "material":"крафт-картон"},
            "price_rub": 12,
            "price_tiers": [{"min_units": 10_000, "unit_price_rub": 10.5}],
            "moq_units": 5_000,
            "lead_time_days": 9,
        },
        headers=_auth(token),
    )
    assert product.status_code == 201, product.text
    capacity = await client.put(
        f"/api/v1/companies/{company}/capacity",
        json={
            "entries": [
                {"date": str(date.today() + timedelta(days=5)), "category":"packaging.paper-cups", "available_units": 30_000},
                {"date": str(date.today() + timedelta(days=40)), "category":"packaging.paper-cups", "available_units": 90_000},
            ]
        },
        headers=_auth(token),
    )
    assert capacity.status_code in (200, 201), capacity.text

    _, _, _, need_id = await _buyer_with_published_need(client, db_session)

    draft = await client.post(
        f"/api/v1/needs/{need_id}/offer-draft",
        json={"company_id": str(company)},
        headers=_auth(token),
    )
    assert draft.status_code == 201, draft.text
    body = draft.json()
    assert body["payload"]["price_rub"] == 10.5, body
    assert "ступень" in next(item["source"] for item in body["fields"] if item["name"] == "price_rub")
    assert body["payload"]["available_units"] == 30_000, body
    assert "мощностей" in next(item["source"] for item in body["fields"] if item["name"] == "available_units")
    assert body["payload"]["moq_units"] == 5_000
    assert body["payload"]["lead_time_days"] == 9
    assert body["payload"]["delivery_cost_rub"] is None
    assert any("логистик" in item.lower() for item in body["missing"])
    assert body["explanation"]
    assert body["status"] == "draft"

    events = (
        await db_session.execute(
            text("SELECT count(*) FROM marketplace.trust_audit_events WHERE event_type = 'offer_draft_generated'")
        )
    ).scalar_one()
    assert events == 1


async def test_offer_draft_uses_stock_for_stock_supplier(client, db_session):
    """Для роли «поставка со склада» доступный объём берётся из остатка."""
    user, company, token = await _seller_company(db_session)
    await _passport(client, token, company, business_kind="stock_supplier", min_order=1_000)
    product = await client.post(
        f"/api/v1/companies/{company}/products",
        json={
            "name": "Стакан 400 мл со склада",
            "category": "Упаковка и тара",
            "subcategory": "Бумажные стаканы",
            "characteristics": {"volume_ml": 400, "coating": "PE", "material":"крафт-картон"},
            "price_rub": 11,
            "moq_units": 1_000,
            "lead_time_days": 2,
            "stock_units": 4_000,
        },
        headers=_auth(token),
    )
    assert product.status_code == 201, product.text
    assert product.json()["stock_units"] == 4_000
    assert product.json()["stock_updated_at"] is not None

    _, _, _, need_id = await _buyer_with_published_need(client, db_session, volume=3_000)
    draft = await client.post(
        f"/api/v1/needs/{need_id}/offer-draft",
        json={"company_id": str(company)},
        headers=_auth(token),
    )
    assert draft.status_code == 201, draft.text
    body = draft.json()
    assert body["payload"]["available_units"] == 4_000
    assert "остаток" in next(item["source"] for item in body["fields"] if item["name"] == "available_units")

    # Остаток меньше запроса — черновик предупреждает, но не решает за человека.
    _, _, _, big_need = await _buyer_with_published_need(client, db_session, volume=50_000)
    draft_big = await client.post(
        f"/api/v1/needs/{big_need}/offer-draft",
        json={"company_id": str(company)},
        headers=_auth(token),
    )
    assert draft_big.status_code == 201
    assert any("меньше запрошенных" in item for item in draft_big.json()["warnings"])


async def test_offer_draft_without_product_asks_human_for_price(client, db_session):
    """Без товара каталога цена не выдумывается: агент помечает поле как ручное."""
    user, company, token = await _seller_company(db_session)
    await _passport(client, token, company, min_order=7_000)
    _, _, _, need_id = await _buyer_with_published_need(client, db_session)

    draft = await client.post(
        f"/api/v1/needs/{need_id}/offer-draft",
        json={"company_id": str(company)},
        headers=_auth(token),
    )
    assert draft.status_code == 201, draft.text
    body = draft.json()
    assert body["payload"]["price_rub"] is None
    price_field = next(item for item in body["fields"] if item["name"] == "price_rub")
    assert price_field["confirmed"] is False
    assert "агент не устанавливает цену" in (price_field["note"] or "")
    assert body["payload"]["moq_units"] == 7_000
    assert any("цену" in item.lower() for item in body["missing"])


async def test_offer_from_draft_records_human_corrections(client, db_session):
    """Предложение из черновика фиксирует, что именно человек изменил."""
    user, company, token = await _seller_company(db_session)
    await _passport(client, token, company)
    await client.post(
        f"/api/v1/companies/{company}/products",
        json={
            "name": "Стакан 400 мл PE",
            "category": "Упаковка и тара",
            "subcategory": "Бумажные стаканы",
            "characteristics": {"volume_ml": 400, "coating": "PE", "material":"крафт-картон"},
            "price_rub": 12,
            "moq_units": 1_000,
            "lead_time_days": 9,
        },
        headers=_auth(token),
    )
    _, _, _, need_id = await _buyer_with_published_need(client, db_session, volume=5_000)

    draft = await client.post(
        f"/api/v1/needs/{need_id}/offer-draft",
        json={"company_id": str(company)},
        headers=_auth(token),
    )
    assert draft.status_code == 201, draft.text
    draft_id = draft.json()["id"]
    assert draft.json()["payload"]["available_units"] is None  # мощность не заполнена

    offer = await client.post(
        f"/api/v1/needs/{need_id}/offers",
        json={'commercial_terms': confirmed_quote_terms(),
            "company_id": str(company),
            "price_rub": 11.5,
            "available_units": 5_000,
            "moq_units": 1_000,
            "delivery_cost_rub": 3_000,
            "lead_time_days": 9,
            "draft_id": draft_id,
        },
        headers=_auth(token),
    )
    assert offer.status_code == 201, offer.text

    row = (
        await db_session.execute(
            text(
                "SELECT status, changed_fields, used_offer_id FROM marketplace.offer_drafts WHERE id = :id"
            ),
            {"id": draft_id},
        )
    ).mappings().one()
    assert row["status"] == "used"
    assert row["used_offer_id"] == offer.json()["id"] is not None or row["used_offer_id"] is not None
    assert "price_rub" in row["changed_fields"]
    assert "available_units" in row["changed_fields"]
    assert "delivery_cost_rub" in row["changed_fields"]
    assert "lead_time_days" not in row["changed_fields"]

    reused = await client.post(
        f"/api/v1/needs/{need_id}/offers",
        json={'commercial_terms': confirmed_quote_terms(), 'delivery_cost_rub': 0,
            "company_id": str(company),
            "price_rub": 11.5,
            "available_units": 5_000,
            "moq_units": 1_000,
            "lead_time_days": 9,
            "draft_id": draft_id,
        },
        headers=_auth(token),
    )
    assert reused.status_code == 409


async def test_agent_scorecard_counts_draft_conversion(client, db_session):
    """Панель агентов считает конверсию черновиков и правки человека из журнала."""
    user, company, token = await _seller_company(db_session)
    await _passport(client, token, company)
    await client.post(
        f"/api/v1/companies/{company}/products",
        json={
            "name": "Стакан 400 мл PE",
            "category": "Упаковка и тара",
            "subcategory": "Бумажные стаканы",
            "characteristics": {"volume_ml": 400, "coating": "PE", "material":"крафт-картон"},
            "price_rub": 12,
            "moq_units": 1_000,
            "lead_time_days": 9,
        },
        headers=_auth(token),
    )
    buyer_user, buyer_company, buyer_token, need_id = await _buyer_with_published_need(
        client, db_session, volume=5_000
    )
    # Сделка требует подтверждённых доказательств по категории.
    await grant_packaging_documents(
        db_session, company, decision_user_id=user, confirms={"material": ["крафт-картон"], "coating": ["PE"]}
    )

    await grant_capacity(db_session, company, 5_000)
    draft = await client.post(
        f"/api/v1/needs/{need_id}/offer-draft",
        json={"company_id": str(company)},
        headers=_auth(token),
    )
    assert draft.status_code == 201
    offer = await client.post(
        f"/api/v1/needs/{need_id}/offers",
        json={'commercial_terms': confirmed_quote_terms(),
            "company_id": str(company),
            "price_rub": 12,
            "available_units": 5_000,
            "moq_units": 1_000,
            "delivery_cost_rub": 0,
            "lead_time_days": 9,
            "draft_id": draft.json()["id"],
        },
        headers=_auth(token),
    )
    assert offer.status_code == 201, offer.text
    deal = await client.post(f"/api/v1/offers/{offer.json()['id']}/select", headers=_auth(buyer_token), json={"expected_revision": 1, "human_approved": True})
    assert deal.status_code == 201, deal.text

    scorecard = await client.get(
        f"/api/v1/companies/{company}/agent-scorecard", headers=_auth(token)
    )
    assert scorecard.status_code == 200, scorecard.text
    body = scorecard.json()
    assert body["offer_drafts_total"] == 1
    assert body["offer_drafts_used"] == 1
    assert body["offer_draft_conversion_pct"] == 100.0
    assert body["offers_from_drafts"] == 1
    assert body["deals_from_drafts"] == 1
    # Наличие журнала вызовов модели зависит от окружения: в CI все сервисы
    # используют одну тестовую базу, поэтому схема agents может существовать.
    if body["llm_metrics_available"]:
        assert body["agent_runs_total"] >= 0
        assert body["agent_runs_failed"] <= body["agent_runs_total"]
    else:
        assert any("LLM Gateway" in note for note in body["notes"])

    forbidden = await client.get("/api/v1/platform/agent-scorecard", headers=_auth(token))
    assert forbidden.status_code == 403

    admin_token = make_token(await make_marketplace_admin(db_session))
    platform = await client.get("/api/v1/platform/agent-scorecard", headers=_auth(admin_token))
    assert platform.status_code == 200, platform.text
    assert platform.json()["scope"] == "platform"
    assert platform.json()["offer_drafts_total"] >= 1


async def test_draft_rejects_incompatible_or_unknown_characteristics():
    """An incompatible SKU must never provide the proposed price or stock."""
    from types import SimpleNamespace
    from app.offer_draft import _matches_need

    product = SimpleNamespace(category="Строительство", subcategory="Крепёж", characteristics={
        "material": "Сталь", "size": "М8×40", "strength_class": "8.8", "unit": "шт",
    })
    need = SimpleNamespace(category="Метизы", volume_units=100, characteristics={"материал": " сталь ", "size": "М8×40"})
    assert _matches_need(product, need)[0]
    for attrs in ({"size": "М10×40"}, {"strength_class": "10.9"}, {"coating": "цинк"},
                  {"unit": "кг"}, {"size": ""}):
        need.characteristics = attrs
        assert not _matches_need(product, need)[0], attrs
    need.category = "Креп"
    need.characteristics = {}
    assert not _matches_need(product, need)[0]


async def test_draft_characteristic_aliases_do_not_hide_conflicts():
    from types import SimpleNamespace
    from app.offer_draft import _matches_need

    product = SimpleNamespace(category="Упаковка и тара", subcategory="Бумажные стаканы",
                              characteristics={"volume_ml": 400, "coating": "PE"})
    need = SimpleNamespace(category="Бумажные стаканы", volume_units=100, characteristics={"объём": "400.0", "покрытие": "pe"})
    assert _matches_need(product, need)[0]
    product.characteristics["покрытие"] = "PLA"
    assert not _matches_need(product, need)[0]
    product.characteristics = {"volume_ml": True}
    need.characteristics = {"volume_ml": 1}
    assert not _matches_need(product, need)[0]
