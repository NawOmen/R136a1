"""Этап S09: подтверждённый резерв, конкретные отказы, симуляция и активация.

Проверяем приёмку: истёкший/неподтверждённый/занятый резерв не используется;
N-2 без решения честно показан; симуляция не пишет продажи; отказ фиксируется
с причиной и новой ревизией без потери поставщика; активация атомарна,
идемпотентна и не переносит принятое.
"""
import asyncio
import uuid
from datetime import date, timedelta

from sqlalchemy import select

from app.models import Deal, DealExecutionEvent, Need, Offer, OptimizationVariantRecord
from conftest import confirmed_quote_terms, grant_capacity, grant_packaging_documents, make_company, make_token, make_user

from test_category_admission import _auth


def auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def live_scenario(failed, covered, total, uncovered=0, unconfirmed=0):
    return {
        "scenario_type": "n1",
        "failed_company_ids": failed,
        "failed_units": covered + uncovered,
        "replacement_allocations": [],
        "baseline_total_cost_rub": total,
        "new_total_cost_rub": total if not uncovered else None,
        "price_delta_rub": 0 if not uncovered else None,
        "price_delta_pct": 0 if not uncovered else None,
        "baseline_lead_time_days": 10,
        "new_lead_time_days": 10,
        "delay_days": 0,
        "uncovered_units": uncovered,
        "confirmed_covered_units": covered,
        "unconfirmed_units": unconfirmed,
        "auto_eligible": False,
        "requires_human_approval": True,
        "solver_status": "optimal",
        "explanations": ["синтетический сценарий"],
    }


async def covered_resilience(monkeypatch):
    from itertools import combinations

    async def fake(payload):
        import os
        if os.environ.get("TEST_OPTIMIZER_URL"):
            from httpx import AsyncClient
            from app.money import exact_json, money_values
            async with AsyncClient() as http:
                response = await http.post(os.environ["TEST_OPTIMIZER_URL"] + "/api/v2/optimize/resilience",
                    headers={"X-Optimizer-Token": os.environ["OPTIMIZER_TOKEN"]}, json=exact_json(payload))
                response.raise_for_status()
                return money_values(response.json())
        from app.money import decimal, amount
        scenarios = []
        primary = payload["primary_allocations"]
        baseline = sum(decimal(row["frozen_total_cost_rub"]) if row.get("frozen_total_cost_rub") is not None else amount(decimal(row["unit_price_rub"]) * row["units"] + decimal(row["delivery_cost_rub"])
            + decimal(row.get("additional_cost_rub", 0))) for row in primary) + decimal(payload.get("reserve_holding_total_rub", 0))
        for size in (1, 2):
            for group in combinations(primary, size):
                demand = sum(row["units"] - row.get("protected_units", 0) for row in group)
                missing = demand
                allocations = []
                for option in sorted(payload["reserve_options"], key=lambda row: (row["reserve_tier"] != "hot", decimal(row["unit_price_rub"]), row["company_id"])):
                    units = min(missing, option["capacity_units"])
                    if not units or units < option["moq_units"]: continue
                    known = option.get("switchover_days") is not None
                    confirmed = option["reserve_tier"] == "hot" and option["confirmation_status"] == "approved" and known
                    allocations.append({"company_id": option["company_id"], "units": units,
                        "unit_price_rub": option["unit_price_rub"], "delivery_cost_rub": option["delivery_cost_rub"],
                        "additional_cost_rub": option["additional_cost_rub"],
                        "total_cost_rub": amount(decimal(option["unit_price_rub"]) * units + decimal(option["delivery_cost_rub"]) + decimal(option["additional_cost_rub"])),
                        "lead_time_days": option["lead_time_days"] + (option.get("switchover_days") or 0),
                        "reserve_tier": option["reserve_tier"], "confirmed": confirmed, "lead_time_known": known})
                    missing -= units
                    if not missing: break
                scenario = live_scenario([row["company_id"] for row in group], demand - missing, baseline, uncovered=missing)
                scenario["scenario_type"] = "n1" if size == 1 else "n2"
                scenario["replacement_allocations"] = allocations
                scenario["unconfirmed_units"] = sum(row["units"] for row in allocations if not row["confirmed"])
                scenario["confirmed_covered_units"] = sum(row["units"] for row in allocations if row["confirmed"])
                lost = sum(decimal(row["unit_price_rub"]) * (row["units"] - row.get("protected_units", 0))
                    + (decimal(row["delivery_cost_rub"]) + decimal(row.get("additional_cost_rub", 0)) if not row.get("protected_units") else 0) for row in group)
                total = amount(baseline - lost + sum(row["total_cost_rub"] for row in allocations))
                scenario["new_total_cost_rub"] = total if not missing else None
                scenario["price_delta_rub"] = amount(total - baseline) if not missing else None
                scenario["price_delta_pct"] = float((total - baseline) / baseline * 100) if not missing and baseline else None
                scenario["new_lead_time_days"] = max([row["lead_time_days"] for row in allocations] + [row["lead_time_days"] for row in primary if row not in group or row.get("protected_units")], default=0)
                scenario["baseline_lead_time_days"] = max(row["lead_time_days"] for row in primary)
                scenario["delay_days"] = max(0, scenario["new_lead_time_days"] - scenario["baseline_lead_time_days"])
                scenario["cost_comparison_applicable"] = not missing
                scenario["auto_eligible"] = (not missing and not scenario["unconfirmed_units"] and
                    (scenario["price_delta_pct"] or 0) <= payload["max_price_increase_pct"] and scenario["delay_days"] <= payload["max_delay_days"])
                scenario["requires_human_approval"] = not scenario["auto_eligible"]
                scenarios.append(scenario)
        return {"scenarios": scenarios, "n1_fully_covered": all(not row["uncovered_units"] and not row["unconfirmed_units"] for row in scenarios if row["scenario_type"] == "n1"),
                "n2_fully_covered": all(not row["uncovered_units"] and not row["unconfirmed_units"] for row in scenarios if row["scenario_type"] == "n2"), "confirmed_coverage_pct": 100, "input_hash": "s09"}
    monkeypatch.setattr("app.api.resilience.calculate_resilience", fake)


