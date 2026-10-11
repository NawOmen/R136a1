"""Этап 12: статистика закупок/продаж/прибыли и оценка работы агентов."""

import json
import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import pytest
from sqlalchemy import text

from app.models import (
    Coalition,
    CompatibilityProfile,
    Deal,
    DealCheckpoint,
    DealCostSnapshot,
    DealExecutionEvent,
    DeliveryAddress,
    DeliveryArrangement,
    GroupOffer,
    Need,
    Offer,
    ParticipantOrder,
    Product,
)
from conftest import make_company, make_marketplace_admin, make_token, make_user


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


async def _deal(db_session, *, buyer=None, seller=None, bc=None, seller_name=None, status="shipped",
                units=10, unit_price="1000", characteristics=None, category="Мебель", created_days_ago=0):
    buyer = buyer or await make_user(db_session)
    seller = seller or await make_user(db_session)
    bc = bc or await make_company(db_session, buyer, can_sell=False)
    sc = await make_company(db_session, seller, can_buy=False)
    if seller_name:
        await db_session.execute(text("UPDATE auth.companies SET display_name = :name WHERE id = :id"),
                                 {"name": seller_name, "id": sc})
    address = DeliveryAddress(company_id=bc, address="г. Москва, ул. Синтетическая, д. 1", city="Москва", region="Москва")
    db_session.add(address)
    await db_session.flush()
    need = Need(company_id=bc, created_by_user_id=buyer, category=category,
                characteristics={} if characteristics is None else characteristics, volume_units=units,
                budget_rub=20000, deadline_date=date.today() + timedelta(days=20),
                delivery_address_id=address.id, visibility="closed", status="matched")
    db_session.add(need)
    await db_session.flush()
    offer = Offer(need_id=need.id, company_id=sc, created_by_user_id=seller, price_rub=Decimal(unit_price),
                  available_units=units, lead_time_days=2, delivery_cost_rub=0, moq_units=1, price_tiers=[], status="selected")
    db_session.add(offer)
    await db_session.flush()
    deal = Deal(offer_id=offer.id, need_id=need.id, buyer_company_id=bc, seller_company_id=sc,
                units=units, total_price_rub=Decimal(unit_price) * units,
                unit_price_rub=Decimal(unit_price), delivery_price_rub=0, status=status)
    if created_days_ago:
        deal.created_at = datetime.now(timezone.utc) - timedelta(days=created_days_ago)
    db_session.add(deal)
    await db_session.flush()
    for kind in ("production", "shipment"):
        db_session.add(DealCheckpoint(deal_id=deal.id, kind=kind, status="completed"))
    db_session.add(DeliveryArrangement(deal_id=deal.id, weight_kg=100, volume_m3=0.5,
                                       cargo_class="small", classification_note="Тестовый способ получения",
                                       method="self_pickup", buyer_responsible=True,
                                       confirmed_by_user_id=buyer))
    await db_session.commit()
    return {"deal": deal, "need": need, "offer": offer, "buyer": buyer, "seller": seller, "bc": bc, "sc": sc}


async def _accept(db_session, ctx, units):
    db_session.add(DealExecutionEvent(
        deal_id=ctx["deal"].id, actor_company_id=ctx["bc"], actor_user_id=ctx["buyer"],
        idempotency_key=uuid.uuid4(), kind="acceptance", units=units,
        note="Приёмка по акту", status="confirmed",
        decided_by_user_id=ctx["buyer"], decided_at=datetime.now(timezone.utc)))
    await db_session.commit()


async def test_report_has_built_at_filters_and_basis(client, db_session):
    ctx = await _deal(db_session)
    await _accept(db_session, ctx, 10)
    r = await client.get(f"/api/v1/companies/{ctx['sc']}/commercial-analytics?role=seller",
                         headers=_auth(make_token(ctx["seller"])))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["period_basis"] == "order_created_at_utc"
    assert body["built_at"]
    assert body["filters"]["source"] == "all"
    assert body["orders_count"] == 1
    assert body["totals"]["net_goods_revenue_rub"] == 10000


