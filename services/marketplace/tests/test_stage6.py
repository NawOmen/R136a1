from conftest import grant_capacity
from datetime import date, timedelta
from itertools import combinations
from uuid import UUID

from app.models import Need, Offer, OptimizationVariantRecord, ResiliencePlan
from conftest import grant_packaging_documents, make_company, make_token, make_user


def auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def fake_resilience(payload):
    scenarios = []
    baseline_cost = sum(
        item["units"] * item["unit_price_rub"] + item["delivery_cost_rub"]
        for item in payload["primary_allocations"]
    )
    for size in (1, 2):
        for failed in combinations(payload["primary_allocations"], size):
            failed_units = sum(item["units"] for item in failed)
            scenarios.append(
                {
                    "scenario_type": f"n{size}",
                    "failed_company_ids": [item["company_id"] for item in failed],
                    "failed_units": failed_units,
                    "replacement_allocations": [],
                    "baseline_total_cost_rub": baseline_cost,
                    "new_total_cost_rub": baseline_cost,
                    "price_delta_rub": 0,
                    "price_delta_pct": 0,
                    "baseline_lead_time_days": 10,
                    "new_lead_time_days": 10,
                    "delay_days": 0,
                    "uncovered_units": failed_units,
                    "confirmed_covered_units": 0,
                    "unconfirmed_units": 0,
                    "auto_eligible": False,
                    "requires_human_approval": True,
                    "explanations": ["Для теста резерв ещё не подтверждён"],
                }
            )
    return {
        "scenarios": scenarios,
        "n1_fully_covered": False,
        "n2_fully_covered": False,
        "confirmed_coverage_pct": 0,
        "input_hash": "stage-6-synthetic",
    }


async def test_resilience_plan_privacy_confirmation_simulation_and_failure(
    client, db_session, monkeypatch
):
    monkeypatch.setattr("app.api.resilience.calculate_resilience", fake_resilience)
    buyer_user = await make_user(db_session)
    buyer = await make_company(db_session, buyer_user, can_buy=True, can_sell=False)
    buyer_token = make_token(buyer_user)
    primary_user = await make_user(db_session)
    primary = await make_company(db_session, primary_user, can_buy=False, can_sell=True)
    primary_token = make_token(primary_user)
    reserve_user = await make_user(db_session)
    reserve = await make_company(db_session, reserve_user, can_buy=False, can_sell=True)
    reserve_token = make_token(reserve_user)
    await grant_capacity(db_session, reserve, 5_000)
    # Резерв — обязательство: у компании резерва должны быть подтверждённые документы.
    await grant_packaging_documents(db_session, reserve, decision_user_id=reserve_user)

    need = Need(
        company_id=buyer,
        created_by_user_id=buyer_user,
        category="бумажные стаканы",
        characteristics={"volume_ml": 400},
        volume_units=5_000,
        budget_rub=100_000,
        deadline_date=date.today() + timedelta(days=30),
        status="open_for_offers",
    )
    db_session.add(need)
    await db_session.flush()
    db_session.add(
        Offer(
            need_id=need.id,
            company_id=reserve,
            created_by_user_id=reserve_user,
            price_rub=12,
            available_units=5_000,
            lead_time_days=8,
            delivery_cost_rub=2_000,
            moq_units=1_000,
            price_tiers=[],
            status="sent",
        )
    )
    await grant_capacity(db_session, primary, 5_000)
    await grant_packaging_documents(db_session, primary, decision_user_id=primary_user)
    db_session.add(Offer(need_id=need.id, company_id=primary, created_by_user_id=primary_user,
        price_rub=10, available_units=5_000, lead_time_days=10, delivery_cost_rub=2_000,
        moq_units=1_000, price_tiers=[], status="sent"))
    variant = OptimizationVariantRecord(
        need_id=need.id,
        kind="reliable",
        input_hash="baseline",
        result={
            "feasible": True,
            "total_cost_rub": 52_000,
            "max_lead_time_days": 10,
            "allocations": [
                {
                    "company_id": str(primary),
                    "units": 5_000,
                    "unit_price_rub": 10,
                    "delivery_cost_rub": 2_000,
                    "total_cost_rub": 52_000,
                    "lead_time_days": 10,
                }
            ],
        },
    )
    db_session.add(variant)
    await db_session.commit()

    created = await client.post(
        f"/api/v1/needs/{need.id}/resilience-plans",
        json={"variant_id": str(variant.id), "max_price_increase_pct": 5, "max_delay_days": 2},
        headers=auth(buyer_token),
    )
    assert created.status_code == 201
    plan = created.json()
    assert plan["status"] == "ready_for_confirmation"
    assert len(plan["scenarios"]) == 1

    invitation = (await client.get(
        f"/api/v1/reserve-invitations/{reserve}", headers=auth(reserve_token)
    )).json()[0]
    hidden = await client.get(
        f"/api/v1/resilience-plans/{plan['id']}", headers=auth(reserve_token)
    )
    assert hidden.status_code == 404

    before = plan["current_allocations"]
    simulated = await client.post(
        f"/api/v1/resilience-plans/{plan['id']}/simulate-failure",
        json={"failed_company_ids": [str(primary)]},
        headers=auth(buyer_token),
    )
    assert simulated.status_code == 201
    after = (await client.get(
        f"/api/v1/resilience-plans/{plan['id']}", headers=auth(buyer_token)
    )).json()
    assert after["current_allocations"] == before
    assert after["status"] == "ready_for_confirmation"

    confirmed = await client.post(
        f"/api/v1/resilience-plans/{plan['id']}/confirm",
        json={"approved": True, "expected_revision": plan["version"]}, headers=auth(buyer_token),
    )
    assert confirmed.status_code == 200

    decision = await client.post(
        f"/api/v1/reserve-commitments/{invitation['id']}/decision",
        json={
            "company_id": str(reserve), "decision": "approved",
            "capacity_units": 5_000, "moq_units": 1_000,
            "unit_price_rub": 12, "delivery_cost_rub": 2_000,
            "lead_time_days": 8, "held_until": str(date.today() + timedelta(days=7)),
        },
        headers=auth(reserve_token),
    )
    assert decision.status_code == 200
    assert decision.json()["reserve_tier"] == "hot"

    obligations = await client.get(
        f"/api/v1/primary-obligations/{primary}", headers=auth(primary_token)
    )
    assert obligations.status_code == 200
    assert obligations.json()[0]["allocation"]["units"] == 5_000
    failed = await client.post(
        f"/api/v1/resilience-plans/{plan['id']}/failures",
        json={"company_id": str(primary), "reason": "Синтетическая поломка линии"},
        headers=auth(primary_token),
    )
    assert failed.status_code == 200
    assert failed.json()["status"] == "partially_covered"
    stored = await db_session.get(ResiliencePlan, UUID(plan["id"]))
    assert stored.failed_company_ids == [str(primary)]
