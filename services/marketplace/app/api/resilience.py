from ..commercial import offer_quote, estimate, frozen_snapshot, require_complete, holding_quotes, holding_total
from ..money import amount, decimal, exact_json, money_values
import uuid
from copy import deepcopy
from datetime import date, datetime, time, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import delete, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from ..admission import SpecificationCheck, admission_audit_payload, require_company_admission
from ..database import get_db
from ..deps import (
    CurrentUser,
    get_current_user,
    notify,
    require_company_admin,
    require_company_buyer,
    require_company_seller,
    require_verified_company,
)
from ..matching import _need_parts, _passport_matches, offer_unit_price, order_unit, ACTIVE_NEED_STATUSES
from ..models import (
    CapabilityPassport,
    Deal,
    DealExecutionEvent,
    Need,
    Offer,
    OptimizationVariantRecord,
    ReserveCommitment,
    ResilienceEvent,
    ResiliencePlan,
    ResilienceScenario,
)
from ..optimizer_client import calculate_resilience
from ..schemas import (
    FailureSimulationIn,
    ProducerFailureIn,
    PrimaryObligationOut,
    ReserveCommitmentOut,
    ReserveDecisionIn,
    ResilienceEventOut,
    ResiliencePlanConfirmIn,
    ResiliencePlanCreateIn,
    ResiliencePlanOut,
    ResilienceScenarioOut,
)
from ..resources import reserve, release, activate_hold, lock_company, reservations
from ..resilience_execution import execution_state, protected_units, bind_execution, cancel_failed_remainder, create_execution_deal
from ..trust import append_audit_event, record_human_approval

from ..requirements import require_current_evidence

router = APIRouter(tags=["stage-6-resilience"])


async def _user_company_ids(db: AsyncSession, user_id: uuid.UUID) -> set[uuid.UUID]:
    rows = await db.execute(
        text("SELECT company_id FROM auth.company_members WHERE user_id = :uid"),
        {"uid": user_id},
    )
    return set(rows.scalars().all())


async def _notify_company_admins(
    db: AsyncSession, company_id: uuid.UUID, message: str, type_: str, *, buyer: bool = False
) -> None:
    rows = await db.execute(
        text(
            "SELECT user_id FROM auth.company_members "
            f"WHERE company_id = :cid AND {'can_buy' if buyer else 'can_sell'} = true AND is_admin = true"
        ),
        {"cid": company_id},
    )
    for user_id in set(rows.scalars().all()):
        await notify(db, user_id, message, type_)


async def _notify_recovery(db, plan, scenario):
    await _notify_company_admins(db, plan.buyer_company_id, "Восстановление согласовано; заказы созданы в разделе сделок.",
        "replacement_activated", buyer=True)
    companies = set(scenario.result["failed_company_ids"]) | {row["company_id"] for row in scenario.result["replacement_allocations"]}
    for company in companies:
        await _notify_company_admins(db, uuid.UUID(company),
            "План восстановления активирован. Проверьте перенесённый объём и сделки.", "replacement_activated")


async def _can_view_plan(
    db: AsyncSession, plan: ResiliencePlan, user: CurrentUser
) -> bool:
    company_ids = await _user_company_ids(db, user.id)
    return plan.buyer_company_id in company_ids


async def _plan_out(db: AsyncSession, plan: ResiliencePlan) -> ResiliencePlanOut:
    reserves = (
        await db.execute(
            select(ReserveCommitment)
            .where(ReserveCommitment.plan_id == plan.id)
            .order_by(ReserveCommitment.reserve_tier, ReserveCommitment.created_at)
        )
    ).scalars().all()
    scenarios = (
        await db.execute(
            select(ResilienceScenario)
            .where(ResilienceScenario.plan_id == plan.id)
            .order_by(ResilienceScenario.created_at.desc())
        )
    ).scalars().all()
    events = (
        await db.execute(
            select(ResilienceEvent)
            .where(ResilienceEvent.plan_id == plan.id)
            .order_by(ResilienceEvent.created_at.desc())
            .limit(50)
        )
    ).scalars().all()
    need = await db.get(Need, plan.need_id)
    payload = await _resilience_payload(db, plan)
    reserve_out = []
    for item in reserves:
        tier, available, reason = await _reserve_availability(db, item, need)
        reserve_out.append(ReserveCommitmentOut.model_validate(item).model_copy(update={
            "effective_tier": tier, "available_units": available, "availability_reason": reason}))
    scenario_out = [ResilienceScenarioOut.model_validate(item).model_copy(update={
        "is_current": money_values(item.result.get("_input")) == money_values(payload)}) for item in scenarios]
    return ResiliencePlanOut(
        commercial_snapshot=plan.commercial_snapshot,        id=plan.id,
        need_id=plan.need_id,
        buyer_company_id=plan.buyer_company_id,
        baseline_variant_id=plan.baseline_variant_id,
        baseline_allocations=plan.baseline_allocations,
        baseline_total_cost_rub=plan.baseline_total_cost_rub,
        baseline_lead_time_days=plan.baseline_lead_time_days,
        current_allocations=plan.current_allocations,
        current_total_cost_rub=plan.current_total_cost_rub,
        current_lead_time_days=plan.current_lead_time_days,
        max_price_increase_pct=plan.max_price_increase_pct,
        max_delay_days=plan.max_delay_days,
        auto_replace_within_thresholds=plan.auto_replace_within_thresholds,
        failed_company_ids=plan.failed_company_ids,
        status=plan.status,
        version=plan.version,
        confirmed_at=plan.confirmed_at,
        reserves=reserve_out,
        scenarios=scenario_out,
        events=[ResilienceEventOut.model_validate(item) for item in events],
    )


async def _reserve_availability(db, item, need):
    if item.confirmation_status == "rejected":
        return "cold", 0, "Приглашение отклонено"
    if item.confirmation_status != "approved":
        return ("cold" if item.reserve_tier == "cold" else "warm"), 0, "Требуется подтверждение производителя"
    if not item.held_until or item.held_until < date.today():
        return "warm", 0, "Срок удержания истёк"
    if item.switchover_days is None:
        return "warm", 0, "Срок переключения не подтверждён"
    rows = [row for row in await reservations(db, item.company_id) if row.anchor_type == "reserve" and row.anchor_id == item.id]
    capacity = sum(row.units for row in rows if row.status == "held" and row.expires_at
                   and row.expires_at > datetime.now(timezone.utc))
    if not capacity:
        return "warm", 0, "Резерв уже назначен или мощность недоступна"
    source_offer = await db.get(Offer, item.offer_id) if item.offer_id else None
    try:
        await require_company_admission(db, item.company_id, SpecificationCheck(category=need.category,
            subcategory=need.subcategory, characteristics=need.characteristics, category_profile=need.category_profile,
            product_id=source_offer.product_id if source_offer else None, volume_units=capacity,
            moq_units=item.confirmed_moq_units, label="резерв"), context="Резерв недоступен")
    except HTTPException as error:
        return "warm", 0, str(error.detail)
    return "hot", min(capacity, item.confirmed_capacity_units or 0), None


async def _primary_payload(db, plan):
    state = await execution_state(db, plan)
    allocations = plan.failure_allocations or plan.current_allocations or plan.baseline_allocations
    return [{"company_id": item["company_id"], "units": item["units"],
        "protected_units": protected_units(item, state), "unit_price_rub": item["unit_price_rub"],
        "additional_cost_rub": item.get("additional_cost_rub", 0),
        "delivery_cost_rub": item.get("delivery_cost_rub", 0), "lead_time_days": item["lead_time_days"]}
        for item in allocations]


