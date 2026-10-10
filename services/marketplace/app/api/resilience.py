from ..commercial import offer_quote, estimate, frozen_snapshot, require_complete, holding_quotes, holding_total
from ..money import amount, decimal
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
from ..resources import reserve, release, activate_hold, lock_company
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
    db: AsyncSession, company_id: uuid.UUID, message: str, type_: str
) -> None:
    rows = await db.execute(
        text(
            "SELECT user_id FROM auth.company_members "
            "WHERE company_id = :cid AND can_sell = true AND is_admin = true"
        ),
        {"cid": company_id},
    )
    for user_id in set(rows.scalars().all()):
        await notify(db, user_id, message, type_)


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
        reserves=[ReserveCommitmentOut.model_validate(item) for item in reserves],
        scenarios=[ResilienceScenarioOut.model_validate(item) for item in scenarios],
        events=[ResilienceEventOut.model_validate(item) for item in events],
    )


def _primary_payload(plan: ResiliencePlan) -> list[dict]:
    return [
        {
            "company_id": item["company_id"],
            "units": item["units"],
            "unit_price_rub": item["unit_price_rub"],
            "additional_cost_rub": item.get("additional_cost_rub",0),
            "delivery_cost_rub": item.get("delivery_cost_rub", 0),
            "lead_time_days": item["lead_time_days"],
        }
        for item in plan.baseline_allocations
    ]


async def _resilience_payload(db: AsyncSession, plan: ResiliencePlan) -> dict:
    commitments = (
        await db.execute(
            select(ReserveCommitment).where(
                ReserveCommitment.plan_id == plan.id,
                ReserveCommitment.confirmation_status != "rejected",
            )
        )
    ).scalars().all()
    reserve_options = []
    holding_cost = holding_total(holding_quotes(plan.commercial_snapshot,commitments))
    for item in commitments:
        approved = item.confirmation_status == "approved"
        capacity = (
            item.confirmed_capacity_units if approved else item.proposed_capacity_units
        )
        moq = item.confirmed_moq_units if approved else item.proposed_moq_units
        price = (
            item.confirmed_unit_price_rub if approved else item.proposed_unit_price_rub
        )
        delivery = (
            item.confirmed_delivery_cost_rub
            if approved
            else item.proposed_delivery_cost_rub
        )
        lead = (
            item.confirmed_lead_time_days if approved else item.proposed_lead_time_days
        )
        if None in {capacity, moq, price, delivery, lead}:
            continue
        quote = item.commercial_snapshot or {}
        if approved:
            require_complete(quote.get('estimate'))
        terms = item.commercial_terms or {}
        if not quote.get('estimate',{}).get('complete'):continue
        expected_basis = plan.baseline_allocations[0].get('comparison_basis')
        if expected_basis and any(terms.get(key)!=value for key,value in expected_basis.items()):
            continue
        additional = sum((decimal(expense['amount_rub']) for expense in terms.get('expenses',[]) if expense['amount_rub'] is not None and expense['code']!='reserve_holding'),decimal(0))
        if any(expense['required'] and expense['amount_rub'] is None for expense in terms.get('expenses',[])):
            continue
        reserve_options.append(
            {
                "company_id": str(item.company_id),
                "unit_price_rub": price,
                "additional_cost_rub": additional,
                "moq_units": moq,
                "capacity_units": capacity,
                "lead_time_days": lead,
                "delivery_cost_rub": delivery,
                "reliability": None,
                "price_tiers": item.price_tiers,
                "serves_region": True,
                "country": "RU",
                "reserve_tier": "hot" if approved else "warm",
                "confirmation_status": item.confirmation_status,
                "held_until": item.held_until.isoformat() if item.held_until else None,
            }
        )
    return {
        "primary_allocations": _primary_payload(plan),
        "reserve_holding_total_rub": holding_cost,
        "reserve_options": reserve_options,
        "max_price_increase_pct": plan.max_price_increase_pct,
        "max_delay_days": plan.max_delay_days,
    }


def _same_failure_set(result: dict, company_ids: list[str]) -> bool:
    return set(result["failed_company_ids"]) == set(company_ids)


async def _lock_plan_need(db, plan_id):
    need_id = await db.scalar(select(ResiliencePlan.need_id).where(ResiliencePlan.id == plan_id))
    if need_id is not None:
        await db.scalar(select(Need).where(Need.id == need_id).with_for_update())


async def _lock_plan_resources(db, plan):
    commitments = list((await db.scalars(select(ReserveCommitment).where(ReserveCommitment.plan_id == plan.id))).all())
    companies = {uuid.UUID(item["company_id"]) for item in plan.baseline_allocations} | {item.company_id for item in commitments}
    for company_id in sorted(companies, key=str):
        await lock_company(db, company_id)