async def make_companies(db_session):
    buyer_user = await make_user(db_session)
    buyer = await make_company(db_session, buyer_user, can_buy=True, can_sell=False)
    primary_user = await make_user(db_session)
    primary = await make_company(db_session, primary_user, can_buy=False, can_sell=True)
    reserve_user = await make_user(db_session)
    reserve = await make_company(db_session, reserve_user, can_buy=False, can_sell=True)
    return {
        "buyer": (buyer_user, buyer, make_token(buyer_user)),
        "primary": (primary_user, primary, make_token(primary_user)),
        "reserve": (reserve_user, reserve, make_token(reserve_user)),
    }


async def make_ready_plan(client, db_session, companies):
    buyer_user, buyer, buyer_token = companies["buyer"]
    primary_user, primary, primary_token = companies["primary"]
    reserve_user, reserve, reserve_token = companies["reserve"]
    await grant_packaging_documents(db_session, primary, decision_user_id=primary_user,
                                    confirms={"material": ["крафт-картон"]})
    await grant_packaging_documents(db_session, reserve, decision_user_id=reserve_user,
                                    confirms={"material": ["крафт-картон"]})
    from conftest import grant_category_capability

    extra_reserves = [value for key, value in companies.items() if key.startswith("reserve") and key != "reserve"]
    extra_primaries = [value for key, value in companies.items() if key.startswith("primary") and key != "primary"]
    for extra_user, extra_company, _ in [*extra_reserves, *extra_primaries]:
        await grant_packaging_documents(db_session, extra_company, decision_user_id=extra_user, confirms={"material": ["крафт-картон"]})
        await grant_capacity(db_session, extra_company, 5_000)
    for company_id in (primary, reserve, *(value[1] for value in [*extra_reserves, *extra_primaries])):
        await grant_category_capability(db_session, company_id, "packaging.paper-cups",
                                        {"volume_ml": 400, "material": "крафт-картон"})
    await grant_capacity(db_session, primary, 5_000)
    await grant_capacity(db_session, reserve, 5_000)
    need = Need(company_id=buyer, created_by_user_id=buyer_user, category="Упаковка и тара",
                subcategory="Бумажные стаканы",
                characteristics={"volume_ml": 400, "material": "крафт-картон", "unit": "шт"},
                volume_units=5_000, budget_rub=500_000,
                deadline_date=date.today() + timedelta(days=30), status="open_for_offers")
    db_session.add(need)
    await db_session.flush()
    for company_id, user_id, price in ((primary, primary_user, 10), (reserve, reserve_user, 12), *((value[1], value[0], 13) for value in extra_reserves), *((value[1], value[0], 11) for value in extra_primaries)):
        db_session.add(Offer(need_id=need.id, company_id=company_id, created_by_user_id=user_id,
                             price_rub=price, available_units=5_000, lead_time_days=8,
                             delivery_cost_rub=2_000, moq_units=1_000, price_tiers=[], status="sent"))
    primary_rows = [(primary, 10), *((value[1], 11) for value in extra_primaries)]
    units = 5000 // len(primary_rows)
    allocations = [{"company_id": str(company), "units": units, "unit_price_rub": price,
        "delivery_cost_rub": 2000, "total_cost_rub": units * price + 2000, "lead_time_days": 8}
        for company, price in primary_rows]
    variant = OptimizationVariantRecord(need_id=need.id, kind="reliable", input_hash="baseline",
        result={"feasible": True, "total_cost_rub": sum(row["total_cost_rub"] for row in allocations),
                "max_lead_time_days": 10, "allocations": allocations})
    db_session.add(variant)
    await db_session.commit()
    for quote in (await db_session.scalars(select(Offer).where(Offer.need_id == need.id))).all():
        token = next(value[2] for value in companies.values() if value[1] == quote.company_id)
        updated = await client.patch(f"/api/v1/offers/{quote.id}", headers=auth(token),
                                     json={"expected_revision": quote.revision,
                                           "commercial_terms": confirmed_quote_terms()})
        assert updated.status_code == 200, updated.text
    created = await client.post(f"/api/v1/needs/{need.id}/resilience-plans",
                                json={"variant_id": str(variant.id), "max_price_increase_pct": 25,
                                      "max_delay_days": 2, "auto_replace_within_thresholds": False},
                                headers=auth(buyer_token))
    assert created.status_code == 201, created.text
    return created.json()


