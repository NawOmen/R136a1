import uuid
from datetime import date, datetime, timezone

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
from ..matching import _need_parts, _passport_matches
from ..models import (
    CapabilityPassport,
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
from ..trust import append_audit_event, record_human_approval

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
        id=plan.id,
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
        reserve_options.append(
            {
                "company_id": str(item.company_id),
                "unit_price_rub": price,
                "moq_units": moq,
                "capacity_units": capacity,
                "lead_time_days": lead,
                "delivery_cost_rub": delivery,
                "reliability": 0.8,
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
        "reserve_options": reserve_options,
        "max_price_increase_pct": plan.max_price_increase_pct,
        "max_delay_days": plan.max_delay_days,
    }


def _same_failure_set(result: dict, company_ids: list[str]) -> bool:
    return set(result["failed_company_ids"]) == set(company_ids)


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
            "buyer_value_rub": round(plan.baseline_total_cost_rub - scenario.result["new_total_cost_rub"], 2),
            "price_delta_rub": scenario.result["price_delta_rub"],
            "delay_days": scenario.result["delay_days"],
        },
    )


async def _calculate_and_store(
    db: AsyncSession, plan: ResiliencePlan, actor_user_id: uuid.UUID | None = None
) -> dict:
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
            try:
                await require_company_admission(
                    db,
                    uuid.UUID(str(allocation["company_id"])),
                    SpecificationCheck(
                        category=plan_need.category,
                        characteristics=plan_need.characteristics,
                        moq_units=int(allocation.get("units") or plan_need.volume_units),
                        label="поставщик замены",
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
    need = await db.get(Need, need_id)
    if need is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Потребность не найдена")
    await require_company_buyer(need.company_id, user, db)
    await require_company_admin(need.company_id, user, db)
    await require_verified_company(need.company_id, user, db)
    existing = (
        await db.execute(select(ResiliencePlan).where(ResiliencePlan.need_id == need.id))
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
            or not _passport_matches(passport, need.category, common)
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
    plan = await db.get(ResiliencePlan, plan_id)
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
            .with_for_update()
        )
    ).scalar_one_or_none()
    if commitment is None or commitment.company_id != data.company_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Приглашение в резерв не найдено")
    await require_company_seller(data.company_id, user, db)
    await require_company_admin(data.company_id, user, db)
    await require_verified_company(data.company_id, user, db)
    plan = (
        await db.execute(
            select(ResiliencePlan)
            .where(ResiliencePlan.id == commitment.plan_id)
            .with_for_update()
        )
    ).scalar_one()
    admission_payload: dict | None = None
    if data.decision == "approved":
        # Резерв — это обязательство: документы компании должны подтверждать
        # спецификацию потребности, для которой удерживается мощность.
        plan_need = await db.get(Need, plan.need_id)
        admission = await require_company_admission(
            db,
            data.company_id,
            SpecificationCheck(
                category=plan_need.category,
                characteristics=plan_need.characteristics,
                moq_units=data.moq_units or plan_need.volume_units,
                label="спецификация потребности",
            ),
            context="Резерв не подтверждён",
        )
        admission_payload = admission_audit_payload(
            admission,
            specification={
                "category": plan_need.category,
                "characteristics": plan_need.characteristics,
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
        commitment.reserve_tier = "hot"
        commitment.confirmation_status = "approved"
        commitment.confirmed_capacity_units = data.capacity_units
        commitment.confirmed_moq_units = data.moq_units
        commitment.confirmed_unit_price_rub = data.unit_price_rub
        commitment.confirmed_delivery_cost_rub = data.delivery_cost_rub
        commitment.confirmed_lead_time_days = data.lead_time_days
        commitment.price_tiers = [item.model_dump() for item in data.price_tiers]
        commitment.held_until = data.held_until
        commitment.confirmed_by_user_id = user.id
        commitment.confirmed_at = datetime.now(timezone.utc)
        event_type = "reserve_confirmed"
    else:
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
            "admission": admission_payload,
        },
        source_refs=[
            {"type": "resilience_plan", "id": str(plan.id)},
            {"type": "reserve_commitment", "id": str(commitment.id)},
        ],
        explanation="Администратор проверенной компании-производителя явно принял решение по резервной мощности.",
    )
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
    plan = await db.get(ResiliencePlan, plan_id)
    if plan is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="План устойчивости не найден")
    await require_company_buyer(plan.buyer_company_id, user, db)
    await require_company_admin(plan.buyer_company_id, user, db)
    await require_verified_company(plan.buyer_company_id, user, db)
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
    failed = set(plan.failed_company_ids)
    failed.add(str(data.company_id))
    if len(failed) > 2:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail="Прототип обрабатывает одновременный отказ не более двух производителей",
        )
    plan.failed_company_ids = sorted(failed)
    plan.status = "awaiting_reserve_reconfirmation"
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
    if scenario is None or scenario.status != "proposed":
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Предложение восстановления не найдено")
    plan = await db.get(ResiliencePlan, scenario.plan_id)
    await require_company_buyer(plan.buyer_company_id, user, db)
    await require_company_admin(plan.buyer_company_id, user, db)
    await require_verified_company(plan.buyer_company_id, user, db)
    result = scenario.result
    if result["uncovered_units"] > 0 or result["unconfirmed_units"] > 0:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail="Нельзя активировать неполную или неподтверждённую замену",
        )
    plan_need = await db.get(Need, plan.need_id)
    # Замена поставщика — новое обязательство: допуск проверяется для каждой
    # компании, которая получит заказ.
    replacement_admissions: list[dict] = []
    for allocation in result["replacement_allocations"]:
        admission = await require_company_admission(
            db,
            uuid.UUID(str(allocation["company_id"])),
            SpecificationCheck(
                category=plan_need.category,
                characteristics=plan_need.characteristics,
                moq_units=int(allocation.get("units") or plan_need.volume_units),
                label="поставщик замены",
            ),
            context="Замена поставщика не активирована",
        )
        replacement_admissions.append(
            {
                "company_id": str(allocation["company_id"]),
                "admission": admission_audit_payload(
                    admission,
                    specification={
                        "category": plan_need.category,
                        "characteristics": plan_need.characteristics,
                    },
                ),
            }
        )
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
    await db.commit()
    return await _plan_out(db, plan)