async def _resilience_payload(db: AsyncSession, plan: ResiliencePlan) -> dict:
    need = await db.get(Need, plan.need_id)
    primary = await _primary_payload(db, plan)
    primary_ids = {item["company_id"] for item in primary}
    commitments = list((await db.scalars(select(ReserveCommitment).where(
        ReserveCommitment.plan_id == plan.id, ReserveCommitment.confirmation_status != "rejected"))).all())
    reserve_options = []
    for item in commitments:
        if str(item.company_id) in primary_ids or item.reserve_tier == "cold":
            continue
        approved = item.confirmation_status == "approved"
        capacity = item.confirmed_capacity_units if approved else item.proposed_capacity_units
        moq = item.confirmed_moq_units if approved else item.proposed_moq_units
        price = item.confirmed_unit_price_rub if approved else item.proposed_unit_price_rub
        delivery = item.confirmed_delivery_cost_rub if approved else item.proposed_delivery_cost_rub
        lead = item.confirmed_lead_time_days if approved else item.proposed_lead_time_days
        if None in (capacity, moq, price, delivery, lead):
            continue
        quote = item.commercial_snapshot or {}
        if not quote.get("estimate", {}).get("complete"):
            continue
        terms = item.commercial_terms or {}
        expected_basis = plan.baseline_allocations[0].get("comparison_basis")
        if expected_basis and any(terms.get(key) != value for key, value in expected_basis.items()):
            continue
        if any(expense["required"] and expense["amount_rub"] is None for expense in terms.get("expenses", [])):
            continue
        tier, available, reason = await _reserve_availability(db, item, need)
        # Expired/used/revoked holds cannot be presented as available alternatives.
        if approved and available == 0 and reason != "Срок переключения не подтверждён":
            continue
        reserve_options.append({"company_id": str(item.company_id), "unit_price_rub": price,
            "additional_cost_rub": sum((decimal(expense["amount_rub"]) for expense in terms.get("expenses", [])
                if expense["amount_rub"] is not None and expense["code"] != "reserve_holding"), decimal(0)),
            "moq_units": moq, "capacity_units": available if tier == "hot" else capacity,
            "lead_time_days": lead, "switchover_days": item.switchover_days,
            "delivery_cost_rub": delivery, "reliability": None, "price_tiers": item.price_tiers,
            "serves_region": True, "country": "RU", "reserve_tier": tier,
            "confirmation_status": item.confirmation_status,
            "held_until": item.held_until.isoformat() if item.held_until else None})
    return {"primary_allocations": primary,
        "reserve_holding_total_rub": holding_total(holding_quotes(plan.commercial_snapshot, commitments)),
        "reserve_options": reserve_options, "max_price_increase_pct": plan.max_price_increase_pct,
        "max_delay_days": plan.max_delay_days}


def _same_failure_set(result: dict, company_ids: list[str]) -> bool:
    return set(result["failed_company_ids"]) == set(company_ids)


async def _lock_plan_need(db, plan_id):
    need_id = await db.scalar(select(ResiliencePlan.need_id).where(ResiliencePlan.id == plan_id))
    if need_id is not None:
        await db.scalar(select(Need).where(Need.id == need_id).with_for_update().execution_options(populate_existing=True))


async def _commitment_offer(db, commitment, need):
    if commitment.offer_id:
        offer = await db.get(Offer, commitment.offer_id)
        if offer:
            return offer
    require_complete(commitment.commercial_snapshot.get("estimate") if commitment.commercial_snapshot else None)
    offer = Offer(id=uuid.uuid4(), need_id=need.id, company_id=commitment.company_id,
        created_by_user_id=commitment.confirmed_by_user_id,
        price_rub=commitment.confirmed_unit_price_rub, available_units=commitment.confirmed_capacity_units,
        lead_time_days=commitment.confirmed_lead_time_days, delivery_cost_rub=commitment.confirmed_delivery_cost_rub,
        moq_units=commitment.confirmed_moq_units, price_tiers=commitment.price_tiers,
        valid_until=commitment.held_until, commercial_terms=commitment.commercial_terms,
        commercial_quote=commitment.commercial_snapshot, status="selected", resource_kind="capacity")
    db.add(offer)
    await db.flush()
    commitment.offer_id = offer.id
    return offer


async def _bind_saved_orders(db, plan):
    """Upgrade pre-S09 assignments on an authorized write, using saved consent."""
    if not plan.commercial_snapshot or not plan.current_allocations:
        return
    need = await db.get(Need, plan.need_id)
    bound = []
    baseline = {row["allocation"]["company_id"]: row for row in plan.commercial_snapshot.get("primary", [])}
    for allocation in plan.current_allocations:
        if allocation.get("deal_id") or allocation.get("role") == "executed":
            bound.append(allocation)
            continue
        company_id = uuid.UUID(allocation["company_id"])
        saved = baseline.get(allocation["company_id"], {})
        snapshot = allocation.get("commercial_snapshot") or saved.get("commercial_snapshot")
        require_complete(snapshot.get("estimate") if snapshot else None)
        if snapshot["need"]["revision"] != need.revision:
            raise HTTPException(409, "Сохранённое назначение относится к прежней спецификации")
        if allocation.get("role") == "reserve":
            commitment = await db.scalar(select(ReserveCommitment).where(ReserveCommitment.plan_id == plan.id,
                ReserveCommitment.company_id == company_id))
            if not commitment:
                raise HTTPException(409, "Подтверждённый резерв не найден")
            saved_offer = await _commitment_offer(db, commitment, need)
            offer_id = saved_offer.id
            scenario_id = (snapshot.get("resource") or {}).get("scenario_id")
            if not scenario_id:
                raise HTTPException(409, "У сохранённой замены отсутствует согласованный сценарий")
            anchor_type, anchor_id = "reserve", commitment.id
            scenario_id = uuid.UUID(scenario_id)
        else:
            offer_id = uuid.UUID(saved["offer_id"])
            anchor_type, anchor_id, scenario_id = "resilience_primary", plan.id, None
        offer = await db.get(Offer, offer_id)
        if not offer:
            raise HTTPException(409, "Исходное КП сохранённого назначения не найдено")
        if allocation["company_id"] in plan.failed_company_ids:
            rows = [row for row in await reservations(db, company_id) if row.anchor_type == anchor_type and row.anchor_id == anchor_id]
            if not any(row.status == "committed" for row in rows):
                deal = await create_execution_deal(db, plan=plan, need=need, offer=offer, allocation=allocation,
                    snapshot=snapshot, actor_user_id=plan.confirmed_by_user_id, scenario_id=scenario_id)
                for row in rows:
                    row.anchor_type, row.anchor_id = "deal", deal.id
                bound.append({**allocation, "deal_id": str(deal.id), "commercial_snapshot": snapshot})
                continue
        bound.append(await bind_execution(db, plan=plan, need=need, offer=offer, allocation=allocation,
            snapshot=snapshot, actor_user_id=plan.confirmed_by_user_id, anchor_type=anchor_type,
            anchor_id=anchor_id, scenario_id=scenario_id))
    plan.current_allocations = bound
    by_company = {row["company_id"]: row for row in bound if row["company_id"] in baseline and row.get("role") != "reserve"}
    plan.baseline_allocations = [{**row, **by_company.get(row["company_id"], {})} for row in plan.baseline_allocations]


async def _lock_plan_resources(db, plan):
    await execution_state(db, plan)
    commitments = list((await db.scalars(select(ReserveCommitment).where(ReserveCommitment.plan_id == plan.id))).all())
    companies = {uuid.UUID(item["company_id"]) for item in plan.baseline_allocations} | {item.company_id for item in commitments}
    for company_id in sorted(companies, key=str):
        await lock_company(db, company_id)
    await _bind_saved_orders(db, plan)