async def confirm_hot_reserve(client, db_session, companies, plan_id, switchover_days=2):
    _, reserve, reserve_token = companies["reserve"]
    invitations = await client.get(f"/api/v1/reserve-invitations/{reserve}", headers=auth(reserve_token))
    assert invitations.status_code == 200 and invitations.json()
    invitation = invitations.json()[0]
    decision = await client.post(f"/api/v1/reserve-commitments/{invitation['id']}/decision",
                                 json={"commercial_terms": confirmed_quote_terms(),
                                       "company_id": str(reserve), "decision": "approved",
                                       "capacity_units": 5_000, "moq_units": 1_000,
                                       "unit_price_rub": 12, "delivery_cost_rub": 2_000,
                                       "lead_time_days": 8,
                                       "held_until": str(date.today() + timedelta(days=7)),
                                       "switchover_days": switchover_days},
                                 headers=auth(reserve_token))
    assert decision.status_code == 200, decision.text
    assert decision.json()["reserve_tier"] == "hot"
    assert decision.json()["switchover_days"] == switchover_days
    return decision.json()


async def test_full_recovery_lifecycle(client, db_session, monkeypatch):
    await covered_resilience(monkeypatch)
    companies = await make_companies(db_session)
    buyer_user, buyer, buyer_token = companies["buyer"]
    primary_user, primary, primary_token = companies["primary"]
    plan = await make_ready_plan(client, db_session, companies)
    assert plan["status"] == "ready_for_confirmation"

    confirmed = await client.post(f"/api/v1/resilience-plans/{plan['id']}/confirm",
                                  json={"approved": True, "expected_revision": plan["version"]},
                                  headers=auth(buyer_token))
    assert confirmed.status_code == 200, confirmed.text
    assert confirmed.json()["status"] == "active"

    await confirm_hot_reserve(client, db_session, companies, plan["id"])
    reported = await client.post(f"/api/v1/resilience-plans/{plan['id']}/failures",
                                 json={"company_id": str(primary), "reason": "Поломка линии"},
                                 headers=auth(primary_token))
    assert reported.status_code == 200, reported.text
    assert reported.json()["version"] == plan["version"] + 1
    assert reported.json()["failed_company_ids"] == [str(primary)]
    baseline_before = {item["company_id"]: item["units"] for item in reported.json()["baseline_allocations"]}
    assert baseline_before[str(primary)] == 5_000

    decided = await client.post(
        f"/api/v1/reserve-commitments/{(await client.get(f'/api/v1/reserve-invitations/{companies['reserve'][1]}', headers=auth(companies['reserve'][2]))).json()[0]['id']}/decision",
        json={"commercial_terms": confirmed_quote_terms(), "company_id": str(companies["reserve"][1]),
              "decision": "approved", "capacity_units": 5_000, "moq_units": 1_000,
              "unit_price_rub": 12, "delivery_cost_rub": 2_000, "lead_time_days": 8,
              "held_until": str(date.today() + timedelta(days=7))},
        headers=auth(companies["reserve"][2]))
    assert decided.status_code == 200, decided.text

    live = await client.get(f"/api/v1/resilience-plans/{plan['id']}", headers=auth(buyer_token))
    scenarios = [s for s in live.json()["scenarios"] if s["status"] == "proposed"]
    assert scenarios, live.json()["scenarios"]
    scenario = scenarios[0]
    approved = await client.post(f"/api/v1/resilience-scenarios/{scenario['id']}/approve",
                                 json={"approved": True, "expected_revision": live.json()["version"]},
                                 headers=auth(buyer_token))
    assert approved.status_code == 200, approved.text
    assert approved.json()["status"] == "recovered"
    assert approved.json()["version"] == live.json()["version"] + 1

    replay = await client.post(f"/api/v1/resilience-scenarios/{scenario['id']}/approve",
                               json={"approved": True, "expected_revision": live.json()["version"]},
                               headers=auth(buyer_token))
    assert replay.status_code == 200
    assert replay.json()["status"] == "recovered"

    from app.models import ResilienceEvent
    activations = (await db_session.execute(select(ResilienceEvent).where(
        ResilienceEvent.plan_id == uuid.UUID(plan["id"]),
        ResilienceEvent.event_type == "replacement_approved"))).scalars().all()
    assert len(activations) == 1


