"""S09 regression: real order/resource mutations, receipts, retries and failures."""
import asyncio
import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
import pytest
from sqlalchemy import select, text
from app.models import Deal, DealCheckpoint, DealExecutionEvent, Need, Notification, ReserveCommitment, ResourceReservation, ResiliencePlan
from conftest import confirmed_quote_terms, make_user, make_company, make_token
from test_stage9_resilience import auth, covered_resilience, make_companies, make_ready_plan, confirm_hot_reserve, _live_proposed_scenario


async def checkpoint(client, deal, company, token, kind, note=None):
    response = await client.patch(f"/api/v3/deals/{deal}/timeline/{kind}", headers=auth(token),
        json={"company_id": str(company), "completed": True, "human_approved": True, "note": note})
    assert response.status_code == 200, response.text
    return response


async def execution(client, deal, company, token, kind, units, key=None):
    response = await client.post(f"/api/v3/deals/{deal}/execution", headers=auth(token),
        json={"company_id": str(company), "kind": kind, "units": units, "note": "Синтетический акт исполнения",
              "human_approved": True, "idempotency_key": str(key or uuid.uuid4())})
    return response


async def approve(client, plan, scenario, token):
    return await client.post(f"/api/v3/resilience-scenarios/{scenario['id']}/approve", headers=auth(token),
        json={"approved": True, "expected_revision": plan["version"]})


async def current_plan(client, plan, token):
    response = await client.get(f"/api/v3/resilience-plans/{plan['id']}", headers=auth(token))
    assert response.status_code == 200, response.text
    return response.json()


async def setup_confirmed(client, db_session, monkeypatch, *, automatic=False, second_reserve=False):
    await covered_resilience(monkeypatch)
    companies = await make_companies(db_session)
    if second_reserve:
        user = await make_user(db_session)
        company = await make_company(db_session, user, can_buy=False, can_sell=True)
        companies["reserve2"] = (user, company, make_token(user))
    plan = await make_ready_plan(client, db_session, companies)
    if automatic:
        stored = await db_session.get(ResiliencePlan, uuid.UUID(plan["id"]))
        stored.auto_replace_within_thresholds = True
        await db_session.commit()
    confirmed = await client.post(f"/api/v3/resilience-plans/{plan['id']}/confirm", headers=auth(companies["buyer"][2]),
        json={"approved": True, "expected_revision": plan["version"]})
    assert confirmed.status_code == 200, confirmed.text
    await confirm_hot_reserve(client, db_session, companies, plan["id"])
    return companies, confirmed.json()


async def report(client, plan, company, token):
    return await client.post(f"/api/v3/resilience-plans/{plan['id']}/failures", headers=auth(token),
        json={"company_id": str(company), "reason": "Синтетическая поломка линии"})


async def test_baseline_is_executable_without_second_reservation(client, db_session, monkeypatch):
    companies, plan = await setup_confirmed(client, db_session, monkeypatch)
    _, primary, seller_token = companies["primary"]
    _, buyer, buyer_token = companies["buyer"]
    deal = plan["current_allocations"][0]["deal_id"]
    rows = list((await db_session.scalars(select(ResourceReservation).where(ResourceReservation.company_id == primary))).all())
    assert sum(row.units for row in rows if row.status == "committed") == 5000
    assert all(row.anchor_type == "deal" and str(row.anchor_id) == deal for row in rows)
    assert len((await db_session.scalars(select(DealCheckpoint).where(DealCheckpoint.deal_id == uuid.UUID(deal)))).all()) == 3
    await checkpoint(client, deal, primary, seller_token, "production")
    await checkpoint(client, deal, primary, seller_token, "shipment")
    await checkpoint(client, deal, primary, seller_token, "shipment", "Уточнён номер синтетического акта")
    key = uuid.uuid4()
    first = await execution(client, deal, buyer, buyer_token, "acceptance", 5000, key)
    replay = await execution(client, deal, buyer, buyer_token, "acceptance", 5000, key)
    assert first.status_code == replay.status_code == 201
    assert first.json()["id"] == replay.json()["id"]
    extra = await execution(client, deal, buyer, buyer_token, "acceptance", 1)
    assert extra.status_code == 409
    refused = await report(client, plan, primary, seller_token)
    assert refused.status_code == 409 and "перенос не требуется" in refused.text


