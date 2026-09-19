import uuid
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import delete, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from ..admission import SpecificationCheck, require_admission_for_specifications
from ..database import get_db
from ..deps import (
    CurrentUser,
    get_current_user,
    get_membership,
    require_company_admin,
    require_company_buyer,
    require_company_seller,
    require_verified_company,
)
from ..matching import _need_parts, run_market_rematch
from ..models import (
    Coalition,
    CoalitionMember,
    CompatibilityProfile,
    GroupOffer,
    MarketOpportunity,
    Need,
    Offer,
    OptimizationVariantRecord,
    ParticipantOrder,
)
from ..optimizer_client import days_until, evaluate_coalition, optimize_allocations
from ..trust import append_audit_event
from ..schemas import (
    CoalitionDecisionIn,
    CoalitionMemberOut,
    CoalitionOut,
    GroupOfferOut,
    GroupOfferPublishIn,
    MarketOpportunityOut,
    OptimizationVariantOut,
)

router = APIRouter(tags=["stage-5-market"])


async def _user_company_ids(db: AsyncSession, user_id: uuid.UUID) -> set[uuid.UUID]:
    rows = await db.execute(
        text("SELECT company_id FROM auth.company_members WHERE user_id = :uid"),
        {"uid": user_id},
    )
    return set(rows.scalars().all())


def _opportunity_out(item: MarketOpportunity) -> MarketOpportunityOut:
    return MarketOpportunityOut(
        id=item.id,
        company_id=item.company_id,
        category=item.category,
        score=item.score,
        competition_level=item.competition_level,
        saturation_risk=item.saturation_risk,
        unmet_volume_units=item.unmet_volume_units if item.buyers_count >= 2 else None,
        buyers_count=item.buyers_count,
        reasons=item.reasons,
        missing_data=item.missing_data,
        status=item.status,
    )


async def _coalition_out(
    db: AsyncSession, coalition: Coalition, viewer_companies: set[uuid.UUID]
) -> CoalitionOut:
    members = (
        await db.execute(
            select(CoalitionMember).where(CoalitionMember.coalition_id == coalition.id)
        )
    ).scalars().all()
    group_offer = (
        await db.execute(
            select(GroupOffer)
            .where(GroupOffer.coalition_id == coalition.id)
            .order_by(GroupOffer.created_at.desc())
        )
    ).scalars().first()
    visible_members = []
    is_producer = coalition.producer_company_id in viewer_companies
    for member in members:
        own = member.buyer_company_id in viewer_companies
        show_terms = own or is_producer
        visible_members.append(
            CoalitionMemberOut(
                need_id=member.need_id,
                buyer_company_id=member.buyer_company_id if own else None,
                units=member.units,
                individual_operations=member.individual_operations if show_terms else {},
                common_cost_rub=member.common_cost_rub if show_terms else None,
                individual_cost_rub=member.individual_cost_rub if show_terms else None,
                delivery_cost_rub=member.delivery_cost_rub if show_terms else None,
                total_cost_rub=member.total_cost_rub if show_terms else None,
                baseline_cost_rub=member.baseline_cost_rub if show_terms else None,
                benefit_rub=member.benefit_rub if show_terms else None,
                approval_status=member.approval_status if show_terms else "скрыто",
            )
        )
    return CoalitionOut(
        id=coalition.id,
        producer_company_id=coalition.producer_company_id,
        category=coalition.category,
        combined_volume_units=coalition.combined_volume_units,
        target_moq_units=coalition.target_moq_units,
        status=coalition.status,
        version=coalition.version,
        explanation=coalition.explanation,
        members=visible_members,
        group_offer=GroupOfferOut.model_validate(group_offer) if group_offer else None,
    )