async def _validate_activation(db, plan, scenario, *, automatic):
    need = await db.get(Need, plan.need_id)
    await require_current_evidence(db, need)
    if need.status not in {*ACTIVE_NEED_STATUSES, "matched"} or need.deadline_date < date.today():
        raise HTTPException(409, "Потребность закрыта или срок поставки истёк")
    result = scenario.result
    if result["uncovered_units"] or result["unconfirmed_units"] or not result["replacement_allocations"]:
        raise HTTPException(409, "Нельзя активировать неполную или неподтверждённую замену")
    payload = await _resilience_payload(db, plan)
    failed = set(result["failed_company_ids"])
    for row in payload["primary_allocations"]:
        if row["company_id"] in failed and row["protected_units"] >= row["units"]:
            raise HTTPException(409, "Объём выпавшего производителя уже получен или отгружен: перенос не требуется")
    old_primary = {row["company_id"]: row for row in result.get("_input", {}).get("primary_allocations", [])}
    if any(row["company_id"] in failed and row["protected_units"] != old_primary.get(row["company_id"], {}).get("protected_units") for row in payload["primary_allocations"]):
        raise HTTPException(409, "Часть объёма уже исполнена: требуется ручное решение с пересчётом замены")
    if money_values(result.get("_input")) != money_values(payload):
        raise HTTPException(409, "Ресурсы или исполнение изменились. Пересчитайте замену")
    failed = set(result["failed_company_ids"])
    expected = sum(row["units"] - row["protected_units"] for row in payload["primary_allocations"] if row["company_id"] in failed)
    if not expected or sum(row["units"] for row in result["replacement_allocations"]) != expected:
        raise HTTPException(409, "Переносимый остаток не соответствует фактическому исполнению")
    if need.budget_rub is not None and decimal(result["new_total_cost_rub"]) > need.budget_rub:
        raise HTTPException(409, "Полная стоимость восстановления превышает бюджет потребности")
    if result["new_lead_time_days"] > (need.deadline_date - date.today()).days:
        raise HTTPException(409, "Восстановление не укладывается в срок потребности")
    if automatic:
        if any(row["protected_units"] > 0 for row in payload["primary_allocations"] if row["company_id"] in failed):
            raise HTTPException(409, "Частично исполненный заказ требует ручного согласования остатка")
        increase = decimal(result["new_total_cost_rub"]) - decimal(plan.baseline_total_cost_rub)
        limit = decimal(plan.baseline_total_cost_rub) * decimal(plan.max_price_increase_pct) / 100
        if increase > limit or result["new_lead_time_days"] > plan.baseline_lead_time_days + plan.max_delay_days:
            raise HTTPException(409, "Нужное восстановление превышает заранее согласованные пороги")
    replacement_total = decimal(0)
    for row in result["replacement_allocations"]:
        commitment = await db.scalar(select(ReserveCommitment).where(ReserveCommitment.plan_id == plan.id,
            ReserveCommitment.company_id == uuid.UUID(row["company_id"])))
        if not commitment:
            raise HTTPException(409, "Подтверждённый резерв не найден")
        tier, capacity, reason = await _reserve_availability(db, commitment, need)
        if tier != "hot" or row["units"] > capacity:
            raise HTTPException(409, reason or "Удержанной мощности недостаточно")
        if row["lead_time_days"] != commitment.confirmed_lead_time_days + commitment.switchover_days:
            raise HTTPException(409, "Срок переключения изменился. Пересчитайте замену")
        terms = commitment.commercial_terms or {}
        quote = estimate(units=row["units"], unit_price=row["unit_price_rub"], delivery=commitment.confirmed_delivery_cost_rub,
            terms=terms, buyer=plan.buyer_company_id, seller=commitment.company_id,
            source={"type": "reserve_commitment", "id": str(commitment.id)}, switching=True)
        require_complete(quote)
        price = decimal(commitment.confirmed_unit_price_rub)
        for price_tier in sorted(commitment.price_tiers, key=lambda tier: tier["min_units"]):
            if row["units"] >= price_tier["min_units"]: price = decimal(price_tier["unit_price_rub"])
        if row["units"] < commitment.confirmed_moq_units or decimal(row["unit_price_rub"]) != price or decimal(row["total_cost_rub"]) != decimal(quote["total_rub"]):
            raise HTTPException(409, "Условия назначения не совпадают с подтверждённым КП резерва")
        replacement_total += decimal(quote["total_rub"])
    original_total = decimal(0)
    lost = decimal(0)
    for row in payload["primary_allocations"]:
        total = amount(row["units"] * decimal(row["unit_price_rub"]) + decimal(row["delivery_cost_rub"]) + decimal(row.get("additional_cost_rub", 0)))
        original_total += total
        if row["company_id"] in failed:
            lost += amount((row["units"] - row["protected_units"]) * decimal(row["unit_price_rub"])) if row["protected_units"] else total
    actual_total = amount(original_total - lost + replacement_total + decimal(payload["reserve_holding_total_rub"]))
    if actual_total != decimal(result["new_total_cost_rub"]):
        raise HTTPException(409, "Итог восстановления не совпадает с полной согласованной сметой")
    return need


async def _activate_scenario(
    db: AsyncSession,
    plan: ResiliencePlan,
    scenario: ResilienceScenario,
    actor_user_id: uuid.UUID | None,
    automatic: bool,
) -> None:
    await _validate_activation(db, plan, scenario, automatic=automatic)
    state = await execution_state(db, plan)
    failed = set(scenario.result["failed_company_ids"])
    source_allocations = plan.failure_allocations or plan.current_allocations or plan.baseline_allocations
    surviving = []
    for item in source_allocations:
        if item["company_id"] not in failed:
            surviving.append(deepcopy(item))
        else:
            retained = protected_units(item, state)
            if retained:
                surviving.append({**item, "units": retained, "role": "executed",
                    "total_cost_rub": amount(decimal(item["total_cost_rub"]) - amount((item["units"] - retained) * decimal(item["unit_price_rub"])))})
            await cancel_failed_remainder(db, allocation=item, state=state,
                actor_user_id=plan.confirmed_by_user_id if automatic else actor_user_id,
                buyer_company_id=plan.buyer_company_id, scenario_id=scenario.id)
    replacements = [
        {**item, "role": "reserve"}
        for item in scenario.result["replacement_allocations"]
    ]
    need = await db.scalar(select(Need).where(Need.id == plan.need_id).with_for_update().execution_options(populate_existing=True))
    if need is not None:
        await require_current_evidence(db, need)
    # Deterministic company order prevents lock inversion for N-2 replacements.
    for replacement in sorted(replacements, key=lambda row: row["company_id"]):
        company_id = uuid.UUID(replacement["company_id"])
        commitment = await db.scalar(select(ReserveCommitment).where(ReserveCommitment.plan_id == plan.id, ReserveCommitment.company_id == company_id))
        if commitment is None:
            raise HTTPException(409, "Подтверждённый резерв не найден")
        source_offer = await db.get(Offer, commitment.offer_id) if commitment.offer_id else None
        await require_company_admission(db, company_id, SpecificationCheck(category=need.category,
            product_id=source_offer.product_id if source_offer else None, volume_units=replacement["units"], category_profile=need.category_profile,
            subcategory=need.subcategory,
            characteristics=need.characteristics, moq_units=replacement["units"], label="спецификация восстановления"), context="Замена не активирована")
        require_complete(commitment.commercial_snapshot.get('estimate') if commitment.commercial_snapshot else None)
        recovery_quote = estimate(units=replacement['units'],unit_price=replacement['unit_price_rub'],delivery=replacement['delivery_cost_rub'],
            terms=commitment.commercial_terms,buyer=plan.buyer_company_id,seller=company_id,
            source={'type':'recovery','scenario_id':str(scenario.id),'commitment_id':str(commitment.id)},switching=True)
        require_complete(recovery_quote)
        replacement['commercial_snapshot'] = frozen_snapshot(estimate_value=recovery_quote,need=need,offer=source_offer,
            resource={'commitment_id':str(commitment.id),'scenario_id':str(scenario.id)})
        await activate_hold(db, company_id=company_id, anchor_id=commitment.id, units=replacement["units"])
        if source_offer is None:
            source_offer = await _commitment_offer(db, commitment, need)
        bound = await bind_execution(db, plan=plan, need=need, offer=source_offer, allocation=replacement,
            snapshot=replacement["commercial_snapshot"], actor_user_id=actor_user_id,
            anchor_type="reserve", anchor_id=commitment.id, scenario_id=scenario.id)
        replacement.update(bound)
    plan.current_allocations = [*surviving, *replacements]
    plan.current_total_cost_rub = scenario.result["new_total_cost_rub"]
    plan.current_lead_time_days = scenario.result["new_lead_time_days"]
    plan.status = "recovered"
    plan.failure_allocations = []
    plan.failed_company_ids = []
    plan.version += 1
    scenario.status = "activated"
    scenario.approved_by_user_id = actor_user_id
    db.add(
        ResilienceEvent(
            plan_id=plan.id,
            event_type="replacement_activated_automatically" if automatic else "replacement_approved",
            actor_user_id=actor_user_id,
            payload={
                "scenario_id": str(scenario.id),
                "version": plan.version,
                "price_delta_rub": scenario.result["price_delta_rub"],
                "delay_days": scenario.result["delay_days"],
            },
        )
    )
    await append_audit_event(
        db,
        event_type="recovery_activated",
        entity_type="resilience_scenario",
        entity_id=scenario.id,
        actor_user_id=actor_user_id,
        actor_company_id=plan.buyer_company_id,
        source_refs=[
            {"type": "resilience_plan", "id": str(plan.id)},
            {"type": "scenario", "id": str(scenario.id)},
            {"type": "baseline_variant", "id": str(plan.baseline_variant_id)},
        ],
        explanation="Конфигурация восстановления активирована после программной проверки покрытия, цены и срока.",
        payload={
            "automatic": automatic,
            "baseline_cost_rub": plan.baseline_total_cost_rub,
            "new_cost_rub": scenario.result["new_total_cost_rub"],
            "buyer_value_rub": amount(decimal(plan.baseline_total_cost_rub) - decimal(scenario.result["new_total_cost_rub"])),
            "price_delta_rub": scenario.result["price_delta_rub"],
            "delay_days": scenario.result["delay_days"],
        },
    )