async def test_recovery_deal_executes_and_replay_checks_current_access(client, db_session, monkeypatch):
    companies, plan, scenario = await _live_proposed_scenario(client, db_session, monkeypatch)
    buyer_user, buyer, buyer_token = companies["buyer"]
    _, reserve, seller_token = companies["reserve"]
    response = await approve(client, plan, scenario, buyer_token)
    assert response.status_code == 200, response.text
    recovered = response.json()
    allocation = next(row for row in recovered["current_allocations"] if row["company_id"] == str(reserve))
    assert allocation["units"] == 5000
    deal = allocation["deal_id"]
    rows = list((await db_session.scalars(select(ResourceReservation).where(ResourceReservation.company_id == reserve))).all())
    assert sum(row.units for row in rows if row.status == "committed") == 5000
    assert all(row.anchor_type == "deal" for row in rows)
    outsider = await make_user(db_session)
    denied = await approve(client, plan, scenario, make_token(outsider))
    assert denied.status_code in (403, 404)
    await checkpoint(client, deal, reserve, seller_token, "production")
    await checkpoint(client, deal, reserve, seller_token, "shipment")
    accepted = await execution(client, deal, buyer, buyer_token, "acceptance", 5000)
    assert accepted.status_code == 201, accepted.text
    repeated = await approve(client, plan, scenario, buyer_token)
    assert repeated.status_code == 200
    assert len((await db_session.scalars(select(Deal).where(Deal.resilience_scenario_id == uuid.UUID(scenario["id"])))).all()) == 1
    await db_session.execute(text("DELETE FROM auth.company_members WHERE company_id=:company AND user_id=:uid"), {"company": buyer, "uid": buyer_user})
    await db_session.commit()
    denied = await approve(client, plan, scenario, buyer_token)
    assert denied.status_code in (403, 404)


async def test_active_reserve_cannot_reject_invitation(client, db_session, monkeypatch):
    companies, plan, scenario = await _live_proposed_scenario(client, db_session, monkeypatch)
    response = await approve(client, plan, scenario, companies["buyer"][2])
    assert response.status_code == 200, response.text
    reserve = companies["reserve"][1]
    commitment = await db_session.scalar(select(ReserveCommitment).where(ReserveCommitment.plan_id == uuid.UUID(plan["id"]), ReserveCommitment.company_id == reserve))
    response = await client.post(f"/api/v3/reserve-commitments/{commitment.id}/decision", headers=auth(companies["reserve"][2]),
        json={"company_id": str(reserve), "decision": "rejected"})
    assert response.status_code == 409
    rows = (await db_session.scalars(select(ResourceReservation).where(ResourceReservation.company_id == reserve))).all()
    assert sum(row.units for row in rows if row.status == "committed") == 5000
    after = await current_plan(client, plan, companies["buyer"][2])
    assert after["version"] == plan["version"] + 1 and after["status"] == "recovered"


@pytest.mark.parametrize("blocker", ["budget", "deadline", "switching", "unknown_switching", "buyer_revoked"])
async def test_auto_recovery_obeys_hard_constraints(client, db_session, monkeypatch, blocker):
    companies, plan = await setup_confirmed(client, db_session, monkeypatch, automatic=True)
    primary, primary_token = companies["primary"][1:]
    response = await report(client, plan, primary, primary_token)
    assert response.status_code == 200, response.text
    need = await db_session.get(Need, uuid.UUID(plan["need_id"]))
    if blocker == "budget": need.budget_rub = Decimal(60000)
    if blocker == "buyer_revoked":
        await db_session.execute(text("UPDATE auth.companies SET verification_status='draft' WHERE id=:company"), {"company": companies["buyer"][1]})
    if blocker == "deadline": need.deadline_date = date.today()+timedelta(days=2)
    await db_session.commit()
    await confirm_hot_reserve(client, db_session, companies, plan["id"], switchover_days=365 if blocker == "switching" else None if blocker == "unknown_switching" else 2)
    after = await current_plan(client, plan, companies["buyer"][2])
    assert after["status"] != "recovered"
    assert not (await db_session.scalars(select(Deal).where(Deal.resilience_scenario_id.is_not(None)))).all()
    scenario = next(item for item in after["scenarios"] if item["status"] == "proposed")
    manual = await approve(client, after, scenario, companies["buyer"][2])
    assert manual.status_code in (403, 409)