async def test_average_price_single_unit_and_mixed_units(client, db_session):
    buyer = await make_user(db_session)
    bc = await make_company(db_session, buyer, can_sell=False)
    first = await _deal(db_session, buyer=buyer, bc=bc, units=10, unit_price="1000")
    await _accept(db_session, first, 10)
    second = await _deal(db_session, buyer=buyer, bc=bc, units=5, unit_price="2000",
                         characteristics={"unit": "комплект"})
    await _accept(db_session, second, 5)
    token = make_token(first["seller"])
    seller2_token = make_token(second["seller"])
    r = await client.get(f"/api/v1/companies/{first['sc']}/commercial-analytics?role=seller", headers=_auth(token))
    assert r.json()["average_prices"] == [{"unit": "шт", "accepted_units": 10, "average_unit_price_rub": 1000.0}]
    r = await client.get(f"/api/v1/companies/{second['sc']}/commercial-analytics?role=seller", headers=_auth(seller2_token))
    assert r.json()["average_prices"] == [{"unit": "комплект", "accepted_units": 5, "average_unit_price_rub": 2000.0}]


async def test_rejection_rate_cohort_and_empty(client, db_session):
    buyer = await make_user(db_session)
    seller = await make_user(db_session)
    bc = await make_company(db_session, buyer, can_sell=False)
    sc = await make_company(db_session, seller, can_buy=False)
    need = Need(company_id=bc, created_by_user_id=buyer, category="Мебель", characteristics={}, volume_units=4,
                budget_rub=4000, deadline_date=date.today() + timedelta(days=10), visibility="closed", status="open_for_offers")
    db_session.add(need)
    await db_session.flush()
    for i, offer_status in enumerate(("rejected", "selected", "sent", "stale")):
        db_session.add(Offer(need_id=need.id, company_id=sc, created_by_user_id=seller, price_rub=100,
                             available_units=4, lead_time_days=1, delivery_cost_rub=0, moq_units=1,
                             price_tiers=[], status=offer_status))
    await db_session.commit()
    r = await client.get(f"/api/v1/companies/{sc}/commercial-analytics?role=seller", headers=_auth(make_token(seller)))
    assert r.status_code == 200, r.text
    rate = r.json()["rejection_rate"]
    assert (rate["offers_total"], rate["rejected"], rate["selected"], rate["open"], rate["stale"]) == (4, 1, 1, 1, 1)
    assert rate["known_outcomes"] == 2
    assert rate["rate_pct"] == 50.0
    lonely = await make_user(db_session)
    lc = await make_company(db_session, lonely, can_buy=False, can_sell=True)
    r = await client.get(f"/api/v1/companies/{lc}/commercial-analytics?role=seller", headers=_auth(make_token(lonely)))
    assert r.json()["rejection_rate"]["rate_pct"] is None


async def test_filters_status_counterparty_product_source(client, db_session):
    ctx_a = await _deal(db_session, seller_name="Альфа Поставка", status="shipped")
    ctx_b = await _deal(db_session, buyer=ctx_a["buyer"], bc=ctx_a["bc"], seller_name="Бета Торг", status="created")
    token = make_token(ctx_a["buyer"])
    base = f"/api/v1/companies/{ctx_a['bc']}/commercial-analytics?role=buyer"
    assert (await client.get(base, headers=_auth(token))).json()["orders_count"] == 2
    assert (await client.get(base + "&status=shipped", headers=_auth(token))).json()["orders_count"] == 1
    assert (await client.get(base + "&counterparty=альфа", headers=_auth(token))).json()["orders_count"] == 1
    assert (await client.get(base + "&counterparty=отсутствует", headers=_auth(token))).json()["orders_count"] == 0
    assert (await client.get(base + "&source=group", headers=_auth(token))).json()["orders_count"] == 0
    assert (await client.get(base + "&source=bogus", headers=_auth(token))).status_code == 422
    product = Product(company_id=ctx_a["sc"], created_by_user_id=ctx_a["seller"], name="Уникальный табурет П-1",
                      category="Мебель", characteristics={}, price_rub=100, price_tiers=[], moq_units=1, lead_time_days=1)
    db_session.add(product)
    await db_session.flush()
    ctx_a["offer"].product_id = product.id
    await db_session.commit()
    assert (await client.get(base + "&product=табурет", headers=_auth(token))).json()["orders_count"] == 1
    assert (await client.get(base + "&product=диван", headers=_auth(token))).json()["orders_count"] == 0