async def _calculate_and_store(
    db: AsyncSession, plan: ResiliencePlan, actor_user_id: uuid.UUID | None = None
) -> dict:
    if plan.status == "stale":
        raise HTTPException(409, "Спецификация изменилась. Создайте новый ресурсный план")
    payload = await _resilience_payload(db, plan)
    result = await calculate_resilience(payload)
    for item in result["scenarios"]:
        item["_input"] = deepcopy(payload)
    await db.execute(
        delete(ResilienceScenario).where(
            ResilienceScenario.plan_id == plan.id,
            ResilienceScenario.status == "calculated",
        )
    )
    for item in result["scenarios"]:
        db.add(
            ResilienceScenario(
                plan_id=plan.id,
                scenario_type=item["scenario_type"],
                failed_company_ids=item["failed_company_ids"],
                result=item,
                input_hash=result["input_hash"],
                status="calculated",
            )
        )

    if not plan.failed_company_ids:
        if plan.status in {"preparing_reserves", "ready_for_confirmation"}:
            plan.status = "ready_for_confirmation"
        return result

    await db.execute(
        update(ResilienceScenario)
        .where(
            ResilienceScenario.plan_id == plan.id,
            ResilienceScenario.status == "proposed",
        )
        .values(status="superseded")
    )
    live_result = next(
        (
            item
            for item in result["scenarios"]
            if _same_failure_set(item, plan.failed_company_ids)
        ),
        None,
    )
    if live_result is None:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail="Оптимизатор не построил сценарий для указанного отказа",
        )
    live = ResilienceScenario(
        plan_id=plan.id,
        scenario_type="live_failure",
        failed_company_ids=plan.failed_company_ids,
        result=live_result,
        input_hash=result["input_hash"],
        status="proposed",
    )
    db.add(live)
    await db.flush()
    if plan.confirmed_at is None and plan.commercial_snapshot:
        plan.status = "ready_for_confirmation"
        return result
    if live_result["uncovered_units"] > 0:
        plan.status = "partially_covered"
    elif live_result["unconfirmed_units"] > 0:
        plan.status = "awaiting_reserve_reconfirmation"
    elif (
        plan.auto_replace_within_thresholds
        and live_result["auto_eligible"]
        and plan.confirmed_at is not None
    ):
        try:
            await _validate_activation(db, plan, live, automatic=True)
        except HTTPException as error:
            plan.status = "recovery_proposed"
            db.add(ResilienceEvent(plan_id=plan.id, event_type="automatic_replacement_blocked",
                actor_user_id=actor_user_id, payload={"scenario_id": str(live.id), "reasons": [str(error.detail)]}))
            await _notify_company_admins(db, plan.buyer_company_id,
                f"Автоматическая замена не выполнена: {error.detail}. Требуется пересчёт или ручное решение.",
                "reserve_confirmation_required", buyer=True)
        else:
            await _activate_scenario(db, plan, live, actor_user_id, automatic=True)
            await _notify_recovery(db, plan, live)
    else:
        plan.status = "recovery_proposed"
    return result


@router.post(
    "/needs/{need_id}/resilience-plans",
    response_model=ResiliencePlanOut,
    status_code=status.HTTP_201_CREATED,
)
async def create_resilience_plan(
    need_id: uuid.UUID,
    data: ResiliencePlanCreateIn,
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    need = await db.scalar(select(Need).where(Need.id == need_id).with_for_update().execution_options(populate_existing=True))
    if need is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Потребность не найдена")
    await require_company_buyer(need.company_id, user, db)
    await require_company_admin(need.company_id, user, db)
    await require_verified_company(need.company_id, user, db)
    await require_current_evidence(db, need)
    existing = (
        await db.execute(select(ResiliencePlan).where(ResiliencePlan.need_id == need.id, ResiliencePlan.status != "stale"))
    ).scalar_one_or_none()
    if existing is not None:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail="Для потребности уже создан план устойчивости",
        )
    variant = await db.get(OptimizationVariantRecord, data.variant_id)
    if (
        variant is None
        or variant.need_id != need.id
        or variant.result.get("stale")
        or not variant.result.get("feasible")
    ):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Нужен выполнимый вариант оптимизатора этой потребности",
        )
    allocations = variant.result.get("allocations", [])
    if not allocations:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="В выбранном варианте нет основных производителей",
        )
    primary_ids = {uuid.UUID(item["company_id"]) for item in allocations}
    plan = ResiliencePlan(
        need_id=need.id,
        buyer_company_id=need.company_id,
        baseline_variant_id=variant.id,
        baseline_allocations=allocations,
        baseline_total_cost_rub=variant.result["total_cost_rub"],
        baseline_lead_time_days=variant.result["max_lead_time_days"],
        current_allocations=allocations,
        current_total_cost_rub=variant.result["total_cost_rub"],
        current_lead_time_days=variant.result["max_lead_time_days"],
        max_price_increase_pct=data.max_price_increase_pct,
        max_delay_days=data.max_delay_days,
        auto_replace_within_thresholds=data.auto_replace_within_thresholds,
        status="preparing_reserves",
    )
    db.add(plan)
    await db.flush()

    offers = (
        await db.execute(
            select(Offer).where(
                Offer.need_id == need.id,
                Offer.status == "sent",
            )
        )
    ).scalars().all()
    reserve_company_ids = set()
    for offer in offers:
        if offer.company_id in primary_ids:
            continue
        if offer.valid_until is not None and offer.valid_until < date.today():
            continue
        reserve_company_ids.add(offer.company_id)
        db.add(
            ReserveCommitment(
                plan_id=plan.id,
                company_id=offer.company_id,
                offer_id=offer.id,
                reserve_tier="warm",
                confirmation_status="pending",
                proposed_capacity_units=offer.available_units,
                proposed_moq_units=offer.moq_units,
                commercial_terms=offer.commercial_terms,
                commercial_snapshot=offer.commercial_quote,
                proposed_unit_price_rub=offer.price_rub,
                proposed_delivery_cost_rub=offer.delivery_cost_rub,
                proposed_lead_time_days=offer.lead_time_days,
                price_tiers=offer.price_tiers,
            )
        )

    verified_ids = set(
        (
            await db.execute(
                text(
                    "SELECT id FROM auth.companies "
                    "WHERE country = 'RU' AND verification_status = 'verified'"
                )
            )
        ).scalars().all()
    )
    common = _need_parts(need)[0]
    passports = (await db.execute(select(CapabilityPassport))).scalars().all()
    for passport in passports:
        if (
            passport.company_id in primary_ids
            or passport.company_id in reserve_company_ids
            or passport.company_id == need.company_id
            or passport.company_id not in verified_ids
            or not _passport_matches(passport, need.category, {**common,**_need_parts(need)[1]},need.subcategory,need.volume_units)
        ):
            continue
        db.add(
            ReserveCommitment(
                plan_id=plan.id,
                company_id=passport.company_id,
                reserve_tier="cold",
                confirmation_status="pending",
                proposed_capacity_units=passport.max_order_units,
                proposed_moq_units=passport.min_order_units,
            )
        )
        reserve_company_ids.add(passport.company_id)
    db.add(
        ResilienceEvent(
            plan_id=plan.id,
            event_type="resilience_plan_created",
            actor_user_id=user.id,
            actor_company_id=need.company_id,
            payload={
                "variant_id": str(variant.id),
                "primary_company_ids": [str(item) for item in sorted(primary_ids, key=str)],
                "automatic_threshold_preapproval_requested": data.auto_replace_within_thresholds,
            },
        )
    )
    await append_audit_event(
        db,
        event_type="resilience_baseline_fixed",
        entity_type="resilience_plan",
        entity_id=plan.id,
        actor_user_id=user.id,
        actor_company_id=plan.buyer_company_id,
        source_refs=[{"type": "baseline_variant", "id": str(plan.baseline_variant_id)}],
        explanation="До применения восстановления зафиксированы исходная стоимость, срок и распределение оптимизатора.",
        payload={
            "baseline_total_cost_rub": plan.baseline_total_cost_rub,
            "baseline_lead_time_days": plan.baseline_lead_time_days,
            "baseline_allocations": plan.baseline_allocations,
        },
    )
    await db.flush()
    for company_id in reserve_company_ids:
        await _notify_company_admins(
            db,
            company_id,
            "Ваша компания приглашена в резерв. Подтвердите цену и удержание мощности.",
            "reserve_invitation",
        )
    await _calculate_and_store(db, plan, user.id)
    await db.commit()
    return await _plan_out(db, plan)