async def test_simulation_writes_no_sales(client, db_session, monkeypatch):
    await covered_resilience(monkeypatch)
    companies = await make_companies(db_session)
    _, buyer, buyer_token = companies["buyer"]
    _, primary, primary_token = companies["primary"]
    plan = await make_ready_plan(client, db_session, companies)
    from app.models import Deal, ResourceReservation
    deals_before = len((await db_session.execute(select(Deal))).scalars().all())
    reservations_before = (await db_session.execute(select(ResourceReservation))).scalars().all()
    for _ in range(3):
        simulated = await client.post(f"/api/v1/resilience-plans/{plan['id']}/simulate-failure",
                                      json={"failed_company_ids": [str(primary)]},
                                      headers=auth(buyer_token))
        assert simulated.status_code == 201, simulated.text
        assert simulated.json()["is_simulation"] is True
    reservations_after = (await db_session.execute(select(ResourceReservation))).scalars().all()
    assert len(reservations_after) == len(reservations_before)
    assert len((await db_session.execute(select(Deal))).scalars().all()) == deals_before


async def test_uncovered_failure_cannot_activate(client, db_session, monkeypatch):
    async def fake_uncovered(payload):
        primary = payload["primary_allocations"][0]
        total = primary["units"] * primary["unit_price_rub"] + primary["delivery_cost_rub"]
        return {"scenarios": [live_scenario([str(primary["company_id"])], 0, total,
                                            uncovered=primary["units"])],
                "n1_fully_covered": False, "n2_fully_covered": False,
                "confirmed_coverage_pct": 0, "input_hash": "s09-uncovered"}

    monkeypatch.setattr("app.api.resilience.calculate_resilience", fake_uncovered)
    companies = await make_companies(db_session)
    _, buyer, buyer_token = companies["buyer"]
    _, primary, primary_token = companies["primary"]
    plan = await make_ready_plan(client, db_session, companies)
    await client.post(f"/api/v1/resilience-plans/{plan['id']}/confirm",
                      json={"approved": True, "expected_revision": plan["version"]},
                      headers=auth(buyer_token))
    reported = await client.post(f"/api/v1/resilience-plans/{plan['id']}/failures",
                                 json={"company_id": str(primary), "reason": "Поломка"},
                                 headers=auth(primary_token))
    assert reported.status_code == 200
    live = await client.get(f"/api/v1/resilience-plans/{plan['id']}", headers=auth(buyer_token))
    scenarios = [s for s in live.json()["scenarios"] if s["status"] == "proposed"]
    assert scenarios
    blocked = await client.post(f"/api/v1/resilience-scenarios/{scenarios[0]['id']}/approve",
                                json={"approved": True, "expected_revision": live.json()["version"]},
                                headers=auth(buyer_token))
    assert blocked.status_code == 409