async def _activate_scenario(
    db: AsyncSession,
    plan: ResiliencePlan,
    scenario: ResilienceScenario,
    actor_user_id: uuid.UUID | None,
    automatic: bool,
) -> None:
    failed = set(scenario.result["failed_company_ids"])
    surviving = [
        {**item, "role": "primary"}
        for item in plan.baseline_allocations
        if item["company_id"] not in failed
    ]
    replacements = [
        {**item, "role": "reserve"}
        for item in scenario.result["replacement_allocations"]
    ]
    need = await db.scalar(select(Need).where(Need.id == plan.need_id).with_for_update())
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
    plan.current_allocations = [*surviving, *replacements]
    plan.current_total_cost_rub = scenario.result["new_total_cost_rub"]
    plan.current_lead_time_days = scenario.result["new_lead_time_days"]
    plan.status = "recovered"
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
    if live_result["uncovered_units"] > 0:
        plan.status = "partially_covered"
    elif live_result["unconfirmed_units"] > 0:
        plan.status = "awaiting_reserve_reconfirmation"
    elif (
        plan.auto_replace_within_thresholds
        and live_result["auto_eligible"]
        and plan.confirmed_at is not None
    ):
        # Автоматическая замена — тоже обязательство: без подтверждённых
        # документов решение остаётся человеку, а не выполняется молча.
        plan_need = await db.get(Need, plan.need_id)
        blockers: list[str] = []
        for allocation in live_result["replacement_allocations"]:
            commitment = await db.scalar(select(ReserveCommitment).where(ReserveCommitment.plan_id == plan.id, ReserveCommitment.company_id == uuid.UUID(str(allocation["company_id"]))))
            source_offer = await db.get(Offer, commitment.offer_id) if commitment and commitment.offer_id else None
            try:
                await require_company_admission(
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
                    context="Автоматическая замена не выполнена",
                )
            except HTTPException as error:
                blockers.append(str(error.detail))
        if blockers:
            plan.status = "recovery_proposed"
            db.add(
                ResilienceEvent(
                    plan_id=plan.id,
                    event_type="automatic_replacement_blocked",
                    actor_user_id=actor_user_id,
                    payload={"scenario_id": str(live.id), "reasons": blockers},
                )
            )
            for user_id in (
                await db.execute(
                    text("SELECT user_id FROM auth.company_members WHERE company_id = :cid"),
                    {"cid": plan.buyer_company_id},
                )
            ).scalars().all():
                await notify(
                    db,
                    user_id,
                    "Автоматическая замена поставщика не выполнена: обязательные документы не подтверждены. "
                    f"Требуется ручное решение. {' '.join(blockers)}",
                    "reserve_confirmation_required",
                )
        else:
            await _activate_scenario(db, plan, live, actor_user_id, automatic=True)
            for allocation in live_result["replacement_allocations"]:
                await _notify_company_admins(
                    db,
                    uuid.UUID(str(allocation["company_id"])),
                    "Ваша компания назначена заменой: объём перенесён, проверьте новые условия.",
                    "replacement_activated",
                )
            auto_need = await db.get(Need, plan.need_id)
            if auto_need and auto_need.created_by_user_id:
                await notify(
                    db,
                    auto_need.created_by_user_id,
                    "Автоматическая замена производителя выполнена в пределах порогов.",
                    "replacement_activated",
                )
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
    need = await db.scalar(select(Need).where(Need.id == need_id).with_for_update())
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
    plan = await db.scalar(select(ResiliencePlan).where(ResiliencePlan.id == plan_id).with_for_update())
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
    need = await db.scalar(select(Need).where(Need.id == plan.need_id).with_for_update())
    await require_current_evidence(db, need)
    if (need.status not in ACTIVE_NEED_STATUSES and not (need.status == "matched" and plan.commercial_snapshot)) or need.deadline_date < date.today():
        raise HTTPException(409, "Потребность уже закрыта или срок поставки истёк")
    if sum(item["units"] for item in plan.baseline_allocations) != need.volume_units:
        raise HTTPException(409, "Объём плана не соответствует потребности. Нужен новый расчёт")
    await _lock_plan_resources(db, plan)
    baseline_snapshots = []
    for allocation in sorted(plan.baseline_allocations, key=lambda item: item["company_id"]):
        company_id = uuid.UUID(allocation["company_id"])
        offers = list((await db.scalars(select(Offer).where(Offer.need_id == need.id, Offer.company_id == company_id,
            Offer.status == "sent").with_for_update())).all())
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
        await reserve(db, company_id=company_id, anchor_type="resilience_primary", anchor_id=plan.id,
            units=allocation["units"], deadline=need.deadline_date, resource_kind=offer.resource_kind, product_id=offer.product_id,
            category=need.category, subcategory=need.subcategory, unit=order_unit(need.characteristics))
    commitments = list((await db.scalars(select(ReserveCommitment).where(ReserveCommitment.plan_id==plan.id, ReserveCommitment.confirmation_status=='approved'))).all())
    quotes = holding_quotes(plan.commercial_snapshot,commitments)
    holding = holding_total(quotes)
    plan.baseline_total_cost_rub = sum((decimal(item['total_cost_rub']) for item in plan.baseline_allocations),decimal(0)) + holding
    if need.budget_rub is not None and plan.baseline_total_cost_rub>need.budget_rub:
        raise HTTPException(409,"Полная смета с удержанием резерва превышает бюджет потребности")
    plan.current_total_cost_rub = plan.baseline_total_cost_rub
    plan.commercial_snapshot = {'schema_version':1,'primary':baseline_snapshots,
        'holding_quotes':quotes,
        'reserve_holding_total_rub':str(holding),'total_rub':str(plan.baseline_total_cost_rub)}
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
    return result.scalars().all()


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
                for item in plan.baseline_allocations
                if item["company_id"] == str(company_id)
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
    await _lock_plan_resources(db, plan)
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
            plan.current_total_cost_rub = plan.baseline_total_cost_rub
            db.add(ResilienceEvent(plan_id=plan.id, event_type="commercial_reapproval_required",
                actor_user_id=user.id, actor_company_id=data.company_id,
                payload={'commitment_id':str(commitment.id),'holding_fee_rub':fee,'version':plan.version}))
    await _calculate_and_store(db, plan, user.id)
    await db.commit()
    await db.refresh(commitment)
    return commitment


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
    plan = await db.scalar(select(ResiliencePlan).where(ResiliencePlan.id == plan_id).with_for_update())
    if plan is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="План устойчивости не найден")
    await require_company_buyer(plan.buyer_company_id, user, db)
    await require_company_admin(plan.buyer_company_id, user, db)
    await require_verified_company(plan.buyer_company_id, user, db)
    if plan.status == "stale":
        raise HTTPException(409, "Спецификация изменилась. Нужен новый ресурсный план")
    primary_ids = {item["company_id"] for item in plan.baseline_allocations}
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
    primary_ids = {item["company_id"] for item in plan.baseline_allocations}
    if str(data.company_id) not in primary_ids:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            detail="Сообщить отказ может только основной производитель этого плана",
        )
    if plan.confirmed_at is None:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail="Фактический отказ применяется только к подтверждённой конфигурации",
        )
    if str(data.company_id) in plan.failed_company_ids:
        return await _plan_out(db, plan)
    await _lock_plan_resources(db, plan)
    await release(db, company_id=data.company_id, anchor_type="resilience_primary", anchor_id=plan.id)
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
    need = await db.get(Need, plan.need_id)
    if need and need.created_by_user_id:
        await notify(
            db,
            need.created_by_user_id,
            "Производитель сообщил о проблеме. Подготовлен пересчёт с резервом.",
            "producer_failure",
        )
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
    plan = await db.scalar(select(ResiliencePlan).where(ResiliencePlan.id == scenario.plan_id).with_for_update())
    if plan is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="План устойчивости не найден")
    scenario = await db.scalar(select(ResilienceScenario).where(ResilienceScenario.id == scenario.id).with_for_update())
    if scenario is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Предложение восстановления не найдено")
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
    # Уже принятая продукция не переносится: принятое засчитывается в счёт
    # выпавшего объёма в первую очередь; частичное исполнение требует ручного
    # решения с пересчётом, а не приблизительной математики.
    accepted_by_seller: dict[str, int] = {}
    need_deals = (await db.execute(select(Deal).where(Deal.need_id == plan.need_id))).scalars().all()
    if need_deals:
        accepted_events = (await db.execute(select(DealExecutionEvent).where(
            DealExecutionEvent.deal_id.in_([deal.id for deal in need_deals]),
            DealExecutionEvent.kind == "acceptance",
            DealExecutionEvent.status == "confirmed"))).scalars().all()
        deal_seller = {deal.id: str(deal.seller_company_id) for deal in need_deals}
        for event in accepted_events:
            seller_id = deal_seller.get(event.deal_id)
            if seller_id:
                accepted_by_seller[seller_id] = accepted_by_seller.get(seller_id, 0) + event.units
    for failed_id in scenario.failed_company_ids:
        failed_units = next((item["units"] for item in plan.baseline_allocations
                             if item["company_id"] == failed_id), 0)
        accepted = accepted_by_seller.get(failed_id, 0)
        if accepted >= failed_units and failed_units > 0:
            raise HTTPException(409, "Объём выпавшего производителя уже получен: перенос не требуется")
        if accepted > 0:
            raise HTTPException(
                409,
                f"Часть объёма ({accepted} из {failed_units}) уже принята: "
                "требуется ручное решение с пересчётом замены",
            )
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
    for allocation in result["replacement_allocations"]:
        await _notify_company_admins(
            db,
            uuid.UUID(str(allocation["company_id"])),
            "Ваша компания назначена заменой: объём перенесён, проверьте новые условия.",
            "replacement_activated",
        )
    need = await db.get(Need, plan.need_id)
    if need and need.created_by_user_id:
        await notify(
            db,
            need.created_by_user_id,
            "Замена производителя активирована: проверьте обновлённые цену и срок.",
            "replacement_activated",
        )
    await db.commit()
    return await _plan_out(db, plan)