@router.get("/resilience-plans/mine", response_model=list[ResiliencePlanOut])
async def list_my_resilience_plans(
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    company_ids = await _user_company_ids(db, user.id)
    if not company_ids:
        return []
    plans = (
        await db.execute(
            select(ResiliencePlan)
            .where(ResiliencePlan.buyer_company_id.in_(company_ids))
            .order_by(ResiliencePlan.updated_at.desc())
        )
    ).scalars().all()
    return [await _plan_out(db, item) for item in plans]


@router.get("/resilience-plans/{plan_id}", response_model=ResiliencePlanOut)
async def get_resilience_plan(
    plan_id: uuid.UUID,
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    plan = await db.get(ResiliencePlan, plan_id)
    if plan is None or not await _can_view_plan(db, plan, user):
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="План устойчивости не найден")
    return await _plan_out(db, plan)


@router.post("/resilience-plans/{plan_id}/confirm", response_model=ResiliencePlanOut)
async def confirm_resilience_plan(
    plan_id: uuid.UUID,
    data: ResiliencePlanConfirmIn,
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await _lock_plan_need(db, plan_id)
    plan = await db.scalar(select(ResiliencePlan).where(ResiliencePlan.id == plan_id).with_for_update().execution_options(populate_existing=True))
    if plan is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="План устойчивости не найден")
    await require_company_buyer(plan.buyer_company_id, user, db)
    await require_company_admin(plan.buyer_company_id, user, db)
    await require_verified_company(plan.buyer_company_id, user, db)
    if plan.status != "ready_for_confirmation":
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail="План должен быть рассчитан до подтверждения",
        )
    if data.expected_revision is None:
        raise HTTPException(428, "Подтвердите показанную версию плана")
    if data.expected_revision != plan.version:
        raise HTTPException(409, "План изменился. Обновите его перед подтверждением")
    need = await db.scalar(select(Need).where(Need.id == plan.need_id).with_for_update().execution_options(populate_existing=True))
    await require_current_evidence(db, need)
    if (need.status not in ACTIVE_NEED_STATUSES and not (need.status == "matched" and plan.commercial_snapshot)) or need.deadline_date < date.today():
        raise HTTPException(409, "Потребность уже закрыта или срок поставки истёк")
    if sum(item["units"] for item in plan.baseline_allocations) != need.volume_units:
        raise HTTPException(409, "Объём плана не соответствует потребности. Нужен новый расчёт")
    await _lock_plan_resources(db, plan)
    already_executing = bool(plan.commercial_snapshot)
    baseline_snapshots = []
    bound_allocations = []
    for allocation in sorted(plan.baseline_allocations, key=lambda item: item["company_id"]):
        company_id = uuid.UUID(allocation["company_id"])
        if already_executing:
            saved_deal = await db.scalar(select(Deal).where(Deal.resilience_plan_id == plan.id,
                Deal.resilience_scenario_id.is_(None), Deal.seller_company_id == company_id))
            if saved_deal:
                saved = next(item for item in plan.commercial_snapshot["primary"] if item["allocation"]["company_id"] == allocation["company_id"])
                baseline_snapshots.append(deepcopy(saved))
                bound_allocations.append({**allocation, "deal_id": str(saved_deal.id), "commercial_snapshot": saved_deal.commercial_snapshot})
                continue
        offers = list((await db.scalars(select(Offer).where(Offer.need_id == need.id, Offer.company_id == company_id,
            Offer.status.in_(["sent", "selected"]) if already_executing else Offer.status == "sent").with_for_update().execution_options(populate_existing=True))).all())
        matching = [offer for offer in offers if offer.moq_units <= allocation["units"] <= offer.available_units
            and offer_unit_price(offer, allocation["units"]) == decimal(allocation["unit_price_rub"])
            and offer.delivery_cost_rub == decimal(allocation["delivery_cost_rub"])
            and offer.lead_time_days == allocation["lead_time_days"]
            and offer.lead_time_days <= (need.deadline_date - date.today()).days
            and (offer.valid_until is None or offer.valid_until >= date.today())
            and (not allocation.get('offer_id') or (str(offer.id)==allocation['offer_id'] and offer.revision==allocation['offer_revision']))]
        if len(matching) != 1:
            raise HTTPException(409, "Исходное предложение изменилось или истекло. Пересчитайте план")
        offer = matching[0]
        require_complete(offer.commercial_quote['estimate'] if offer.commercial_quote else None)
        if offer.commercial_quote['need']['revision']!=need.revision:
            raise HTTPException(409,'Потребность изменилась после подтверждения исходного КП')
        admission = await require_company_admission(db, company_id, SpecificationCheck(category=need.category,
            subcategory=need.subcategory,
            characteristics=need.characteristics, moq_units=allocation["units"], product_id=offer.product_id,
            volume_units=allocation["units"],category_profile=need.category_profile), context="Основной объём не подтверждён")
        allocated_quote = await offer_quote(db,offer,need,units=allocation['units'])
        if decimal(allocated_quote['estimate']['total_rub']) != decimal(allocation['total_cost_rub']):
            raise HTTPException(409,'Полная смета исходного КП изменилась. Пересчитайте план перед согласием')
        baseline_snapshots.append({
            "allocation": deepcopy(allocation),
            "commercial_snapshot": allocated_quote,
            "offer_id": str(offer.id),
            "need_id": str(need.id),
            "need_revision": need.revision,
            "admission": admission_audit_payload(admission, specification={
                "category": need.category, "subcategory": need.subcategory,
                "characteristics": need.characteristics, "category_profile": need.category_profile,
                "moq_units": allocation["units"],
            }),
        })
        existing = await db.scalar(select(Deal).where(Deal.resilience_plan_id == plan.id,
            Deal.resilience_scenario_id.is_(None), Deal.seller_company_id == company_id))
        if existing:
            bound_allocations.append({**allocation, "deal_id": str(existing.id), "commercial_snapshot": existing.commercial_snapshot})
        else:
            await reserve(db, company_id=company_id, anchor_type="resilience_primary", anchor_id=plan.id,
                units=allocation["units"], deadline=need.deadline_date, resource_kind=offer.resource_kind, product_id=offer.product_id,
                category=need.category, subcategory=need.subcategory, unit=order_unit(need.characteristics))
            bound_allocations.append(await bind_execution(db, plan=plan, need=need, offer=offer,
                allocation=allocation, snapshot=allocated_quote, actor_user_id=user.id,
                anchor_type="resilience_primary", anchor_id=plan.id))
    commitments = list((await db.scalars(select(ReserveCommitment).where(ReserveCommitment.plan_id==plan.id, ReserveCommitment.confirmation_status=='approved'))).all())
    quotes = holding_quotes(plan.commercial_snapshot,commitments)
    holding = holding_total(quotes)
    plan.baseline_total_cost_rub = sum((decimal(item['total_cost_rub']) for item in plan.baseline_allocations),decimal(0)) + holding
    if need.budget_rub is not None and plan.baseline_total_cost_rub>need.budget_rub:
        raise HTTPException(409,"Полная смета с удержанием резерва превышает бюджет потребности")
    plan.current_total_cost_rub = sum((decimal(item["total_cost_rub"]) for item in plan.current_allocations), decimal(0)) + holding if already_executing else plan.baseline_total_cost_rub
    if need.budget_rub is not None and plan.current_total_cost_rub > need.budget_rub:
        raise HTTPException(409, "Полная текущая смета с удержанием резерва превышает бюджет потребности")
    plan.commercial_snapshot = {'schema_version':1,'primary':baseline_snapshots,
        'holding_quotes':quotes,
        'reserve_holding_total_rub':str(holding),'total_rub':str(plan.baseline_total_cost_rub)}
    plan.baseline_allocations = bound_allocations
    if not already_executing:
        plan.current_allocations = deepcopy(bound_allocations)
    need.status = "matched"
    plan.status = "active"
    plan.confirmed_by_user_id = user.id
    plan.confirmed_at = datetime.now(timezone.utc)
    db.add(
        ResilienceEvent(
            plan_id=plan.id,
            event_type="resilience_plan_confirmed",
            actor_user_id=user.id,
            actor_company_id=plan.buyer_company_id,
            payload={
                "auto_replace_within_thresholds": plan.auto_replace_within_thresholds,
                "max_price_increase_pct": plan.max_price_increase_pct,
                "max_delay_days": plan.max_delay_days,
            },
        )
    )
    await record_human_approval(
        db,
        action="confirm_resilience_plan",
        entity_type="resilience_plan",
        entity_id=plan.id,
        actor_user_id=user.id,
        actor_company_id=plan.buyer_company_id,
        permission="company_admin+buyer+verified",
        decision="approved",
        payload={
            "baseline_variant_id": str(plan.baseline_variant_id),
            "plan_version": plan.version,
            "baseline_allocations": baseline_snapshots,
            "max_price_increase_pct": plan.max_price_increase_pct,
            "max_delay_days": plan.max_delay_days,
            "auto_replace_within_thresholds": plan.auto_replace_within_thresholds,
        },
        source_refs=[
            {"type": "baseline_variant", "id": str(plan.baseline_variant_id)},
            {"type": "resilience_plan", "id": str(plan.id)},
        ],
        explanation="Администратор проверенной компании-покупателя явно подтвердил конфигурацию и пределы замены.",
    )
    if plan.failed_company_ids:
        await _calculate_and_store(db, plan, user.id)
    await db.commit()
    return await _plan_out(db, plan)