async def test_group_orders_do_not_double_revenue(client, db_session):
    ctx = await _deal(db_session)
    await _accept(db_session, ctx, 10)
    profile = CompatibilityProfile(category="Мебель", input_hash=uuid.uuid4().hex)
    db_session.add(profile)
    await db_session.flush()
    coalition = Coalition(compatibility_profile_id=profile.id, producer_company_id=ctx["sc"],
                          category="Мебель", combined_volume_units=10)
    db_session.add(coalition)
    await db_session.flush()
    group_offer = GroupOffer(coalition_id=coalition.id, company_id=ctx["sc"])
    db_session.add(group_offer)
    await db_session.flush()
    db_session.add(ParticipantOrder(coalition_id=coalition.id, group_offer_id=group_offer.id, need_id=ctx["need"].id,
                                    buyer_company_id=ctx["bc"], seller_company_id=ctx["sc"],
                                    units=10, total_price_rub=Decimal("10000"), status="created"))
    await db_session.commit()
    r = await client.get(f"/api/v1/companies/{ctx['sc']}/commercial-analytics?role=seller",
                         headers=_auth(make_token(ctx["seller"])))
    body = r.json()
    assert body["group_orders_count"] == 1
    assert body["totals"]["net_goods_revenue_rub"] == 10000
    r = await client.get(f"/api/v1/companies/{ctx['sc']}/commercial-analytics?role=seller&source=direct",
                         headers=_auth(make_token(ctx["seller"])))
    assert r.json()["group_orders_count"] == 0


async def test_csv_matches_screen_injection_safe_and_guarded(client, db_session):
    ctx = await _deal(db_session, category="=ГИПЕРССЫЛКА(1)")
    await _accept(db_session, ctx, 10)
    token = make_token(ctx["seller"])
    screen = (await client.get(f"/api/v1/companies/{ctx['sc']}/commercial-analytics?role=seller",
                               headers=_auth(token))).json()
    r = await client.get(f"/api/v1/companies/{ctx['sc']}/commercial-report.csv?role=seller", headers=_auth(token))
    assert r.status_code == 200, r.text
    assert "attachment" in r.headers["content-disposition"]
    text = r.text
    assert text.count("Прямой") == screen["orders_count"] == 1
    assert "\"'=ГИПЕРССЫЛКА(1)" in text
    assert "Итого по отчёту" in text
    assert str(ctx["deal"].id) in text
    assert "Отчёт сформирован (UTC)" in text
    stranger = await make_user(db_session)
    assert (await client.get(f"/api/v1/companies/{ctx['sc']}/commercial-report.csv?role=seller",
                             headers=_auth(make_token(stranger)))).status_code in (403, 404)
    buyer_token = make_token(ctx["buyer"])
    r = await client.get(f"/api/v1/companies/{ctx['bc']}/commercial-report.csv?role=buyer", headers=_auth(buyer_token))
    assert r.status_code == 200
    assert "Себестоимость" not in r.text