async def test_expired_hold_marks_saved_calculation_stale(client, db_session, monkeypatch):
    companies, plan, scenario = await _live_proposed_scenario(client, db_session, monkeypatch)
    commitment = await db_session.scalar(select(ReserveCommitment).where(ReserveCommitment.plan_id == uuid.UUID(plan["id"])))
    commitment.held_until = date.today()-timedelta(days=1)
    rows = (await db_session.scalars(select(ResourceReservation).where(ResourceReservation.anchor_type == "reserve", ResourceReservation.anchor_id == commitment.id))).all()
    for row in rows: row.expires_at = datetime.now(timezone.utc)-timedelta(seconds=1)
    await db_session.commit()
    current = await current_plan(client, plan, companies["buyer"][2])
    assert current["reserves"][0]["effective_tier"] == "warm"
    assert current["reserves"][0]["available_units"] == 0
    assert "истёк" in current["reserves"][0]["availability_reason"]
    assert not next(item for item in current["scenarios"] if item["id"] == scenario["id"])["is_current"]
    assert (await approve(client, current, scenario, companies["buyer"][2])).status_code == 409


async def test_partial_shipment_preserved_and_only_remainder_replaced(client, db_session, monkeypatch):
    companies, plan = await setup_confirmed(client, db_session, monkeypatch, automatic=True)
    _, buyer, buyer_token = companies["buyer"]
    _, primary, primary_token = companies["primary"]
    _, reserve, reserve_token = companies["reserve"]
    old_deal = plan["current_allocations"][0]["deal_id"]
    await checkpoint(client, old_deal, primary, primary_token, "production")
    shipped = await execution(client, old_deal, primary, primary_token, "shipment", 2000)
    assert shipped.status_code == 201, shipped.text
    accepted = await execution(client, old_deal, buyer, buyer_token, "acceptance", 2000)
    assert accepted.status_code == 201, accepted.text
    failed = await report(client, plan, primary, primary_token)
    assert failed.status_code == 200, failed.text
    await confirm_hot_reserve(client, db_session, companies, plan["id"])
    proposed = await current_plan(client, plan, buyer_token)
    assert proposed["status"] == "recovery_proposed"
    scenario = next(item for item in proposed["scenarios"] if item["status"] == "proposed")
    assert scenario["result"]["failed_units"] == 3000
    activated = await approve(client, proposed, scenario, buyer_token)
    assert activated.status_code == 200, activated.text
    recovered = activated.json()
    assert sum(row["units"] for row in recovered["current_allocations"]) == 5000
    assert recovered["current_total_cost_rub"] == "60000.00"
    old = await client.get(f"/api/v3/deals/{old_deal}/execution?company_id={buyer}", headers=auth(buyer_token))
    assert old.json()["accepted_units"] == old.json()["shipped_units"] == 2000
    assert old.json()["cancelled_units"] == 3000 and old.json()["open_units"] == 0
    replacement = next(row for row in recovered["current_allocations"] if row["company_id"] == str(reserve))
    assert replacement["units"] == 3000
    await checkpoint(client, replacement["deal_id"], reserve, reserve_token, "production")
    await checkpoint(client, replacement["deal_id"], reserve, reserve_token, "shipment")
    assert (await execution(client, replacement["deal_id"], buyer, buyer_token, "acceptance", 3000)).status_code == 201
    events = (await db_session.scalars(select(DealExecutionEvent).where(DealExecutionEvent.kind == "acceptance", DealExecutionEvent.status == "confirmed"))).all()
    assert sum(event.units for event in events) == 5000