@router.get(
    "/reserve-invitations/{company_id}", response_model=list[ReserveCommitmentOut]
)
async def list_reserve_invitations(
    company_id: uuid.UUID,
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await require_company_seller(company_id, user, db)
    result = await db.execute(
        select(ReserveCommitment)
        .where(ReserveCommitment.company_id == company_id)
        .order_by(ReserveCommitment.updated_at.desc())
    )
    out = []
    for commitment in result.scalars().all():
        plan = await db.get(ResiliencePlan, commitment.plan_id)
        need = await db.get(Need, plan.need_id)
        tier, available, reason = await _reserve_availability(db, commitment, need)
        out.append(ReserveCommitmentOut.model_validate(commitment).model_copy(update={
            "effective_tier": tier, "available_units": available, "availability_reason": reason}))
    return out


@router.get(
    "/primary-obligations/{company_id}", response_model=list[PrimaryObligationOut]
)
async def list_primary_obligations(
    company_id: uuid.UUID,
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await require_company_seller(company_id, user, db)
    plans = (
        await db.execute(
            select(ResiliencePlan)
            .where(ResiliencePlan.confirmed_at.is_not(None))
            .order_by(ResiliencePlan.updated_at.desc())
        )
    ).scalars().all()
    result = []
    for plan in plans:
        allocation = next(
            (
                item
                for item in (plan.current_allocations or plan.baseline_allocations)
                if item["company_id"] == str(company_id) and item.get("role") != "executed"
            ),
            None,
        )
        if allocation is not None:
            result.append(
                PrimaryObligationOut(
                    plan_id=plan.id,
                    need_id=plan.need_id,
                    company_id=company_id,
                    allocation=allocation,
                    plan_status=plan.status,
                    confirmed_at=plan.confirmed_at,
                )
            )
    return result


@router.post(
    "/reserve-commitments/{commitment_id}/decision",
    response_model=ReserveCommitmentOut,
)
async def decide_reserve_commitment(
    commitment_id: uuid.UUID,
    data: ReserveDecisionIn,
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    commitment = (
        await db.execute(
            select(ReserveCommitment)
            .where(ReserveCommitment.id == commitment_id)
        )
    ).scalar_one_or_none()
    if commitment is None or commitment.company_id != data.company_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Приглашение в резерв не найдено")
    await require_company_seller(data.company_id, user, db)
    await require_company_admin(data.company_id, user, db)
    await require_verified_company(data.company_id, user, db)
    await _lock_plan_need(db, commitment.plan_id)
    plan = (
        await db.execute(
            select(ResiliencePlan)
            .where(ResiliencePlan.id == commitment.plan_id)
            .with_for_update()
        )
    ).scalar_one()
    if plan.status == "stale":
        raise HTTPException(409, "Спецификация изменилась. Приглашение в резерв устарело")
    await require_current_evidence(db, await db.get(Need, plan.need_id))
    await db.refresh(commitment, with_for_update=True)
    if "switchover_days" not in data.model_fields_set:
        data.switchover_days = commitment.switchover_days
    await _lock_plan_resources(db, plan)
    if any(row["company_id"] == str(data.company_id) and row.get("role") == "reserve" for row in plan.current_allocations):
        raise HTTPException(409, "Резерв уже исполняет заказ. Используйте сообщение об отказе или отмену остатка сделки")
    if data.decision == "approved" and commitment.confirmation_status == "approved":
        raise HTTPException(409, "Уже подтверждённый резерв нельзя повторно тарифицировать. Согласованные условия сохранены.")
    admission_payload: dict | None = None
    if data.decision == "approved":
        # Резерв — это обязательство: документы компании должны подтверждать
        # спецификацию потребности, для которой удерживается мощность.
        plan_need = await db.get(Need, plan.need_id)
        source_offer = await db.get(Offer, commitment.offer_id) if commitment.offer_id else None
        admission = await require_company_admission(
            db,
            data.company_id,
            SpecificationCheck(
                category=plan_need.category,
                subcategory=plan_need.subcategory,
                characteristics=plan_need.characteristics,
                moq_units=data.moq_units or plan_need.volume_units,
                label="спецификация потребности",
                product_id=source_offer.product_id if source_offer else None,
                volume_units=plan_need.volume_units,category_profile=plan_need.category_profile,
            ),
            context="Резерв не подтверждён",
        )
        admission_payload = admission_audit_payload(
            admission,
            specification={
                "category": plan_need.category, "subcategory": plan_need.subcategory,
                "characteristics": plan_need.characteristics,
                "category_profile": plan_need.category_profile,
                "moq_units": data.moq_units,
            },
        )
        required = {
            "capacity_units": data.capacity_units,
            "moq_units": data.moq_units,
            "unit_price_rub": data.unit_price_rub,
            "delivery_cost_rub": data.delivery_cost_rub,
            "lead_time_days": data.lead_time_days,
            "held_until": data.held_until,
        }
        if any(value is None for value in required.values()):
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Для подтверждения нужны цена, MOQ, мощность, логистика, срок и дата удержания",
            )
        if data.moq_units > data.capacity_units:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail="MOQ превышает мощность")
        if data.held_until < date.today():
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Нельзя подтвердить удержание мощности в прошлом",
            )
        source_offer = await db.get(Offer, commitment.offer_id) if commitment.offer_id else None
        quote = estimate(units=plan_need.volume_units,unit_price=data.unit_price_rub,delivery=data.delivery_cost_rub,
            terms=data.commercial_terms,buyer=plan.buyer_company_id,seller=data.company_id,
            source={'type':'reserve_commitment','id':str(commitment.id),'plan_version':plan.version,
                    'revision':((commitment.commercial_snapshot or {}).get('estimate',{}).get('source',{}).get('revision',0)+1)})
        require_complete(quote)
        if any(line['conditional'] and line['required'] and line['amount_rub'] is None for line in quote['lines']):
            raise HTTPException(409,'Уточните стоимость переключения до подтверждения резерва')
        commitment.commercial_terms = data.commercial_terms.model_dump() if data.commercial_terms else None
        commitment.commercial_snapshot = frozen_snapshot(estimate_value=quote,need=plan_need,offer=source_offer,
            resource={'capacity_units':data.capacity_units,'held_until':str(data.held_until),
                      'switchover_days':data.switchover_days})
        await reserve(db, company_id=data.company_id, anchor_type="reserve", anchor_id=commitment.id,
                      units=data.capacity_units, deadline=plan_need.deadline_date,
                      resource_kind=source_offer.resource_kind if source_offer else "capacity",
                      product_id=source_offer.product_id if source_offer else None,
                      expires_at=datetime.combine(data.held_until, time.max, tzinfo=timezone.utc),
                      category=plan_need.category, subcategory=plan_need.subcategory, unit=order_unit(plan_need.characteristics))
        commitment.reserve_tier = "hot"
        commitment.confirmation_status = "approved"
        commitment.confirmed_capacity_units = data.capacity_units
        commitment.confirmed_moq_units = data.moq_units
        commitment.confirmed_unit_price_rub = data.unit_price_rub
        commitment.confirmed_delivery_cost_rub = data.delivery_cost_rub
        commitment.confirmed_lead_time_days = data.lead_time_days
        commitment.price_tiers = [item.model_dump() for item in data.price_tiers]
        commitment.held_until = data.held_until
        commitment.switchover_days = data.switchover_days
        commitment.confirmed_by_user_id = user.id
        commitment.confirmed_at = datetime.now(timezone.utc)
        event_type = "reserve_confirmed"
    else:
        await release(db, company_id=data.company_id, anchor_type="reserve", anchor_id=commitment.id)
        commitment.confirmation_status = "rejected"
        event_type = "reserve_rejected"
    db.add(
        ResilienceEvent(
            plan_id=plan.id,
            event_type=event_type,
            actor_user_id=user.id,
            actor_company_id=data.company_id,
            payload={"commitment_id": str(commitment.id)},
        )
    )
    await record_human_approval(
        db,
        action="reserve_commitment_decision",
        entity_type="reserve_commitment",
        entity_id=commitment.id,
        actor_user_id=user.id,
        actor_company_id=data.company_id,
        permission="company_admin+seller+verified",
        decision=data.decision,
        payload={
            "plan_id": str(plan.id),
            "capacity_units": data.capacity_units,
            "moq_units": data.moq_units,
            "unit_price_rub": data.unit_price_rub,
            "delivery_cost_rub": data.delivery_cost_rub,
            "lead_time_days": data.lead_time_days,
            "held_until": data.held_until.isoformat() if data.held_until else None,
            "switchover_days": data.switchover_days,
            "admission": admission_payload,
        },
        source_refs=[
            {"type": "resilience_plan", "id": str(plan.id)},
            {"type": "reserve_commitment", "id": str(commitment.id)},
        ],
        explanation="Администратор проверенной компании-производителя явно принял решение по резервной мощности.",
    )
    # A seller may add paid holding after the original buyer approval. That
    # changes the payable bill and requires a new, versioned buyer approval.
    if data.decision == "approved" and plan.confirmed_at is not None:
        accepted = (plan.commercial_snapshot or {}).get('holding_quotes', [])
        fee = sum((decimal(line['amount_rub']) for line in commitment.commercial_snapshot['estimate']['lines']
                   if line['code'] == 'reserve_holding'), decimal(0))
        if fee > 0 and commitment.commercial_snapshot not in accepted:
            plan.confirmed_at = None
            plan.confirmed_by_user_id = None
            plan.version += 1
            plan.status = "ready_for_confirmation"
            all_commitments = list((await db.scalars(select(ReserveCommitment).where(ReserveCommitment.plan_id==plan.id))).all())
            plan.baseline_total_cost_rub = sum((decimal(item['total_cost_rub']) for item in plan.baseline_allocations),decimal(0)) + holding_total(holding_quotes(plan.commercial_snapshot,all_commitments))
            plan.current_total_cost_rub = sum((decimal(item["total_cost_rub"]) for item in plan.current_allocations), decimal(0)) + holding_total(holding_quotes(plan.commercial_snapshot,all_commitments))
            db.add(ResilienceEvent(plan_id=plan.id, event_type="commercial_reapproval_required",
                actor_user_id=user.id, actor_company_id=data.company_id,
                payload={'commitment_id':str(commitment.id),'holding_fee_rub':fee,'version':plan.version}))
    await _calculate_and_store(db, plan, user.id)
    await db.commit()
    await db.refresh(commitment)
    tier, available, reason = await _reserve_availability(db, commitment, await db.get(Need, plan.need_id))
    return ReserveCommitmentOut.model_validate(commitment).model_copy(update={
        "effective_tier": tier, "available_units": available, "availability_reason": reason})


