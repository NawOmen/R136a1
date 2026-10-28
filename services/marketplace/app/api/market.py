from ..commercial import estimate, distribute, require_complete, baseline_comparable, group_snapshot, offer_quote
from ..money import decimal
import uuid
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import delete, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from ..admission import SpecificationCheck, admission_audit_payload, require_admission_for_specifications
from ..database import get_db
from ..deps import (
    CurrentUser,
    get_current_user,
    get_membership,
    require_company_admin,
    require_company_buyer,
    require_company_seller,
    require_verified_seller,
)
from ..matching import ACTIVE_NEED_STATUSES, _need_parts, need_is_current, order_unit, run_market_rematch
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
from ..resources import reserve, release
from ..trust import append_audit_event, payload_hash, record_human_approval
from ..schemas import (
    CoalitionDecisionIn,
    CoalitionMemberOut,
    CoalitionOut,
    GroupOfferOut,
    GroupOfferPublishIn,
    MarketOpportunityOut,
    OptimizationVariantOut,
    OpportunityDismissIn,
)

from ..requirements import require_current_evidence

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
        unit=item.unit,
        score=item.score,
        competition_level=item.competition_level,
        saturation_risk=item.saturation_risk,
        unmet_volume_units=item.unmet_volume_units if item.buyers_count >= 2 else None,
        buyers_count=item.buyers_count,
        reasons=item.reasons,
        missing_data=item.missing_data,
        status=item.status,
        dismissal_reason=item.dismissal_reason,
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
    profile = await db.get(CompatibilityProfile, coalition.compatibility_profile_id)
    unit = str((profile.common_base or {}).get("unit") or "шт") if profile else "шт"
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
                commercial_estimate=({**(member.commercial_estimate or {}), **({} if own else {'baseline_cost_rub':None,'baseline_offer_id':None,'benefit_rub':None,'baseline_comparable':False,'baseline_snapshot':None})} if show_terms and member.commercial_estimate else None),
                individual_operations=member.individual_operations if show_terms else {},
                common_cost_rub=member.common_cost_rub if show_terms else None,
                individual_cost_rub=member.individual_cost_rub if show_terms else None,
                delivery_cost_rub=member.delivery_cost_rub if show_terms else None,
                total_cost_rub=member.total_cost_rub if show_terms else None,
                baseline_cost_rub=member.baseline_cost_rub if own else None,
                benefit_rub=member.benefit_rub if own else None,
                approval_status=member.approval_status if show_terms else "скрыто",
            )
        )
    return CoalitionOut(
        id=coalition.id,
        producer_company_id=coalition.producer_company_id,
        category=coalition.category,
        unit=unit,
        combined_volume_units=coalition.combined_volume_units,
        confirmed_volume_units=sum(item.units for item in members if item.approval_status == "approved"),
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


@router.post("/opportunities/{opportunity_id}/dismiss", response_model=MarketOpportunityOut)
async def dismiss_opportunity(
    opportunity_id: uuid.UUID,
    data: OpportunityDismissIn,
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Продавец отклоняет рекомендацию с причиной: она пропадает из ленты,
    пока состав спроса не изменится."""
    opportunity = await db.get(MarketOpportunity, opportunity_id)
    if opportunity is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Рыночная возможность не найдена")
    await require_company_seller(opportunity.company_id, user, db)
    opportunity.status = "dismissed"
    opportunity.dismissal_reason = data.reason.strip()
    await db.commit()
    await db.refresh(opportunity)
    return _opportunity_out(opportunity)


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
    await require_verified_seller(group_offer.company_id, user, db)
    # Match the consent path: needs, coalition, then resource locks. Refresh
    # identity-map objects after waiting, before checking statuses or volumes.
    member_needs = await _lock_coalition_needs(db, group_offer.coalition_id)
    coalition = await db.scalar(select(Coalition).where(Coalition.id == group_offer.coalition_id)
                                .with_for_update().execution_options(populate_existing=True))
    await db.refresh(group_offer, with_for_update=True)
    if coalition is None or coalition.status not in {"candidate", "recalculation_required"}:
        raise HTTPException(409, "Состав или спецификация группы изменились. Подготовьте новое предложение")
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
    profile = await db.get(CompatibilityProfile, coalition.compatibility_profile_id)
    members = (
        await db.execute(
            select(CoalitionMember).where(CoalitionMember.coalition_id == coalition.id)
            .order_by(CoalitionMember.id).with_for_update().execution_options(populate_existing=True)
        )
    ).scalars().all()
    # S08.01/08.02: производство обязано уложиться в окно до раннего дедлайна,
    # а объёмы — в кратность партии.
    earliest_deadline = min(need.deadline_date for need in member_needs.values())
    if data.production_end > earliest_deadline:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Производство выходит за ранний дедлайн участника. Сократите окно или обновите подбор",
        )
    total_units = sum(item.units for item in members)
    if total_units % data.lot_multiple != 0 or any(
        member.units % data.lot_multiple != 0 for member in members
    ):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Объём группы и каждого участника должен быть кратен партии",
        )
    # Обязательство производителя по группе: документы проверяются по спецификации
    # каждой потребности, потому что участники заказывают разные изделия.
    if not member_needs or any(
        need is None or need.status not in ACTIVE_NEED_STATUSES or not need_is_current(need)
        for need in member_needs.values()
    ):
        raise HTTPException(409, "Потребность участника закрыта или её срок истёк. Обновите подбор группы")
    if any(member.need_id not in member_needs or member.units != member_needs[member.need_id].volume_units
           for member in members):
        raise HTTPException(409, "Количество участника изменилось. Обновите подбор группы")
    for need in member_needs.values():
        await require_current_evidence(db, need)
    await require_admission_for_specifications(
        db,
        group_offer.company_id,
        [
            SpecificationCheck(
                category=need.category,
                subcategory=need.subcategory,
                characteristics=need.characteristics,
                category_profile=need.category_profile,
                moq_units=need.volume_units,
                volume_units=sum(item.units for item in members),
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
    shared = distribute(data.shared_cost_rub,{member.need_id:member.units for member in members})
    eligible_tiers = [tier for tier in data.price_tiers if tier.min_units<=sum(item.units for item in members)]
    if not eligible_tiers:raise HTTPException(422,'Нет ценовой ступени для общего объёма')
    batch_price = sorted(eligible_tiers,key=lambda tier:tier.min_units)[-1].unit_price_rub
    goods_parts = distribute(sum(item.units for item in members)*batch_price,{member.need_id:member.units for member in members})
    estimates = {}
    payload_members = []
    for member in members:
        need = await db.get(Need, member.need_id)
        term = terms[member.need_id]
        tiers = sorted(data.price_tiers,key=lambda tier:tier.min_units)
        applicable = [tier for tier in tiers if tier.min_units <= sum(item.units for item in members)]
        if not applicable:raise HTTPException(422,'Нет ценовой ступени для общего объёма')
        value = estimate(units=need.volume_units,unit_price=applicable[-1].unit_price_rub,
            delivery=term.delivery_cost_rub,terms={**(term.commercial_terms.model_dump() if term.commercial_terms else {}),'expenses':[(expense.model_dump()) for expense in (term.commercial_terms.expenses if term.commercial_terms else [])]+[{'code':'individual_operations','title':'Индивидуальные операции','amount_rub':term.individual_operations_cost_rub,'source':'Условия участника','version':str(coalition.version+1)}]},buyer=need.company_id,seller=group_offer.company_id,
            source={'type':'group_offer','id':str(group_offer.id),'revision':coalition.version+1},shared=shared[member.need_id],goods_override=goods_parts[member.need_id])
        require_complete(value)
        value['need_revision'] = need.revision
        baseline = await db.get(Offer,term.baseline_offer_id) if term.baseline_offer_id else None
        if baseline and (baseline.company_id!=group_offer.company_id or baseline.need_id!=need.id or baseline.status not in {'sent','selected'}):
            raise HTTPException(422,'Индивидуальное КП не относится к потребности участника')
        value['baseline_offer_id'] = str(baseline.id) if baseline else None
        value['baseline_snapshot'] = baseline.commercial_quote if baseline else None
        value['baseline_cost_rub'] = baseline.commercial_quote['estimate']['total_rub'] if baseline and baseline_comparable(baseline.commercial_quote,need,value) else None
        value['baseline_comparable'] = value['baseline_cost_rub'] is not None
        value['benefit_rub'] = str(decimal(value['baseline_cost_rub'])-decimal(value['total_rub'])) if value['baseline_comparable'] else None
        estimates[member.need_id] = value
        payload_members.append(
            {
                "need_id": str(need.id),
                "buyer_company_id": str(need.company_id),
                "volume_units": need.volume_units,
                "common_base": profile.common_base,
                "individual_operations": member.individual_operations,
                "hard_constraints": profile.hard_constraints,
                "flexible_parameters": profile.flexible_parameters.get(str(need.id), {}),
                "individual_operations_cost_rub": decimal(value["total_rub"])-decimal(value["lines"][0]["amount_rub"])-decimal(value["lines"][2]["amount_rub"]),
                "delivery_cost_rub": value["lines"][2]["amount_rub"],
                "budget_rub": need.budget_rub,
                "individual_baseline_cost_rub": value["baseline_cost_rub"],
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
        member.individual_cost_rub = terms[member.need_id].individual_operations_cost_rub
        member.delivery_cost_rub = calculated["delivery_cost_rub"]
        member.total_cost_rub = calculated["total_cost_rub"]
        member.baseline_cost_rub = calculated["baseline_cost_rub"]
        member.benefit_rub = calculated["benefit_rub"]
        member.approval_status = "pending"
        need = await db.get(Need, member.need_id)
        need.status = "awaiting_approvals"
        need.no_match_reason = None
    for member in members:
        member.commercial_estimate = estimates[member.need_id]
        member.common_cost_rub = decimal(member.commercial_estimate['lines'][0]['amount_rub'])
        member.total_cost_rub = decimal(member.commercial_estimate['total_rub'])
        member.baseline_cost_rub = decimal(member.commercial_estimate['baseline_cost_rub']) if member.commercial_estimate['baseline_cost_rub'] is not None else None
        member.benefit_rub = decimal(member.commercial_estimate['benefit_rub']) if member.commercial_estimate['benefit_rub'] is not None else None
        need = member_needs[member.need_id]
        if need.budget_rub is not None and member.total_cost_rub>need.budget_rub:
            raise HTTPException(409,'Полная смета превышает бюджет участника')
    group_offer.min_total_units = data.min_total_units
    group_offer.max_total_units = data.max_total_units
    group_offer.lot_multiple = data.lot_multiple
    group_offer.price_tiers = [item.model_dump() for item in data.price_tiers]
    group_offer.production_start = data.production_start
    group_offer.production_end = data.production_end
    group_offer.fill_deadline = data.fill_deadline
    group_offer.non_fill_rule = data.non_fill_rule
    group_offer.status = "preliminary"
    group_offer.seller_approval_status = "approved"
    coalition.status = "awaiting_approvals"
    coalition.version += 1
    coalition.explanation = result["reasons"]
    await record_human_approval(
        db,
        action="seller_group_offer_published",
        entity_type="group_offer",
        entity_id=group_offer.id,
        actor_user_id=user.id,
        actor_company_id=group_offer.company_id,
        permission="company_admin+seller+verified",
        decision="approved",
        payload={
            "coalition_id": str(coalition.id),
            "coalition_version": coalition.version,
            "min_total_units": data.min_total_units,
            "max_total_units": data.max_total_units,
            "available_capacity_units": data.available_capacity_units,
            "price_tiers": [item.model_dump(mode="json") for item in data.price_tiers],
            "production_start": str(data.production_start),
            "production_end": str(data.production_end),
            "fill_deadline": str(data.fill_deadline),
            "non_fill_rule": data.non_fill_rule,
            "participant_terms": [item.model_dump(mode="json") for item in data.participant_terms],
            "shared_cost_rub": str(data.shared_cost_rub) if data.shared_cost_rub is not None else None,
        },
        source_refs=[
            {"type": "coalition", "id": str(coalition.id)},
            {"type": "group_offer", "id": str(group_offer.id)},
        ],
        explanation="Производитель явно подтвердил опубликованную версию групповых условий.",
    )
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


async def _lock_coalition_needs(db, coalition_id):
    ids = select(CoalitionMember.need_id).where(CoalitionMember.coalition_id == coalition_id)
    needs = (await db.scalars(select(Need).where(Need.id.in_(ids)).order_by(Need.id).with_for_update()
                              .execution_options(populate_existing=True))).all()
    return {need.id: need for need in needs}


@router.post("/coalitions/{coalition_id}/decision", response_model=CoalitionOut)
async def decide_coalition(
    coalition_id: uuid.UUID,
    data: CoalitionDecisionIn,
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await _lock_coalition_needs(db, coalition_id)
    coalition = (
        await db.execute(select(Coalition).where(Coalition.id == coalition_id).with_for_update()
                         .execution_options(populate_existing=True))
    ).scalar_one_or_none()
    if coalition is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Коалиция не найдена")
    member = (
        await db.execute(
            select(CoalitionMember).where(
                CoalitionMember.coalition_id == coalition.id,
                CoalitionMember.buyer_company_id == data.company_id,
            )
            .execution_options(populate_existing=True)
        )
    ).scalar_one_or_none()
    if member is None:
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="Компания не является участником коалиции")
    await require_company_buyer(data.company_id, user, db)
    await require_company_admin(data.company_id, user, db)
    decision_hash = payload_hash({"decision": data.decision,
                                  "expected_revision": data.expected_revision}) if data.request_key else None
    # A committed decision survives the state/TTL changes it caused. Recheck
    # access before replaying it, and never apply the saved request a second time.
    if data.request_key is not None and member.decision_request_key == data.request_key:
        if member.decision_request_hash != decision_hash:
            raise HTTPException(409, "Ключ запроса уже использован для других условий")
        return await _coalition_out(db, coalition, await _user_company_ids(db, user.id))
    if coalition.version != data.expected_revision:
        raise HTTPException(status.HTTP_409_CONFLICT, detail="Условия группы изменились. Обновите страницу и проверьте их заново")
    if coalition.status != "awaiting_approvals":
        raise HTTPException(status.HTTP_409_CONFLICT, detail="Подтверждение для этой группы сейчас недоступно")
    group_offer = (
        await db.execute(
            select(GroupOffer)
            .where(GroupOffer.coalition_id == coalition.id)
            .order_by(GroupOffer.created_at.desc())
            .execution_options(populate_existing=True)
        )
    ).scalars().first()
    if group_offer is None or group_offer.status != "preliminary":
        raise HTTPException(status.HTTP_409_CONFLICT, detail="Нет предварительных условий для подтверждения")
    if group_offer.fill_deadline is None or group_offer.fill_deadline < date.today():
        raise HTTPException(status.HTTP_409_CONFLICT, detail="Срок подтверждения групповых условий истёк")
    if member.approval_status != "pending":
        raise HTTPException(status.HTTP_409_CONFLICT, detail="Решение этой компании уже принято")
    if data.decision == "approved":
        require_complete(member.commercial_estimate)
        if member.commercial_estimate.get('baseline_offer_id'):
            baseline = await db.get(Offer,uuid.UUID(member.commercial_estimate['baseline_offer_id']))
            saved = member.commercial_estimate.get('baseline_snapshot') or {}
            need = await db.get(Need,member.need_id)
            if (baseline is None or baseline.status not in {'sent','selected'} or baseline.revision != saved.get('offer',{}).get('revision')
                or not baseline_comparable(saved,need,member.commercial_estimate)):
                raise HTTPException(409,'КП для сравнения устарело. Выберите актуальное КП или продолжите без базы экономии')
    member.approval_status = data.decision
    member.decision_request_key = data.request_key
    member.decision_request_hash = decision_hash
    await record_human_approval(
        db,
        action="coalition_member_decision",
        entity_type="coalition",
        entity_id=coalition.id,
        actor_user_id=user.id,
        actor_company_id=data.company_id,
        permission="company_admin+buyer",
        decision=data.decision,
        payload={
            "coalition_id": str(coalition.id),
            "coalition_version": coalition.version,
            "need_id": str(member.need_id),
            "units": member.units,
            "total_cost_rub": str(member.total_cost_rub) if getattr(member, "total_cost_rub", None) is not None else None,
            "commercial_estimate": member.commercial_estimate,
            "request_key": str(data.request_key) if data.request_key else None,
        },
        source_refs=[
            {"type": "coalition", "id": str(coalition.id)},
            {"type": "need", "id": str(member.need_id)},
        ],
        explanation="Участник коалиции явно принял решение только по собственным условиям.",
    )
    members = (
        await db.execute(select(CoalitionMember).where(CoalitionMember.coalition_id == coalition.id)
                         .order_by(CoalitionMember.id).with_for_update().execution_options(populate_existing=True))
    ).scalars().all()
    if data.decision == "approved":
        member_needs = {item.need_id: await db.get(Need, item.need_id) for item in members}
        if not member_needs or any(
            need is None or need.status not in ACTIVE_NEED_STATUSES or not need_is_current(need)
            for need in member_needs.values()
        ):
            raise HTTPException(409, "Потребность участника закрыта или её срок истёк. Обновите подбор группы")
        if any(item.units != member_needs[item.need_id].volume_units or
               (item.commercial_estimate or {}).get('need_revision', 1) != member_needs[item.need_id].revision
               for item in members):
            raise HTTPException(409, "Спецификация участника изменилась. Требуются новые условия группы")
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
        # Проверка продавца повторяется перед созданием обязательств.
        # Для покупателей верификация компании не требуется.
        producer = (await db.execute(
            text("SELECT verification_status FROM auth.companies WHERE id = :id"),
            {"id": coalition.producer_company_id},
        )).scalar_one_or_none()
        if producer != "verified":
            raise HTTPException(status.HTTP_409_CONFLICT,
                                detail="Допуск производителя отозван. Обязательства не созданы")
        buyer_rows = (await db.execute(text(
            "SELECT c.id FROM auth.companies c WHERE c.id = ANY(:ids) AND c.country = 'RU' "
            "AND EXISTS (SELECT 1 FROM auth.company_members m WHERE m.company_id=c.id AND m.can_buy=true)"
        ), {"ids": [item.buyer_company_id for item in members]})).all()
        buyers = {row[0] for row in buyer_rows}
        if any(item.buyer_company_id not in buyers for item in members):
            raise HTTPException(409, "Компания участника недоступна для закупок. Обязательства не созданы")
        for current_need in member_needs.values():
            await require_current_evidence(db, current_need)
        # Обязательства создаются сейчас: допуск производителя проверяется заново,
        # потому что документ мог истечь или быть отозван после публикации условий.
        admissions = await require_admission_for_specifications(
            db,
            coalition.producer_company_id,
            [
                SpecificationCheck(
                    category=need.category,
                    subcategory=need.subcategory,
                    characteristics=need.characteristics,
                    category_profile=need.category_profile,
                    moq_units=need.volume_units,
                    volume_units=sum(item.units for item in members),
                    label=f"потребность {need.id}",
                )
                for need in member_needs.values()
            ],
            context="Групповые обязательства не созданы",
        )
        admissions_by_need = dict(zip(member_needs, admissions, strict=True))
        participant_snapshots = []
        for item in members:
            need = member_needs[item.need_id]
            require_complete(item.commercial_estimate)
            participant_snapshots.append({
                "need_id": str(need.id),
                "need_revision": need.revision,
                "buyer_company_id": str(item.buyer_company_id),
                "seller_company_id": str(coalition.producer_company_id),
                "units": item.units,
                "total_price_rub": item.total_cost_rub,
                "admission": admission_audit_payload(admissions_by_need[need.id], specification={
                    "category": need.category, "subcategory": need.subcategory,
                    "characteristics": need.characteristics, "category_profile": need.category_profile,
                    "moq_units": need.volume_units,
                }),
            })
        await reserve(db, company_id=group_offer.company_id, anchor_type="coalition", anchor_id=coalition.id,
                      units=sum(item.units for item in members), start=group_offer.production_start,
                      deadline=group_offer.production_end, category=coalition.category,
                      subcategory=next(iter(member_needs.values())).subcategory,
                      unit=order_unit(next(iter(member_needs.values())).characteristics))
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
                "participants": participant_snapshots,
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
                    coalition_version=coalition.version,
                    commercial_snapshot=await group_snapshot(db,item.commercial_estimate,member_needs[item.need_id],resource={'group_offer_id':str(group_offer.id),'coalition_version':coalition.version,'price_tiers':group_offer.price_tiers,'production_start':str(group_offer.production_start),'production_end':str(group_offer.production_end),'fill_deadline':str(group_offer.fill_deadline)}),
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
    need = await db.scalar(select(Need).where(Need.id == need_id).with_for_update())
    if need is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Потребность не найдена")
    await require_company_buyer(need.company_id, user, db)
    await require_current_evidence(db, need)
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
    quote_groups = {}
    for offer in offers:
        country = (
            await db.execute(text("SELECT country FROM auth.companies WHERE id = :id"), {"id": offer.company_id})
        ).scalar_one_or_none()
        quote = offer.commercial_quote or {}
        value = quote.get('estimate',{})
        if not value.get('complete') or quote['need']['revision']!=need.revision:
            continue
        terms = value['terms']
        key = (terms['tax_basis'],terms['vat_rate_pct'],terms['delivery_method'],terms['delivery_conditions'])
        extra = sum((decimal(line['amount_rub']) for line in value['lines'] if line['code'] not in {'goods','delivery'} and not line['conditional']),decimal(0))
        option = {
                "company_id": str(offer.company_id),
                "unit_price_rub": offer.price_rub,
                "additional_cost_rub": extra,
                "moq_units": offer.moq_units,
                "capacity_units": offer.available_units,
                "lead_time_days": offer.lead_time_days,
                "delivery_cost_rub": value["lines"][2]["amount_rub"],
                "reliability": None,
                "price_tiers": offer.price_tiers,
                "serves_region": True,
                "country": country or "",
            }
        group = quote_groups.setdefault(key,{})
        previous = group.get(str(offer.company_id))
        if previous is None or decimal(value['total_rub']) < decimal(previous[1].commercial_quote['estimate']['total_rub']):
            group[str(offer.company_id)] = (option,offer)
    if not quote_groups:
        raise HTTPException(409,'Нет КП с подтверждённой полной сметой, доставкой и налоговой базой')
    records = []
    results = []
    for key,group in sorted(quote_groups.items(),key=lambda item:str(item[0])):
        sources = {company_id:pair[1] for company_id,pair in group.items()}
        calculated = await optimize_allocations({'demand_units':need.volume_units,'budget_rub':need.budget_rub,
            'deadline_days':days_until(need.deadline_date),'producers':[pair[0] for pair in group.values()],
            'comparison_context':{'need_id':str(need.id),'need_revision':need.revision,'basis':key,
                                  'offer_versions':sorted((str(pair[1].id),pair[1].revision) for pair in group.values())}})
        for variant in calculated['variants']:
            variant['comparison_basis'] = {'tax_basis':key[0],'vat_rate_pct':key[1],'delivery_method':key[2],'delivery_conditions':key[3]}
            variant['reasons'].append('Сравнение внутри одинаковой налоговой базы и условий получения; разные базы не ранжируются вместе')
            for allocation in variant.get('allocations',[]):
                source = sources[allocation['company_id']]
                allocation['offer_id'] = str(source.id)
                allocation['offer_revision'] = source.revision
                allocation['comparison_basis'] = variant['comparison_basis']
                allocation['commercial_snapshot'] = await offer_quote(db,source,need,units=allocation['units'])
        results.append(calculated)
    for result in results:
        for variant in result["variants"]:
            existing = (await db.execute(select(OptimizationVariantRecord).where(
                OptimizationVariantRecord.need_id==need.id, OptimizationVariantRecord.kind==variant['kind'],
                OptimizationVariantRecord.input_hash==result['input_hash'],
                OptimizationVariantRecord.result['stale'].as_boolean().is_not(True)))).scalar_one_or_none()
            if existing is None:
                existing = OptimizationVariantRecord(need_id=need.id,kind=variant['kind'],result=variant,input_hash=result['input_hash'])
                db.add(existing)
            records.append(existing)
    await db.commit()
    return [OptimizationVariantOut.model_validate(record) for record in records]


from pydantic import BaseModel
class BaselineSelectionIn(BaseModel):
    company_id: uuid.UUID
    offer_id: uuid.UUID | None
    expected_revision: int


@router.post('/coalitions/{coalition_id}/baseline',response_model=CoalitionOut)
async def choose_individual_baseline(coalition_id:uuid.UUID,data:BaselineSelectionIn,
                                     user:CurrentUser=Depends(get_current_user),db:AsyncSession=Depends(get_db)):
    await _lock_coalition_needs(db, coalition_id)
    coalition = await db.scalar(select(Coalition).where(Coalition.id==coalition_id).with_for_update())
    if coalition is None:raise HTTPException(404,'Коалиция не найдена')
    await require_company_buyer(data.company_id,user,db)
    if coalition.version!=data.expected_revision:raise HTTPException(409,'Условия группы изменились')
    member = await db.scalar(select(CoalitionMember).where(CoalitionMember.coalition_id==coalition.id,
                                                         CoalitionMember.buyer_company_id==data.company_id))
    if member is None:raise HTTPException(403,'Компания не участвует в этой коалиции')
    if member.approval_status!='pending' or coalition.status!='awaiting_approvals':
        raise HTTPException(409,'Альтернативу можно выбрать до подтверждения собственных условий')
    need = await db.get(Need,member.need_id)
    offer = await db.get(Offer,data.offer_id) if data.offer_id else None
    if data.offer_id:
        if offer is None or offer.need_id!=need.id or offer.status not in {'sent','selected'} or (offer.valid_until and offer.valid_until<date.today()):
            raise HTTPException(422,'Нужен действующий подтверждённый КП этой потребности')
        if not baseline_comparable(offer.commercial_quote,need,member.commercial_estimate):
            raise HTTPException(422,'КП не сопоставимо по версии требований, объёму, сроку, адресу, доставке или налоговой базе')
    value = {**member.commercial_estimate,'baseline_offer_id':str(offer.id) if offer else None,
             'baseline_snapshot':offer.commercial_quote if offer else None,
             'baseline_cost_rub':offer.commercial_quote['estimate']['total_rub'] if offer else None,'baseline_comparable':offer is not None}
    value['benefit_rub'] = str(decimal(value['baseline_cost_rub'])-decimal(value['total_rub'])) if offer else None
    member.commercial_estimate = value
    member.baseline_cost_rub = decimal(value['baseline_cost_rub']) if offer else None
    member.benefit_rub = decimal(value['benefit_rub']) if offer else None
    await append_audit_event(db,event_type='individual_baseline_selected',entity_type='coalition',entity_id=coalition.id,
        actor_user_id=user.id,actor_company_id=data.company_id,
        payload={'need_id':str(need.id),'offer_id':str(offer.id) if offer else None,'offer_revision':offer.revision if offer else None,'estimate':value},
        explanation='Покупатель выбрал своё сопоставимое подтверждённое КП; найденные и каталожные цены не являются базой экономии')
    await db.commit()
    return await _coalition_out(db,coalition,await _user_company_ids(db,user.id))