async def test_replacement_can_report_second_failure_and_transfer_once(client, db_session, monkeypatch):
    companies, plan = await setup_confirmed(client, db_session, monkeypatch, second_reserve=True)
    buyer_token = companies["buyer"][2]
    first = await report(client, plan, companies["primary"][1], companies["primary"][2])
    assert first.status_code == 200, first.text
    await confirm_hot_reserve(client, db_session, companies, plan["id"])
    proposed = await current_plan(client, plan, buyer_token)
    scenario = next(row for row in proposed["scenarios"] if row["status"] == "proposed")
    first = await approve(client, proposed, scenario, buyer_token)
    assert first.status_code == 200, first.text
    obligations = await client.get(f"/api/v3/primary-obligations/{companies['reserve'][1]}", headers=auth(companies["reserve"][2]))
    assert obligations.status_code == 200 and obligations.json()[0]["allocation"]["units"] == 5000
    second = await report(client, first.json(), companies["reserve"][1], companies["reserve"][2])
    assert second.status_code == 200, second.text
    renewed = {**companies, "reserve": companies["reserve2"]}
    await confirm_hot_reserve(client, db_session, renewed, plan["id"])
    proposed = await current_plan(client, plan, buyer_token)
    scenario = next(row for row in proposed["scenarios"] if row["status"] == "proposed")
    assert scenario["failed_company_ids"] == [str(companies["reserve"][1])]
    second = await approve(client, proposed, scenario, buyer_token)
    assert second.status_code == 200, second.text
    assert second.json()["baseline_allocations"][0]["company_id"] == str(companies["primary"][1])
    assert second.json()["current_allocations"][0]["company_id"] == str(companies["reserve2"][1])
    rows = (await db_session.scalars(select(ResourceReservation).where(ResourceReservation.status == "committed"))).all()
    assert sum(row.units for row in rows) == 5000
    assert all(row.company_id == companies["reserve2"][1] for row in rows)


async def test_notifications_follow_current_buyer_admins(client, db_session, monkeypatch):
    companies, plan = await setup_confirmed(client, db_session, monkeypatch, automatic=True)
    old_user, buyer, _ = companies["buyer"]
    new_user = await make_user(db_session)
    await db_session.execute(text("DELETE FROM auth.company_members WHERE company_id=:company AND user_id=:uid"), {"company": buyer, "uid": old_user})
    await db_session.execute(text("INSERT INTO auth.company_members (id, company_id, user_id, can_buy, can_sell, is_admin) VALUES (:id,:company,:uid,true,false,true)"),
        {"id": uuid.uuid4(), "company": buyer, "uid": new_user})
    await db_session.execute(text("DELETE FROM marketplace.notifications"))
    await db_session.commit()
    failed = await report(client, plan, companies["primary"][1], companies["primary"][2])
    assert failed.status_code == 200, failed.text
    await confirm_hot_reserve(client, db_session, companies, plan["id"])
    current = await current_plan(client, plan, make_token(new_user))
    assert current["status"] == "recovered"
    notifications = (await db_session.scalars(select(Notification).where(Notification.type == "replacement_activated"))).all()
    assert any(item.user_id == new_user for item in notifications)
    assert not any(item.user_id == old_user for item in notifications)