async def _live_proposed_scenario(client, db_session, monkeypatch, fake=None):
    if fake is None:
        await covered_resilience(monkeypatch)
    else:
        monkeypatch.setattr("app.api.resilience.calculate_resilience", fake)
    companies = await make_companies(db_session)
    buyer_user, buyer, buyer_token = companies["buyer"]
    primary_user, primary, primary_token = companies["primary"]
    plan = await make_ready_plan(client, db_session, companies)
    await client.post(f"/api/v1/resilience-plans/{plan['id']}/confirm",
                      json={"approved": True, "expected_revision": plan["version"]},
                      headers=auth(buyer_token))
    await confirm_hot_reserve(client, db_session, companies, plan["id"])
    reported = await client.post(f"/api/v1/resilience-plans/{plan['id']}/failures",
                                 json={"company_id": str(primary), "reason": "Поломка"},
                                 headers=auth(primary_token))
    assert reported.status_code == 200, reported.text
    await confirm_hot_reserve(client, db_session, companies, plan["id"])
    live = await client.get(f"/api/v1/resilience-plans/{plan['id']}", headers=auth(buyer_token))
    scenarios = [s for s in live.json()["scenarios"] if s["status"] == "proposed"]
    assert scenarios
    return companies, live.json(), scenarios[0]


async def _seed_deal_with_acceptance(db_session, need_id, seller_id, buyer_id, buyer_user_id,
                                     units, accepted_units):
    from app.models import Deal, DealExecutionEvent, Offer

    offer = Offer(need_id=need_id, company_id=seller_id, price_rub=10, available_units=units,
                  lead_time_days=5, moq_units=1, status="selected")
    db_session.add(offer)
    await db_session.flush()
    deal = Deal(offer_id=offer.id, need_id=need_id, buyer_company_id=buyer_id,
                seller_company_id=seller_id, units=units, unit_price_rub=10,
                total_price_rub=10 * units, status="created")
    db_session.add(deal)
    await db_session.flush()
    if accepted_units:
        db_session.add(DealExecutionEvent(
            deal_id=deal.id, actor_company_id=buyer_id, actor_user_id=buyer_user_id,
            idempotency_key=uuid.uuid4(), kind="acceptance", units=accepted_units,
            note="синтетическая приёмка", status="confirmed",
            decided_by_user_id=buyer_user_id))
        await db_session.flush()
    await db_session.commit()
    return deal


async def test_accepted_volume_blocks_transfer(client, db_session, monkeypatch):
    companies, plan, scenario = await _live_proposed_scenario(client, db_session, monkeypatch)
    buyer_user, buyer, buyer_token = companies["buyer"]
    _, primary, _ = companies["primary"]
    need_id = plan["need_id"]
    await _seed_deal_with_acceptance(db_session, uuid.UUID(need_id), primary, buyer,
                                     buyer_user, 5_000, 5_000)
    blocked = await client.post(f"/api/v1/resilience-scenarios/{scenario['id']}/approve",
                                json={"approved": True, "expected_revision": plan["version"]},
                                headers=auth(buyer_token))
    assert blocked.status_code == 409
    assert "уже получен" in blocked.text