async def test_cost_tax_basis_roundtrip_and_privacy(client, db_session):
    ctx = await _deal(db_session)
    await _accept(db_session, ctx, 6)
    seller_token = make_token(ctx["seller"])
    r = await client.put(f"/api/v1/deals/{ctx['deal'].id}/costs", headers=_auth(seller_token),
                         json={"company_id": str(ctx["sc"]), "expected_revision": 0,
                               "unit_cost_rub": "600.00", "attributable_expenses_rub": "500.00",
                               "tax_basis": "no_vat", "note": "Калькуляция цеха № 3", "human_approved": True})
    assert r.status_code == 200, r.text
    r = await client.get(f"/api/v1/deals/{ctx['deal'].id}/execution?company_id={ctx['sc']}", headers=_auth(seller_token))
    assert r.json()["cost_tax_basis"] == "no_vat"
    assert r.json()["financials"]["gross_profit_rub"] == 2400.0
    assert r.json()["financials"]["contribution_rub"] == 1900.0
    buyer_token = make_token(ctx["buyer"])
    r = await client.get(f"/api/v1/deals/{ctx['deal'].id}/execution?company_id={ctx['bc']}", headers=_auth(buyer_token))
    assert "cost_tax_basis" not in r.json()
    assert "gross_profit_rub" not in r.json()["financials"]
    r = await client.get(f"/api/v1/companies/{ctx['sc']}/commercial-analytics?role=seller", headers=_auth(seller_token))
    row = [o for o in r.json()["orders"] if o["deal_id"] == str(ctx["deal"].id)][0]
    assert row["cost_tax_basis"] == "no_vat"
    assert row["cost_of_goods_rub"] == 3600.0


async def test_catalog_price_change_does_not_rewrite_history(client, db_session):
    ctx = await _deal(db_session)
    await _accept(db_session, ctx, 10)
    token = make_token(ctx["seller"])
    before = (await client.get(f"/api/v1/companies/{ctx['sc']}/commercial-analytics?role=seller",
                               headers=_auth(token))).json()["totals"]
    product = Product(company_id=ctx["sc"], created_by_user_id=ctx["seller"], name="Стул",
                      category="Мебель", characteristics={}, price_rub=100, price_tiers=[], moq_units=1, lead_time_days=1)
    db_session.add(product)
    await db_session.commit()
    product.price_rub = 9999
    await db_session.commit()
    after = (await client.get(f"/api/v1/companies/{ctx['sc']}/commercial-analytics?role=seller",
                              headers=_auth(token))).json()["totals"]
    assert before == after


async def test_old_order_accepted_today_stays_in_old_period(client, db_session):
    ctx = await _deal(db_session, created_days_ago=40)
    await _accept(db_session, ctx, 10)
    token = make_token(ctx["seller"])
    old_start = (date.today() - timedelta(days=60)).isoformat()
    old_end = (date.today() - timedelta(days=30)).isoformat()
    body = (await client.get(
        f"/api/v1/companies/{ctx['sc']}/commercial-analytics?role=seller&start={old_start}&end={old_end}",
        headers=_auth(token))).json()
    assert body["orders_count"] == 1
    assert body["built_at"] >= body["orders"][0]["created_at"]
    fresh = (await client.get(f"/api/v1/companies/{ctx['sc']}/commercial-analytics?role=seller",
                              headers=_auth(token))).json()
    assert fresh["orders_count"] == 1
    assert "прошлом периоде" in fresh["explanation"]


async def test_scorecard_empty_denominator_none_and_buyer_access(client, db_session):
    buyer = await make_user(db_session)
    bc = await make_company(db_session, buyer, can_sell=False)
    r = await client.get(f"/api/v1/companies/{bc}/agent-scorecard", headers=_auth(make_token(buyer)))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["offer_draft_conversion_pct"] is None
    assert body["recommendation_conversion_pct"] is None
    stranger = await make_user(db_session)
    assert (await client.get(f"/api/v1/companies/{bc}/agent-scorecard",
                             headers=_auth(make_token(stranger)))).status_code in (403, 404)