@router.post(
    "/resilience-plans/{plan_id}/simulate-failure",
    response_model=ResilienceScenarioOut,
    status_code=status.HTTP_201_CREATED,
)
async def simulate_failure(
    plan_id: uuid.UUID,
    data: FailureSimulationIn,
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await _lock_plan_need(db, plan_id)
    plan = await db.scalar(select(ResiliencePlan).where(ResiliencePlan.id == plan_id).with_for_update().execution_options(populate_existing=True))
    if plan is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="План устойчивости не найден")
    await require_company_buyer(plan.buyer_company_id, user, db)
    await require_company_admin(plan.buyer_company_id, user, db)
    await require_verified_company(plan.buyer_company_id, user, db)
    if plan.status == "stale":
        raise HTTPException(409, "Спецификация изменилась. Нужен новый ресурсный план")
    primary_ids = {item["company_id"] for item in (plan.current_allocations or plan.baseline_allocations) if item.get("role") != "executed"}
    requested = [str(item) for item in data.failed_company_ids]
    if len(set(requested)) != len(requested) or not set(requested) <= primary_ids:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Симулировать можно отказ одного или двух основных производителей",
        )
    result = await calculate_resilience(await _resilience_payload(db, plan))
    selected = next(
        (item for item in result["scenarios"] if _same_failure_set(item, requested)),
        None,
    )
    if selected is None:
        raise HTTPException(status.HTTP_409_CONFLICT, detail="Сценарий не рассчитан")
    scenario = ResilienceScenario(
        plan_id=plan.id,
        scenario_type="safe_simulation",
        failed_company_ids=requested,
        result=selected,
        input_hash=result["input_hash"],
        status="simulated",
        is_simulation=True,
    )
    db.add(scenario)
    db.add(
        ResilienceEvent(
            plan_id=plan.id,
            event_type="safe_failure_simulated",
            actor_user_id=user.id,
            actor_company_id=plan.buyer_company_id,
            payload={"failed_company_ids": requested, "deal_changed": False},
        )
    )
    await db.commit()
    await db.refresh(scenario)
    return scenario


