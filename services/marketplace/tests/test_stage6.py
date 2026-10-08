from app.money import money_values
from conftest import confirmed_quote_terms
from conftest import grant_capacity,grant_category_capability
from datetime import date, timedelta
from itertools import combinations
import pytest
from uuid import UUID

from app.models import Need, Offer, OptimizationVariantRecord, ResiliencePlan
from conftest import grant_packaging_documents, make_company, make_token, make_user


def auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def fake_resilience(payload):
    payload = money_values(payload)
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


@pytest.mark.parametrize("automatic,paid_holding", [(False,False),(True,False),(False,True)])
async def test_resilience_plan_privacy_confirmation_simulation_and_failure(
    client, db_session, monkeypatch, automatic, paid_holding
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
    await grant_packaging_documents(db_session, reserve, decision_user_id=reserve_user,confirms={"material":["крафт-картон"]})

    for supplier in (primary,reserve):await grant_category_capability(db_session,supplier,"packaging.paper-cups",{"volume_ml":400,"material":"крафт-картон"})

    need = Need(
        company_id=buyer,
        created_by_user_id=buyer_user,
        category="бумажные стаканы",
        characteristics={"volume_ml": 400,"material":"крафт-картон"},
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
    await grant_packaging_documents(db_session, primary, decision_user_id=primary_user,confirms={"material":["крафт-картон"]})
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

    # Explicit current quotes; historical NULL quotes are not backfilled by the application.
    from sqlalchemy import select
    for quote in (await db_session.scalars(select(Offer).where(Offer.need_id==need.id))).all():
        token = primary_token if quote.company_id==primary else reserve_token
        updated = await client.patch(f'/api/v1/offers/{quote.id}',headers=auth(token),json={
            'expected_revision':quote.revision,'commercial_terms':confirmed_quote_terms()})
        assert updated.status_code==200,updated.text
    created = await client.post(
        f"/api/v1/needs/{need.id}/resilience-plans",
        json={"variant_id": str(variant.id), "max_price_increase_pct": 25, "max_delay_days": 2, "auto_replace_within_thresholds":automatic},
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
        json={'commercial_terms': {**confirmed_quote_terms(),'expenses':([{'code':'reserve_holding','title':'Удержание производителя','amount_rub':'50.00','source':'Синтетический тариф','version':'1'}] if paid_holding else [])},
            "company_id": str(reserve), "decision": "approved",
            "capacity_units": 5_000, "moq_units": 1_000,
            "unit_price_rub": 12, "delivery_cost_rub": 2_000,
            "lead_time_days": 8, "held_until": str(date.today() + timedelta(days=7)),
        },
        headers=auth(reserve_token),
    )
    assert decision.status_code == 200
    assert decision.json()["reserve_tier"] == "hot"

    if paid_holding:
        revised = (await client.get(f"/api/v1/resilience-plans/{plan['id']}",headers=auth(buyer_token))).json()
        assert revised['confirmed_at'] is None and revised['version'] > plan['version']
        assert revised['status'] == 'ready_for_confirmation'
        stale = await client.post(f"/api/v1/resilience-plans/{plan['id']}/confirm",
            headers=auth(buyer_token),json={'approved':True,'expected_revision':plan['version']})
        assert stale.status_code == 409
        renewed = await client.post(f"/api/v1/resilience-plans/{plan['id']}/confirm",
            headers=auth(buyer_token),json={'approved':True,'expected_revision':revised['version']})
        assert renewed.status_code == 200,renewed.text
        assert renewed.json()['baseline_total_cost_rub'] == 52050
        removed = await client.post(f"/api/v1/reserve-commitments/{invitation['id']}/decision",
            headers=auth(reserve_token),json={'company_id':str(reserve),'decision':'rejected'})
        assert removed.status_code == 200,removed.text
        after_cancel=(await client.get(f"/api/v1/resilience-plans/{plan['id']}",headers=auth(buyer_token))).json()
        assert after_cancel['baseline_total_cost_rub'] == 52050
        assert after_cancel['confirmed_at'] is not None
        new_terms={**confirmed_quote_terms(),'expenses':[{'code':'reserve_holding','title':'Новое удержание','amount_rub':'70.00','source':'Новый синтетический тариф','version':'2'}]}
        renewed_reserve=await client.post(f"/api/v1/reserve-commitments/{invitation['id']}/decision",headers=auth(reserve_token),json={
            'company_id':str(reserve),'decision':'approved','capacity_units':5000,'moq_units':1000,
            'unit_price_rub':12,'delivery_cost_rub':2000,'lead_time_days':8,
            'held_until':str(date.today()+timedelta(days=7)),'commercial_terms':new_terms})
        assert renewed_reserve.status_code==200,renewed_reserve.text
        proposed=(await client.get(f"/api/v1/resilience-plans/{plan['id']}",headers=auth(buyer_token))).json()
        assert proposed['confirmed_at'] is None and proposed['baseline_total_cost_rub']==52120
        final=await client.post(f"/api/v1/resilience-plans/{plan['id']}/confirm",headers=auth(buyer_token),json={'approved':True,'expected_revision':proposed['version']})
        assert final.status_code==200,final.text
        assert final.json()['commercial_snapshot']['reserve_holding_total_rub']==120
        assert len(final.json()['commercial_snapshot']['holding_quotes'])==2

    obligations = await client.get(
        f"/api/v1/primary-obligations/{primary}", headers=auth(primary_token)
    )
    assert obligations.status_code == 200
    assert obligations.json()[0]["allocation"]["units"] == 5_000
    if automatic:
        async def covered(payload):
            result = await fake_resilience(payload)
            for scenario in result['scenarios']:
                scenario.update(replacement_allocations=[{'company_id':str(reserve),'units':5000,'unit_price_rub':12,'delivery_cost_rub':2000,'total_cost_rub':62000,'lead_time_days':8}],
                    new_total_cost_rub=62000,new_lead_time_days=8,uncovered_units=0,confirmed_covered_units=5000,
                    auto_eligible=True,requires_human_approval=False)
            return result
        monkeypatch.setattr("app.api.resilience.calculate_resilience",covered)
    failed = await client.post(
        f"/api/v1/resilience-plans/{plan['id']}/failures",
        json={"company_id": str(primary), "reason": "Синтетическая поломка линии"},
        headers=auth(primary_token),
    )
    assert failed.status_code == 200
    assert failed.json()["status"] == ("recovered" if automatic else "partially_covered")
    stored = await db_session.get(ResiliencePlan, UUID(plan["id"]))
    assert stored.failed_company_ids == [str(primary)]