@pytest.fixture
async def agents_ledger(db_session):
    # Журнал прогонов принадлежит LLM Gateway: таблица может уже существовать
    # (миграции сервиса или соседние тесты) в минимальной или полной форме.
    # Только добавляем недостающие колонки и чистим свои строки; DDL не удаляем.
    await db_session.execute(text("CREATE SCHEMA IF NOT EXISTS agents"))
    await db_session.execute(text(
        "CREATE TABLE IF NOT EXISTS agents.agent_runs (id UUID PRIMARY KEY, revision INTEGER NOT NULL DEFAULT 1, "
        "state TEXT NOT NULL, result JSONB NOT NULL DEFAULT '{}', user_id UUID NOT NULL, company_id UUID)"))
    for ddl in (
        "ALTER TABLE agents.agent_runs ADD COLUMN IF NOT EXISTS agent_type VARCHAR(64)",
        "ALTER TABLE agents.agent_runs ADD COLUMN IF NOT EXISTS requested_route VARCHAR(32) DEFAULT 'local'",
        "ALTER TABLE agents.agent_runs ADD COLUMN IF NOT EXISTS used_route VARCHAR(32)",
        "ALTER TABLE agents.agent_runs ADD COLUMN IF NOT EXISTS model_version VARCHAR(120)",
        "ALTER TABLE agents.agent_runs ADD COLUMN IF NOT EXISTS prompt_version VARCHAR(64)",
        "ALTER TABLE agents.agent_runs ADD COLUMN IF NOT EXISTS input_summary TEXT DEFAULT ''",
        "ALTER TABLE agents.agent_runs ADD COLUMN IF NOT EXISTS error TEXT",
        "ALTER TABLE agents.agent_runs ADD COLUMN IF NOT EXISTS duration_ms INTEGER",
        "ALTER TABLE agents.agent_runs ADD COLUMN IF NOT EXISTS estimated_cost_rub NUMERIC(24,12)",
        "ALTER TABLE agents.agent_runs ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ DEFAULT now()",
    ):
        await db_session.execute(text(ddl))
    await db_session.execute(text(
        "CREATE TABLE IF NOT EXISTS agents.tool_calls (id UUID PRIMARY KEY, run_id UUID NOT NULL, "
        "tool_name VARCHAR(120), status VARCHAR(32), input_summary TEXT DEFAULT '', "
        "output_summary TEXT DEFAULT '', created_at TIMESTAMPTZ DEFAULT now())"))
    await db_session.commit()
    created: list = []
    yield created
    if created:
        await db_session.execute(text("DELETE FROM agents.tool_calls WHERE run_id = ANY(:ids)"), {"ids": created})
        await db_session.execute(text("DELETE FROM agents.agent_runs WHERE id = ANY(:ids)"), {"ids": created})
        await db_session.commit()


async def _agent_run(db_session, created, user, company, agent_type, result, **overrides):
    values = {"id": uuid.uuid4(), "user_id": user, "company_id": company, "agent_type": agent_type,
              "state": "confirmed_by_user", "requested_route": "local", "input_summary": "",
              "used_route": "local", "model_version": "qwen3.5:9b",
              "prompt_version": "buyer-extraction-1", "result": json.dumps(result, ensure_ascii=False),
              "error": None, "duration_ms": 1200, "estimated_cost_rub": "0.05"}
    values.update(overrides)
    await db_session.execute(text(
        "INSERT INTO agents.agent_runs (id, revision, user_id, company_id, agent_type, state, requested_route, input_summary, "
        "used_route, model_version, prompt_version, result, error, duration_ms, estimated_cost_rub) VALUES "
        "(:id, 1, :user_id, :company_id, :agent_type, :state, :requested_route, :input_summary, :used_route, "
        ":model_version, :prompt_version, CAST(:result AS jsonb), :error, :duration_ms, "
        "CAST(:estimated_cost_rub AS numeric))"), values)
    await db_session.commit()
    created.append(values["id"])
    return values["id"]