@router.post("/resilience-plans/{plan_id}/failures", response_model=ResiliencePlanOut)
async def report_producer_failure(
    plan_id: uuid.UUID,
    data: ProducerFailureIn,
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await _lock_plan_need(db, plan_id)
    plan = (
        await db.execute(
            select(ResiliencePlan).where(ResiliencePlan.id == plan_id).with_for_update()
        )
    ).scalar_one_or_none()
    if plan is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="План устойчивости не найден")
    await require_company_seller(data.company_id, user, db)
    await require_company_admin(data.company_id, user, db)
    await require_verified_company(data.company_id, user, db)
    if plan.status == "stale":
        raise HTTPException(409, "Спецификация изменилась. Нужен новый ресурсный план")
    primary_ids = {item["company_id"] for item in (plan.current_allocations or plan.baseline_allocations) if item.get("role") != "executed"}
    if str(data.company_id) not in primary_ids:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            detail="Сообщить отказ может только исполняющий производитель этого плана",
        )
    if plan.confirmed_at is None:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail="Фактический отказ применяется только к подтверждённой конфигурации",
        )
    if str(data.company_id) in plan.failed_company_ids:
        return await _plan_out(db, plan)
    await _lock_plan_resources(db, plan)
    state = await execution_state(db, plan)
    allocation = next(row for row in (plan.current_allocations or plan.baseline_allocations) if row["company_id"] == str(data.company_id))
    remaining = allocation["units"] - protected_units(allocation, state)
    if remaining <= 0:
        raise HTTPException(409, "Весь объём уже отгружен или принят: перенос не требуется")
    if not plan.failure_allocations:
        plan.failure_allocations = deepcopy(plan.current_allocations or plan.baseline_allocations)
    await release(db, company_id=data.company_id,
        anchor_type="deal" if allocation.get("deal_id") else "resilience_primary",
        anchor_id=uuid.UUID(allocation["deal_id"]) if allocation.get("deal_id") else plan.id)
    failed = set(plan.failed_company_ids)
    failed.add(str(data.company_id))
    if len(failed) > 2:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail="Расчёт поддерживает одновременный отказ не более двух производителей",
        )
    plan.failed_company_ids = sorted(failed)
    plan.status = "awaiting_reserve_reconfirmation"
    plan.version += 1
    commitments = (
        await db.execute(
            select(ReserveCommitment).where(
                ReserveCommitment.plan_id == plan.id,
                ReserveCommitment.confirmation_status != "rejected",
            )
        )
    ).scalars().all()
    for commitment in commitments:
        if str(commitment.company_id) in primary_ids:
            continue
        commitment.confirmation_status = "reconfirmation_requested"
        await _notify_company_admins(
            db,
            commitment.company_id,
            "Произошёл сбой основного производителя. Переподтвердите условия резерва.",
            "reserve_reconfirmation",
        )
    db.add(
        ResilienceEvent(
            plan_id=plan.id,
            event_type="producer_failure_reported",
            actor_user_id=user.id,
            actor_company_id=data.company_id,
            payload={
                "reason": data.reason,
                "failed_company_ids": plan.failed_company_ids,
                "only_failed_volume_blocked": True,
                "plan_version": plan.version,
            },
        )
    )
    await _calculate_and_store(db, plan, user.id)
    await _notify_company_admins(db, plan.buyer_company_id,
        "Производитель сообщил о проблеме. Подготовлен пересчёт неотгруженного остатка с резервом.",
        "producer_failure", buyer=True)
    await db.commit()
    return await _plan_out(db, plan)


@router.post(
    "/resilience-scenarios/{scenario_id}/approve",
    response_model=ResiliencePlanOut,
)
async def approve_recovery(
    scenario_id: uuid.UUID,
    data: ResiliencePlanConfirmIn,
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    scenario = await db.get(ResilienceScenario, scenario_id)
    if scenario is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Предложение восстановления не найдено")
    if data.expected_revision is None:
        raise HTTPException(428, "Подтвердите показанную версию конфигурации замены")
    await _lock_plan_need(db, scenario.plan_id)
    plan = await db.scalar(select(ResiliencePlan).where(ResiliencePlan.id == scenario.plan_id).with_for_update().execution_options(populate_existing=True))
    if plan is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="План устойчивости не найден")
    scenario = await db.scalar(select(ResilienceScenario).where(ResilienceScenario.id == scenario.id).with_for_update().execution_options(populate_existing=True))
    if scenario is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Предложение восстановления не найдено")
    await require_company_buyer(plan.buyer_company_id, user, db)
    await require_company_admin(plan.buyer_company_id, user, db)
    await require_verified_company(plan.buyer_company_id, user, db)
    if scenario.status == "activated":
        return await _plan_out(db, plan)
    if scenario.status != "proposed" or set(scenario.failed_company_ids) != set(plan.failed_company_ids):
        raise HTTPException(409, "Предложение восстановления устарело")
    if data.expected_revision != plan.version:
        raise HTTPException(409, "Конфигурация замены изменилась. Обновите её перед подтверждением")
    await require_company_buyer(plan.buyer_company_id, user, db)
    await require_company_admin(plan.buyer_company_id, user, db)
    await require_verified_company(plan.buyer_company_id, user, db)
    if plan.confirmed_at is None:
        raise HTTPException(409, "Сначала согласуйте актуальную полную смету плана")
    await _lock_plan_resources(db, plan)
    result = scenario.result
    if result["uncovered_units"] > 0 or result["unconfirmed_units"] > 0:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail="Нельзя активировать неполную или неподтверждённую замену",
        )
    plan_need = await db.get(Need, plan.need_id)
    await _validate_activation(db, plan, scenario, automatic=False)
    # Замена поставщика — новое обязательство: допуск проверяется для каждой
    # компании, которая получит заказ.
    replacement_admissions: list[dict] = []
    for allocation in result["replacement_allocations"]:
        commitment = await db.scalar(select(ReserveCommitment).where(ReserveCommitment.plan_id == plan.id, ReserveCommitment.company_id == uuid.UUID(str(allocation["company_id"]))))
        source_offer = await db.get(Offer, commitment.offer_id) if commitment and commitment.offer_id else None
        admission = await require_company_admission(
            db,
            uuid.UUID(str(allocation["company_id"])),
            SpecificationCheck(
                category=plan_need.category,
                subcategory=plan_need.subcategory,
                characteristics=plan_need.characteristics,
                moq_units=int(allocation.get("units") or plan_need.volume_units),
                label="поставщик замены",
                product_id=source_offer.product_id if source_offer else None,
                volume_units=int(allocation.get("units") or plan_need.volume_units),
                category_profile=plan_need.category_profile,
            ),
            context="Замена поставщика не активирована",
        )
        replacement_admissions.append(
            {
                "company_id": str(allocation["company_id"]),
                "admission": admission_audit_payload(
                    admission,
                    specification={
                        "category": plan_need.category, "subcategory": plan_need.subcategory,
                        "characteristics": plan_need.characteristics,
                        "category_profile": plan_need.category_profile,
                    },
                ),
            }
        )
    for allocation in sorted(result["replacement_allocations"], key=lambda row: row["company_id"]):
        await lock_company(db, uuid.UUID(allocation["company_id"]))
    await record_human_approval(
        db,
        action="approve_recovery",
        entity_type="resilience_scenario",
        entity_id=scenario.id,
        actor_user_id=user.id,
        actor_company_id=plan.buyer_company_id,
        permission="company_admin+buyer+verified",
        decision="approved",
        payload={
            "plan_id": str(plan.id),
            "new_total_cost_rub": result["new_total_cost_rub"],
            "new_lead_time_days": result["new_lead_time_days"],
            "replacement_allocations": result["replacement_allocations"],
            "admissions": replacement_admissions,
        },
        source_refs=[
            {"type": "resilience_plan", "id": str(plan.id)},
            {"type": "scenario", "id": str(scenario.id)},
        ],
        explanation="Администратор проверенной компании-покупателя явно подтвердил предложенную конфигурацию восстановления.",
    )
    await _activate_scenario(db, plan, scenario, user.id, automatic=False)
    await _notify_recovery(db, plan, scenario)
    await db.commit()
    return await _plan_out(db, plan)


@router.post("/resilience-plans/{plan_id}/recalculate", response_model=ResiliencePlanOut)
async def recalculate_plan(plan_id: uuid.UUID, user: CurrentUser = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    await _lock_plan_need(db, plan_id)
    plan = await db.scalar(select(ResiliencePlan).where(ResiliencePlan.id == plan_id).with_for_update().execution_options(populate_existing=True))
    if plan is None:
        raise HTTPException(404, "План устойчивости не найден")
    await require_company_buyer(plan.buyer_company_id, user, db)
    await require_company_admin(plan.buyer_company_id, user, db)
    await _lock_plan_resources(db, plan)
    await _calculate_and_store(db, plan, user.id)
    await db.commit()
    return await _plan_out(db, plan)