async def test_concurrent_receipt_cannot_race_recovery_validation(client, db_session, monkeypatch):
    companies, plan = await setup_confirmed(client, db_session, monkeypatch)
    _, primary, seller_token = companies["primary"]
    _, buyer, buyer_token = companies["buyer"]
    deal = plan["current_allocations"][0]["deal_id"]
    await checkpoint(client, deal, primary, seller_token, "production")
    assert (await execution(client, deal, primary, seller_token, "shipment", 2000)).status_code == 201
    failed = await report(client, plan, primary, seller_token)
    assert failed.status_code == 200, failed.text
    await confirm_hot_reserve(client, db_session, companies, plan["id"])
    proposed = await current_plan(client, plan, buyer_token)
    scenario = next(row for row in proposed["scenarios"] if row["status"] == "proposed")
    from app.api import resilience
    original = resilience._validate_activation
    paused, resume = asyncio.Event(), asyncio.Event()
    async def guarded(*args, **kwargs):
        need = await original(*args, **kwargs)
        paused.set()
        await resume.wait()
        return need
    monkeypatch.setattr(resilience, "_validate_activation", guarded)
    activation = asyncio.create_task(approve(client, proposed, scenario, buyer_token))
    await asyncio.wait_for(paused.wait(), timeout=10)
    receipt = asyncio.create_task(execution(client, deal, buyer, buyer_token, "acceptance", 2000))
    try:
        await asyncio.sleep(0.1)
        assert not receipt.done(), "Приёмка должна ждать общий замок потребности"
    finally:
        resume.set()
    activated, accepted = await asyncio.wait_for(asyncio.gather(activation, receipt), timeout=15)
    assert activated.status_code == 200, activated.text
    assert accepted.status_code == 201, accepted.text
    assert sum(row["units"] for row in activated.json()["current_allocations"]) == 5000


async def test_saved_pre_s09_assignment_binds_without_reserving_again(client, db_session, monkeypatch):
    companies, plan = await setup_confirmed(client, db_session, monkeypatch)
    stored = await db_session.get(ResiliencePlan, uuid.UUID(plan["id"]))
    allocation = stored.current_allocations[0]
    deal_id = uuid.UUID(allocation["deal_id"])
    rows = (await db_session.scalars(select(ResourceReservation).where(ResourceReservation.anchor_id == deal_id))).all()
    for row in rows: row.anchor_type, row.anchor_id = "resilience_primary", stored.id
    original = {key: value for key, value in allocation.items() if key not in {"deal_id", "commercial_snapshot"}}
    stored.current_allocations = [original]
    stored.baseline_allocations = [original]
    await db_session.execute(text("DELETE FROM marketplace.deals WHERE id=:deal"), {"deal": deal_id})
    await db_session.commit()
    restored = await client.post(f"/api/v3/resilience-plans/{plan['id']}/recalculate", headers=auth(companies["buyer"][2]))
    assert restored.status_code == 200, restored.text
    assert restored.json()["current_allocations"][0]["deal_id"]
    assert len((await db_session.scalars(select(Deal).where(Deal.resilience_plan_id == stored.id))).all()) == 1
    rows = (await db_session.scalars(select(ResourceReservation).where(ResourceReservation.company_id == companies["primary"][1]).execution_options(populate_existing=True))).all()
    assert all(row.anchor_type == "deal" for row in rows)
    assert sum(row.units for row in rows if row.status == "committed") == 5000


async def test_notification_failure_rolls_back_orders_audit_and_resources(client, db_session, monkeypatch):
    from fastapi import HTTPException
    from app.models import HumanApprovalRecord
    companies, plan, scenario = await _live_proposed_scenario(client, db_session, monkeypatch)
    async def fail_notification(*args, **kwargs):
        raise HTTPException(500, "Синтетический сбой записи уведомления")
    monkeypatch.setattr("app.api.resilience._notify_recovery", fail_notification)
    response = await approve(client, plan, scenario, companies["buyer"][2])
    assert response.status_code == 500
    assert not (await db_session.scalars(select(Deal).where(Deal.resilience_scenario_id.is_not(None)))).all()
    assert not (await db_session.scalars(select(HumanApprovalRecord).where(HumanApprovalRecord.action == "approve_recovery"))).all()
    rows = (await db_session.scalars(select(ResourceReservation).where(ResourceReservation.company_id == companies["reserve"][1]))).all()
    assert sum(row.units for row in rows if row.status == "held") == 5000
    current = await current_plan(client, plan, companies["buyer"][2])
    assert current["version"] == plan["version"] and current["status"] == "recovery_proposed"