async def test_role_quality_gates_scoping_and_versions(client, db_session, agents_ledger):
    buyer = await make_user(db_session)
    bc = await make_company(db_session, buyer, can_sell=False)
    token = make_token(buyer)
    result = {"properties": [{"status": "confirmed"}, {"status": "confirmed"}, {"status": "needs_clarification"}],
              "conflicts": [{"key": "material"}]}
    run_id = await _agent_run(db_session, agents_ledger, buyer, bc, "buyer_agent", result)
    await db_session.execute(text(
        "INSERT INTO agents.tool_calls (id, run_id, tool_name, status, input_summary, output_summary) VALUES "
        "(gen_random_uuid(), :rid, 'apply_user_clarification', 'success', '', '')"),
        {"rid": run_id})
    await db_session.commit()
    body = (await client.get(f"/api/v1/companies/{bc}/role-quality", headers=_auth(token))).json()
    assert body["method_version"] == "role-quality-1"
    assert body["min_observations"] == 5
    assert "single_score" not in body and "score" not in body["roles"][0]
    role = [x for x in body["roles"] if x["role"] == "buyer_agent"][0]
    assert role["status"] == "not_evaluated"
    assert role["completed_share_pct"] is None
    assert role["critical_completeness_pct"] is None
    assert body["benchmark"]["bank"].endswith("ru_tasks.json")
    for _ in range(4):
        await _agent_run(db_session, agents_ledger, buyer, bc, "buyer_agent", result)
    body = (await client.get(f"/api/v1/companies/{bc}/role-quality", headers=_auth(token))).json()
    role = [x for x in body["roles"] if x["role"] == "buyer_agent"][0]
    assert role["status"] == "evaluated"
    assert role["sample"] == 5
    assert role["completed_share_pct"] == 100.0
    assert role["critical_completeness_pct"] == 66.7
    assert role["conflicts_found"] == 5
    assert role["clarification_runs"] == 1
    assert role["model_versions"] == ["qwen3.5:9b"]
    assert role["prompt_versions"] == ["buyer-extraction-1"]
    other = await make_user(db_session)
    oc = await make_company(db_session, other, can_sell=False)
    body = (await client.get(f"/api/v1/companies/{oc}/role-quality", headers=_auth(make_token(other)))).json()
    assert body["roles"] == []
    admin = await make_marketplace_admin(db_session)
    body = (await client.get("/api/v1/platform/role-quality", headers=_auth(make_token(admin)))).json()
    # Платформа видит все компании, включая строки соседних тестов той же базы:
    # проверяем нижнюю границу и наличие наших версий, а не точное равенство.
    platform_role = [x for x in body["roles"] if x["role"] == "buyer_agent"][0]
    assert platform_role["sample"] >= 5
    assert "qwen3.5:9b" in platform_role["model_versions"]
    stranger = await make_user(db_session)
    assert (await client.get(f"/api/v1/companies/{bc}/role-quality",
                             headers=_auth(make_token(stranger)))).status_code in (403, 404)


async def test_scorecard_model_versions_and_unknown_cost(client, db_session, agents_ledger):
    seller = await make_user(db_session)
    sc = await make_company(db_session, seller, can_buy=False)
    await _agent_run(db_session, agents_ledger, seller, sc, "seller_agent", {"eligible": True}, prompt_version="seller-explain-1",
                     model_version="qwen3.5:9b", estimated_cost_rub=None)
    body = (await client.get(f"/api/v1/companies/{sc}/agent-scorecard", headers=_auth(make_token(seller)))).json()
    assert body["agent_model_versions"] == ["qwen3.5:9b"]
    assert body["agent_prompt_versions"] == ["seller-explain-1"]
    assert body["offer_draft_conversion_pct"] is None