async def test_partial_acceptance_requires_manual_decision(client, db_session, monkeypatch):
    companies, plan, scenario = await _live_proposed_scenario(client, db_session, monkeypatch)
    buyer_user, buyer, buyer_token = companies["buyer"]
    _, primary, _ = companies["primary"]
    need_id = plan["need_id"]
    await _seed_deal_with_acceptance(db_session, uuid.UUID(need_id), primary, buyer,
                                     buyer_user, 5_000, 2_000)
    blocked = await client.post(f"/api/v1/resilience-scenarios/{scenario['id']}/approve",
                                json={"approved": True, "expected_revision": plan["version"]},
                                headers=auth(buyer_token))
    assert blocked.status_code == 409
    assert "ручное решение" in blocked.text


async def test_broken_replacement_keeps_volumes(client, db_session, monkeypatch):
    from app.models import ResourceReservation

    async def fake_with_replacement(payload):
        reserve_id = str(payload["reserve_options"][0]["company_id"]) if payload["reserve_options"] else str(uuid.uuid4())
        return {"scenarios": [{
            "scenario_type": "n1", "failed_company_ids": [str(payload["primary_allocations"][0]["company_id"])],
            "failed_units": 5_000,
            "replacement_allocations": [{"company_id": reserve_id, "units": 5_000, "unit_price_rub": 12,
                                         "delivery_cost_rub": 2_000, "additional_cost_rub": 0,
                                         "total_cost_rub": 62_000, "lead_time_days": 8}],
            "baseline_total_cost_rub": 52_000, "new_total_cost_rub": 62_000,
            "price_delta_rub": 10_000, "price_delta_pct": 1.0,
            "baseline_lead_time_days": 10, "new_lead_time_days": 10, "delay_days": 0,
            "uncovered_units": 0, "confirmed_covered_units": 5_000, "unconfirmed_units": 0,
            "auto_eligible": False, "requires_human_approval": True,
            "solver_status": "optimal", "explanations": ["синтетика"]}],
            "n1_fully_covered": True, "n2_fully_covered": True,
            "confirmed_coverage_pct": 100, "input_hash": "s09-broken"}

    companies, plan, scenario = await _live_proposed_scenario(client, db_session, monkeypatch,
                                                              fake=fake_with_replacement)
    _, buyer, buyer_token = companies["buyer"]
    await db_session.execute(
        __import__("sqlalchemy").delete(
            __import__("app.models", fromlist=["ReserveCommitment"]).ReserveCommitment))
    await db_session.commit()
    holds_before = sorted(
        (row.anchor_type, row.units, row.status)
        for row in (await db_session.execute(select(ResourceReservation))).scalars().all())
    broken = await client.post(f"/api/v1/resilience-scenarios/{scenario['id']}/approve",
                               json={"approved": True, "expected_revision": plan["version"]},
                               headers=auth(buyer_token))
    assert broken.status_code == 409
    holds_after = sorted(
        (row.anchor_type, row.units, row.status)
        for row in (await db_session.execute(select(ResourceReservation))).scalars().all())
    assert holds_after == holds_before
    current = await client.get(f"/api/v1/resilience-plans/{plan['id']}", headers=auth(buyer_token))
    assert current.json()["status"] != "recovered"


async def test_concurrent_approve_activates_once(client, db_session, monkeypatch):
    import asyncio

    from app.models import ResilienceEvent

    companies, plan, scenario = await _live_proposed_scenario(client, db_session, monkeypatch)
    _, buyer, buyer_token = companies["buyer"]

    async def approve():
        return await client.post(f"/api/v1/resilience-scenarios/{scenario['id']}/approve",
                                 json={"approved": True, "expected_revision": plan["version"]},
                                 headers=auth(buyer_token))

    first, second = await asyncio.gather(approve(), approve())
    # Ровно одна активация: второй либо видит готовый результат, либо честный
    # конфликт устаревшей показанной версии. Дубликата замены нет в обоих случаях.
    assert sorted([first.status_code, second.status_code]) in ([200, 200], [200, 409])
    events = (await db_session.execute(select(ResilienceEvent).where(
        ResilienceEvent.plan_id == uuid.UUID(plan["id"]),
        ResilienceEvent.event_type == "replacement_approved"))).scalars().all()
    assert len(events) == 1
    final = await client.get(f"/api/v1/resilience-plans/{plan['id']}", headers=auth(buyer_token))
    assert final.json()["status"] == "recovered"