async def test_two_actual_failures_transfer_to_one_executable_recovery(client, db_session, monkeypatch):
    await covered_resilience(monkeypatch)
    companies = await make_companies(db_session)
    user = await make_user(db_session)
    company = await make_company(db_session, user, can_buy=False, can_sell=True)
    companies["primary2"] = (user, company, make_token(user))
    plan = await make_ready_plan(client, db_session, companies)
    buyer_token = companies["buyer"][2]
    confirmed = await client.post(f"/api/v3/resilience-plans/{plan['id']}/confirm", headers=auth(buyer_token),
        json={"approved": True, "expected_revision": plan["version"]})
    assert confirmed.status_code == 200, confirmed.text
    assert len(confirmed.json()["current_allocations"]) == 2
    await confirm_hot_reserve(client, db_session, companies, plan["id"])
    for key in ("primary", "primary2"):
        failed = await report(client, plan, companies[key][1], companies[key][2])
        assert failed.status_code == 200, failed.text
    await confirm_hot_reserve(client, db_session, companies, plan["id"])
    proposed = await current_plan(client, plan, buyer_token)
    scenario = next(row for row in proposed["scenarios"] if row["status"] == "proposed")
    assert len(scenario["failed_company_ids"]) == 2
    assert scenario["result"]["confirmed_covered_units"] == 5000
    response = await approve(client, proposed, scenario, buyer_token)
    assert response.status_code == 200, response.text
    assert len(response.json()["current_allocations"]) == 1
    assert response.json()["current_allocations"][0]["units"] == 5000
    rows = (await db_session.scalars(select(ResourceReservation).where(ResourceReservation.status == "committed"))).all()
    assert sum(row.units for row in rows) == 5000


async def test_paid_reconfirmation_after_failure_can_be_approved_without_rewinding_orders(client, db_session, monkeypatch):
    companies, plan = await setup_confirmed(client, db_session, monkeypatch)
    failed = await report(client, plan, companies["primary"][1], companies["primary"][2])
    assert failed.status_code == 200, failed.text
    reserve = companies["reserve"][1]
    commitment = await db_session.scalar(select(ReserveCommitment).where(ReserveCommitment.plan_id == uuid.UUID(plan["id"]), ReserveCommitment.company_id == reserve))
    terms = confirmed_quote_terms()
    terms["expenses"] = [{"code": "reserve_holding", "title": "Удержание резерва", "amount_rub": "25.00",
        "source": "Синтетическое КП резерва", "version": "2", "required": True, "payer": "buyer"}]
    renewed = await client.post(f"/api/v3/reserve-commitments/{commitment.id}/decision", headers=auth(companies["reserve"][2]),
        json={"company_id": str(reserve), "decision": "approved", "capacity_units": 5000, "moq_units": 1000,
              "unit_price_rub": "12.00", "delivery_cost_rub": "2000.00", "lead_time_days": 8,
              "held_until": str(date.today()+timedelta(days=7)), "switchover_days": 2, "commercial_terms": terms})
    assert renewed.status_code == 200, renewed.text
    buyer_token = companies["buyer"][2]
    proposed = await current_plan(client, plan, buyer_token)
    assert proposed["status"] == "ready_for_confirmation" and proposed["confirmed_at"] is None
    confirmed = await client.post(f"/api/v3/resilience-plans/{plan['id']}/confirm", headers=auth(buyer_token),
        json={"approved": True, "expected_revision": proposed["version"]})
    assert confirmed.status_code == 200, confirmed.text
    assert confirmed.json()["current_allocations"][0]["deal_id"] == plan["current_allocations"][0]["deal_id"]
    scenario = next(row for row in confirmed.json()["scenarios"] if row["status"] == "proposed")
    recovered = await approve(client, confirmed.json(), scenario, buyer_token)
    assert recovered.status_code == 200, recovered.text
    assert recovered.json()["current_total_cost_rub"] == "62025.00"
