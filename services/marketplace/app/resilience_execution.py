"""Executable orders and one lock order for recovery and fulfilment.

Writers acquire Need -> Plan -> Deals -> company resources -> audit. A confirmed
shipment is protected in full even if the buyer has only accepted part of it.
"""
import uuid
from datetime import datetime, timezone
from fastapi import HTTPException
from sqlalchemy import select
from .models import Deal, DealCheckpoint, DealExecutionEvent, Need, ResiliencePlan
from .money import decimal
from .resources import transfer_to_deal


async def lock_execution_need(db, deal_id):
    need_id = await db.scalar(select(Deal.need_id).where(Deal.id == deal_id))
    if need_id:
        await db.scalar(select(Need).where(Need.id == need_id).with_for_update().execution_options(populate_existing=True))


async def execution_state(db, plan):
    deals = list((await db.scalars(select(Deal).where(Deal.need_id == plan.need_id)
        .order_by(Deal.id).with_for_update().execution_options(populate_existing=True))).all())
    state = {}
    for deal in deals:
        events = list((await db.scalars(select(DealExecutionEvent).where(DealExecutionEvent.deal_id == deal.id))).all())
        accepted = sum(e.units for e in events if e.kind == "acceptance" and e.status == "confirmed")
        cancelled = sum(e.units for e in events if e.kind == "cancellation" and e.status == "confirmed")
        shipment = await db.scalar(select(DealCheckpoint).where(DealCheckpoint.deal_id == deal.id, DealCheckpoint.kind == "shipment"))
        shipped = deal.units - cancelled if shipment and shipment.status == "completed" else sum(e.units for e in events if e.kind == "shipment" and e.status == "confirmed")
        state[str(deal.id)] = {"company_id": str(deal.seller_company_id), "protected_units": max(accepted, shipped),
            "legacy": deal.resilience_plan_id is None, "accepted_units": accepted, "cancelled_units": cancelled, "units": deal.units}
    return state


def protected_units(allocation, state):
    if allocation.get("deal_id"):
        return min(allocation["units"], sum(row["protected_units"] for key, row in state.items()
            if row["company_id"] == allocation["company_id"] and (key == allocation["deal_id"] or row.get("legacy"))))
    # Pre-S09 executions are also protected; they cannot be silently duplicated.
    return min(allocation["units"], sum(row["protected_units"] for row in state.values()
        if row["company_id"] == allocation["company_id"]))


async def create_execution_deal(db, *, plan, need, offer, allocation, snapshot, actor_user_id, scenario_id=None):
    deal = await db.scalar(select(Deal).where(Deal.resilience_plan_id == plan.id,
        Deal.seller_company_id == uuid.UUID(allocation["company_id"]), Deal.resilience_scenario_id == scenario_id))
    if deal:
        return deal
    deal = Deal(id=uuid.uuid4(), resilience_plan_id=plan.id, resilience_scenario_id=scenario_id,
        offer_id=offer.id, need_id=need.id, buyer_company_id=plan.buyer_company_id,
        seller_company_id=offer.company_id, performed_by_user_id=actor_user_id,
        units=allocation["units"], unit_price_rub=decimal(allocation["unit_price_rub"]),
        delivery_price_rub=decimal(allocation["delivery_cost_rub"]),
        total_price_rub=decimal(snapshot["estimate"]["total_rub"]), commercial_snapshot=snapshot, status="created")
    offer.status = "selected"
    db.add(deal)
    await db.flush()
    db.add_all([DealCheckpoint(deal_id=deal.id, kind=kind, status="pending", note="")
                for kind in ("production", "shipment", "delivery")])
    return deal


async def bind_execution(db, *, plan, need, offer, allocation, snapshot, actor_user_id,
                         anchor_type, anchor_id, scenario_id=None):
    deal = await create_execution_deal(db, plan=plan, need=need, offer=offer, allocation=allocation,
        snapshot=snapshot, actor_user_id=actor_user_id, scenario_id=scenario_id)
    await transfer_to_deal(db, company_id=offer.company_id, anchor_type=anchor_type,
                          anchor_id=anchor_id, deal_id=deal.id, units=allocation["units"])
    return {**allocation, "deal_id": str(deal.id), "commercial_snapshot": snapshot}


async def cancel_failed_remainder(db, *, allocation, state, actor_user_id, buyer_company_id, scenario_id):
    if not allocation.get("deal_id"):
        return
    deal = await db.get(Deal, uuid.UUID(allocation["deal_id"]))
    row = state.get(str(deal.id), {})
    remaining = deal.units - row.get("protected_units", 0) - row.get("cancelled_units", 0)
    if remaining <= 0:
        return
    db.add(DealExecutionEvent(deal_id=deal.id, actor_company_id=buyer_company_id,
        actor_user_id=actor_user_id, idempotency_key=scenario_id, kind="cancellation", units=remaining,
        note="Перенос неотгруженного остатка по согласованному плану восстановления", status="confirmed",
        decided_by_user_id=actor_user_id, decided_at=datetime.now(timezone.utc)))
    deal.status = "cancelled" if not row.get("protected_units") else "partially_accepted"


async def require_shipment_allowed(db, deal):
    if deal.resilience_plan_id:
        plan = await db.get(ResiliencePlan, deal.resilience_plan_id)
        if plan and (plan.status == "stale" or str(deal.seller_company_id) in plan.failed_company_ids):
            raise HTTPException(409, "Неотгруженный объём заблокирован отказом производителя. Нужен план восстановления")