@router.post("/market/rematch", status_code=status.HTTP_202_ACCEPTED)
async def rematch_market(
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await run_market_rematch(db, "manual_rematch", None, {"requested_by": str(user.id)})
    await db.commit()
    return {"status": "processed"}


@router.get("/companies/{company_id}/market-opportunities", response_model=list[MarketOpportunityOut])
async def list_market_opportunities(
    company_id: uuid.UUID,
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await require_company_seller(company_id, user, db)
    await run_market_rematch(db, "opportunity_feed_opened", company_id)
    await db.commit()
    result = await db.execute(
        select(MarketOpportunity)
        .where(
            MarketOpportunity.company_id == company_id,
            MarketOpportunity.status == "active",
        )
        .order_by(MarketOpportunity.score.desc(), MarketOpportunity.category)
    )
    return [_opportunity_out(item) for item in result.scalars().all()]


@router.post("/opportunities/{opportunity_id}/prepare-offer", response_model=GroupOfferOut, status_code=201)
async def prepare_group_offer(
    opportunity_id: uuid.UUID,
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    opportunity = await db.get(MarketOpportunity, opportunity_id)
    if opportunity is None or opportunity.status != "active":
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Рыночная возможность не найдена")
    await require_company_seller(opportunity.company_id, user, db)
    await require_company_admin(opportunity.company_id, user, db)
    coalition = (
        await db.execute(
            select(Coalition).where(
                Coalition.producer_company_id == opportunity.company_id,
                Coalition.category == opportunity.category,
                Coalition.status.in_(("candidate", "recalculation_required")),
            )
        )
    ).scalars().first()
    if coalition is None:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail="Для этой возможности пока нет совместимой группы потребностей",
        )
    existing = (
        await db.execute(
            select(GroupOffer).where(
                GroupOffer.coalition_id == coalition.id,
                GroupOffer.company_id == opportunity.company_id,
                GroupOffer.status == "draft",
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        return existing
    draft = GroupOffer(
        coalition_id=coalition.id,
        company_id=opportunity.company_id,
        opportunity_id=opportunity.id,
        min_total_units=coalition.target_moq_units,
        max_total_units=coalition.combined_volume_units,
        price_tiers=[],
        status="draft",
        seller_approval_status="pending",
        created_by_user_id=user.id,
    )
    db.add(draft)
    await db.commit()
    await db.refresh(draft)
    return draft


@router.post("/group-offers/{group_offer_id}/publish", response_model=CoalitionOut)
async def publish_group_offer(
    group_offer_id: uuid.UUID,
    data: GroupOfferPublishIn,
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    group_offer = await db.get(GroupOffer, group_offer_id)
    if group_offer is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Черновик группового предложения не найден")
    await require_company_seller(group_offer.company_id, user, db)
    await require_company_admin(group_offer.company_id, user, db)
    await require_verified_company(group_offer.company_id, user, db)
    if group_offer.status != "draft":
        raise HTTPException(status.HTTP_409_CONFLICT, detail="Опубликовать можно только черновик")
    if (
        data.min_total_units > data.max_total_units
        or data.min_total_units > data.available_capacity_units
    ):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="MOQ не может превышать максимум партии или подтверждённую мощность",
        )
    if (
        data.fill_deadline < date.today()
        or data.production_end < data.production_start
        or data.fill_deadline >= data.production_start
    ):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Срок набора должен завершаться до корректного производственного окна",
        )
    coalition = await db.get(Coalition, group_offer.coalition_id)
    profile = await db.get(CompatibilityProfile, coalition.compatibility_profile_id)
    members = (
        await db.execute(
            select(CoalitionMember).where(CoalitionMember.coalition_id == coalition.id)
        )
    ).scalars().all()
    # Обязательство производителя по группе: документы проверяются по спецификации
    # каждой потребности, потому что участники заказывают разные изделия.
    member_needs = {member.need_id: await db.get(Need, member.need_id) for member in members}
    await require_admission_for_specifications(
        db,
        group_offer.company_id,
        [
            SpecificationCheck(
                category=need.category,
                characteristics=need.characteristics,
                moq_units=need.volume_units,
                label=f"потребность {need.id}",
            )
            for need in member_needs.values()
        ],
        context="Групповое предложение не опубликовано",
    )
    terms = {item.need_id: item for item in data.participant_terms}
    if set(terms) != {item.need_id for item in members}:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Условия должны быть заданы отдельно для каждого участника",
        )
    company_country = (
        await db.execute(text("SELECT country FROM auth.companies WHERE id = :id"), {"id": group_offer.company_id})
    ).scalar_one()
    payload_members = []
    for member in members:
        need = await db.get(Need, member.need_id)
        term = terms[member.need_id]
        payload_members.append(
            {
                "need_id": str(need.id),
                "buyer_company_id": str(need.company_id),
                "volume_units": need.volume_units,
                "common_base": profile.common_base,
                "individual_operations": member.individual_operations,
                "hard_constraints": profile.hard_constraints,
                "flexible_parameters": profile.flexible_parameters.get(str(need.id), {}),
                "individual_operations_cost_rub": term.individual_operations_cost_rub,
                "delivery_cost_rub": term.delivery_cost_rub,
                "budget_rub": need.budget_rub,
                "individual_baseline_cost_rub": term.individual_baseline_cost_rub,
                "deadline_days": days_until(need.deadline_date),
                "delivery_days": term.delivery_days,
            }
        )
    # Срок участника считается от текущего дня до завершения производства,
    # а не только как длительность самого производственного окна.
    production_days = (data.production_end - date.today()).days + 1
    result = await evaluate_coalition(
        {
            "producer_company_id": str(group_offer.company_id),
            "producer_country": company_country,
            "min_total_units": data.min_total_units,
            "max_total_units": data.max_total_units,
            "available_capacity_units": data.available_capacity_units,
            "production_days": production_days,
            "price_tiers": [item.model_dump() for item in data.price_tiers],
            "members": payload_members,
        }
    )
    if not result["feasible"]:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail="; ".join(result["reasons"]),
        )
    result_members = {uuid.UUID(item["need_id"]): item for item in result["members"]}
    for member in members:
        calculated = result_members[member.need_id]
        member.common_cost_rub = calculated["common_production_cost_rub"]
        member.individual_cost_rub = calculated["individual_operations_cost_rub"]
        member.delivery_cost_rub = calculated["delivery_cost_rub"]
        member.total_cost_rub = calculated["total_cost_rub"]
        member.baseline_cost_rub = calculated["baseline_cost_rub"]
        member.benefit_rub = calculated["benefit_rub"]
        member.approval_status = "pending"
        need = await db.get(Need, member.need_id)
        need.status = "awaiting_approvals"
        need.no_match_reason = None
    group_offer.min_total_units = data.min_total_units
    group_offer.max_total_units = data.max_total_units
    group_offer.price_tiers = [item.model_dump() for item in data.price_tiers]
    group_offer.production_start = data.production_start
    group_offer.production_end = data.production_end
    group_offer.fill_deadline = data.fill_deadline
    group_offer.non_fill_rule = data.non_fill_rule
    group_offer.status = "preliminary"
    group_offer.seller_approval_status = "approved"
    coalition.status = "awaiting_approvals"
    coalition.explanation = result["reasons"]
    await run_market_rematch(db, "group_offer_published", group_offer.id)
    await db.commit()
    return await _coalition_out(db, coalition, await _user_company_ids(db, user.id))


@router.get("/coalitions/mine", response_model=list[CoalitionOut])
async def list_my_coalitions(
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    company_ids = await _user_company_ids(db, user.id)
    if not company_ids:
        return []
    member_coalitions = select(CoalitionMember.coalition_id).where(
        CoalitionMember.buyer_company_id.in_(company_ids)
    )
    coalitions = (
        await db.execute(
            select(Coalition)
            .where(
                or_(
                    Coalition.producer_company_id.in_(company_ids),
                    Coalition.id.in_(member_coalitions),
                )
            )
            .order_by(Coalition.updated_at.desc())
        )
    ).scalars().all()
    today = date.today()
    for coalition in coalitions:
        group_offer = (
            await db.execute(
                select(GroupOffer)
                .where(GroupOffer.coalition_id == coalition.id)
                .order_by(GroupOffer.created_at.desc())
            )
        ).scalars().first()
        if (
            group_offer
            and group_offer.fill_deadline
            and group_offer.fill_deadline < today
            and coalition.status not in {"confirmed", "cancelled", "expired"}
        ):
            group_offer.status = "expired"
            coalition.status = "expired"
            members = (
                await db.execute(select(CoalitionMember).where(CoalitionMember.coalition_id == coalition.id))
            ).scalars().all()
            for member in members:
                need = await db.get(Need, member.need_id)
                need.status = "waiting_for_match"
                need.no_match_reason = "Срок набора группы истёк; обязательства не созданы"
    await db.commit()
    return [await _coalition_out(db, item, company_ids) for item in coalitions]


@router.post("/coalitions/{coalition_id}/decision", response_model=CoalitionOut)
async def decide_coalition(
    coalition_id: uuid.UUID,
    data: CoalitionDecisionIn,
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    coalition = (
        await db.execute(select(Coalition).where(Coalition.id == coalition_id).with_for_update())
    ).scalar_one_or_none()
    if coalition is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Коалиция не найдена")
    group_offer = (
        await db.execute(
            select(GroupOffer)
            .where(GroupOffer.coalition_id == coalition.id)
            .order_by(GroupOffer.created_at.desc())
        )
    ).scalars().first()
    if group_offer is None or group_offer.status != "preliminary":
        raise HTTPException(status.HTTP_409_CONFLICT, detail="Нет предварительных условий для подтверждения")
    member = (
        await db.execute(
            select(CoalitionMember).where(
                CoalitionMember.coalition_id == coalition.id,
                CoalitionMember.buyer_company_id == data.company_id,
            )
        )
    ).scalar_one_or_none()
    if member is None:
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="Компания не является участником коалиции")
    await require_company_buyer(data.company_id, user, db)
    await require_company_admin(data.company_id, user, db)
    await require_verified_company(data.company_id, user, db)
    member.approval_status = data.decision
    members = (
        await db.execute(select(CoalitionMember).where(CoalitionMember.coalition_id == coalition.id))
    ).scalars().all()
    if data.decision == "rejected":
        coalition.status = "recalculation_required"
        coalition.version += 1
        group_offer.status = "recalculation_required"
        for other in members:
            if other.id != member.id:
                other.approval_status = "pending"
            need = await db.get(Need, other.need_id)
            need.status = "waiting_for_match"
            need.no_match_reason = (
                "Один из участников отказался от групповых условий; "
                "обязательства не созданы, выполняется повторный подбор"
            )
        await db.execute(delete(ParticipantOrder).where(ParticipantOrder.coalition_id == coalition.id))
        await run_market_rematch(db, "coalition_member_rejected", coalition.id, {"need_id": str(member.need_id)})
    elif all(item.approval_status == "approved" for item in members):
        if group_offer.seller_approval_status != "approved":
            raise HTTPException(status.HTTP_409_CONFLICT, detail="Производитель ещё не подтвердил условия")
        # Обязательства создаются сейчас: допуск производителя проверяется заново,
        # потому что документ мог истечь или быть отозван после публикации условий.
        member_needs = {item.need_id: await db.get(Need, item.need_id) for item in members}
        await require_admission_for_specifications(
            db,
            coalition.producer_company_id,
            [
                SpecificationCheck(
                    category=need.category,
                    characteristics=need.characteristics,
                    moq_units=need.volume_units,
                    label=f"потребность {need.id}",
                )
                for need in member_needs.values()
            ],
            context="Групповые обязательства не созданы",
        )
        await append_audit_event(
            db,
            event_type="coalition_obligations_checked",
            entity_type="coalition",
            entity_id=coalition.id,
            actor_user_id=user.id,
            actor_company_id=data.company_id,
            source_refs=[{"type": "coalition", "id": str(coalition.id)}],
            explanation="Перед созданием групповых обязательств допуск производителя проверен повторно.",
            payload={
                "version": coalition.version,
                "category": coalition.category,
                "needs": [str(item.need_id) for item in members],
            },
        )
        for item in members:
            db.add(
                ParticipantOrder(
                    coalition_id=coalition.id,
                    group_offer_id=group_offer.id,
                    need_id=item.need_id,
                    buyer_company_id=item.buyer_company_id,
                    seller_company_id=group_offer.company_id,
                    units=item.units,
                    total_price_rub=item.total_cost_rub,
                    status="created",
                )
            )
            need = await db.get(Need, item.need_id)
            need.status = "matched"
            need.no_match_reason = None
        coalition.status = "confirmed"
        group_offer.status = "confirmed"
    await db.commit()
    return await _coalition_out(db, coalition, await _user_company_ids(db, user.id))


@router.post("/needs/{need_id}/optimize", response_model=list[OptimizationVariantOut])
async def optimize_need(
    need_id: uuid.UUID,
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    need = await db.get(Need, need_id)
    if need is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Потребность не найдена")
    await require_company_buyer(need.company_id, user, db)
    offers = (
        await db.execute(
            select(Offer).where(
                Offer.need_id == need.id,
                Offer.status == "sent",
                or_(Offer.valid_until.is_(None), Offer.valid_until >= date.today()),
            )
        )
    ).scalars().all()
    if not offers:
        raise HTTPException(status.HTTP_409_CONFLICT, detail="Для оптимизации пока нет предложений")
    producers = []
    for offer in offers:
        country = (
            await db.execute(text("SELECT country FROM auth.companies WHERE id = :id"), {"id": offer.company_id})
        ).scalar_one_or_none()
        producers.append(
            {
                "company_id": str(offer.company_id),
                "unit_price_rub": offer.price_rub,
                "moq_units": offer.moq_units,
                "capacity_units": offer.available_units,
                "lead_time_days": offer.lead_time_days,
                "delivery_cost_rub": offer.delivery_cost_rub,
                "reliability": 0.8,
                "price_tiers": offer.price_tiers,
                "serves_region": True,
                "country": country or "RU",
            }
        )
    result = await optimize_allocations(
        {
            "demand_units": need.volume_units,
            "budget_rub": need.budget_rub,
            "deadline_days": days_until(need.deadline_date),
            "producers": producers,
        }
    )
    records = []
    for variant in result["variants"]:
        existing = (
            await db.execute(
                select(OptimizationVariantRecord).where(
                    OptimizationVariantRecord.need_id == need.id,
                    OptimizationVariantRecord.kind == variant["kind"],
                    OptimizationVariantRecord.input_hash == result["input_hash"],
                )
            )
        ).scalar_one_or_none()
        if existing is None:
            existing = OptimizationVariantRecord(
                need_id=need.id,
                kind=variant["kind"],
                result=variant,
                input_hash=result["input_hash"],
            )
            db.add(existing)
            await db.flush()
        records.append(existing)
    await db.commit()
    return records
