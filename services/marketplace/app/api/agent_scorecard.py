"""Оценка работы ИИ-агентов: конверсия сценариев, правки человека, маршруты модели.

Показатели считаются из журналов и таблиц, а не вписываются вручную. Метрики
модели берутся из журнала вызовов LLM Gateway; если он недоступен, показатели
помечаются как отсутствующие, а не подменяются нулями.
"""

from __future__ import annotations
from ..money import decimal

import uuid
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Query
from sqlalchemy import or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_db
from ..deps import (
    CurrentUser,
    get_current_user,
    require_marketplace_admin,
    require_membership,
)
from fastapi import HTTPException, status
from ..models import (
    Deal,
    BusinessDenialEvent,
    ResilienceEvent,
    GroupOffer,
    HumanApprovalRecord,
    MarketOpportunity,
    Offer,
    OfferDraft,
    TrustAuditEvent,
    Need,
)
from ..schemas import AgentScorecardOut, RoleQualityOut

router = APIRouter(tags=["agent-scorecard"])

WINDOW_DAYS_DEFAULT = 30


def _percent(part: int, total: int) -> float | None:
    """Доля в процентах; пустая выборка — «Нет данных», а не ноль."""
    return round(part / total * 100, 1) if total else None


async def _llm_metrics(db: AsyncSession, since: datetime, company_id: uuid.UUID | None = None) -> dict:
    """Never attribute unscoped legacy runs using a user's current memberships."""
    available = await db.scalar(text("SELECT to_regclass('agents.agent_runs') IS NOT NULL"))
    if not available:
        return {"available": False}
    scoped = await db.scalar(text(
        "SELECT EXISTS (SELECT 1 FROM information_schema.columns "
        "WHERE table_schema='agents' AND table_name='agent_runs' AND column_name='company_id')"
    ))
    if not scoped:
        return {"available": False}
    row = (await db.execute(text(
        "SELECT count(*) AS total, "
        "count(*) FILTER (WHERE error IS NOT NULL OR state = 'failed') AS failed, "
        "count(*) FILTER (WHERE used_route IN ('local', 'local_qwen')) AS local_route, "
        "count(*) FILTER (WHERE used_route IN ('external', 'external_deepseek')) AS external_route, "
        "count(*) FILTER (WHERE used_route = 'local_qwen+external_deepseek') AS mixed_route, "
        "count(*) FILTER (WHERE used_route = 'rules_only') AS rules_route, "
        "count(*) FILTER (WHERE used_route IS NULL OR used_route NOT IN "
        "('local', 'local_qwen', 'external', 'external_deepseek', 'local_qwen+external_deepseek', 'rules_only')) AS unknown_route, "
        "count(estimated_cost_rub) AS costed, "
        "avg(duration_ms) AS avg_duration, count(duration_ms) AS timed, "
        "sum(estimated_cost_rub) AS cost, "
        "coalesce(array_agg(DISTINCT model_version) FILTER (WHERE model_version IS NOT NULL), '{}') AS models, "
        "coalesce(array_agg(DISTINCT prompt_version) FILTER (WHERE prompt_version IS NOT NULL), '{}') AS prompts "
        "FROM agents.agent_runs WHERE created_at >= :since "
        "AND (CAST(:company_id AS uuid) IS NULL OR company_id = CAST(:company_id AS uuid))"
    ), {"since": since, "company_id": company_id})).mappings().one()
    return {"available": True, **dict(row)}


async def scorecard(db: AsyncSession, *, scope: str, company_id: uuid.UUID | None, window_days: int) -> AgentScorecardOut:
    since = datetime.now(timezone.utc) - timedelta(days=window_days)
    notes: list[str] = []

    draft_query = select(OfferDraft).where(OfferDraft.created_at >= since)
    offer_query = select(Offer).where(Offer.created_at >= since)
    deal_query = select(Deal).where(Deal.created_at >= since)
    opportunity_query = select(MarketOpportunity).where(MarketOpportunity.created_at >= since)
    approval_query = select(HumanApprovalRecord).where(HumanApprovalRecord.created_at >= since)
    audit_query = select(TrustAuditEvent).where(TrustAuditEvent.created_at >= since)
    if company_id is not None:
        draft_query = draft_query.where(OfferDraft.company_id == company_id)
        offer_query = offer_query.join(Need,Need.id==Offer.need_id).where(or_(Offer.company_id == company_id,Need.company_id == company_id))
        deal_query = deal_query.where(
            or_(Deal.seller_company_id == company_id, Deal.buyer_company_id == company_id)
        )
        opportunity_query = opportunity_query.where(MarketOpportunity.company_id == company_id)
        approval_query = approval_query.where(HumanApprovalRecord.actor_company_id == company_id)
        audit_query = audit_query.where(TrustAuditEvent.actor_company_id == company_id)

    drafts = list((await db.execute(draft_query)).scalars().all())
    all_drafts = drafts
    eligible = []
    from ..models import Product
    for item in drafts:
        if item.status == "used" and item.used_offer_id:
            eligible.append(item)
        elif item.status == "draft" and not (item.missing or []):
            need = await db.get(Need,item.need_id)
            if not need or need.status != 'open_for_offers' or item.payload.get('need_revision') != need.revision:
                continue
            pid = item.payload.get('product_id')
            if pid:
                product = await db.get(Product,uuid.UUID(str(pid)))
                if not product or item.payload.get('source_updated_at') != product.updated_at.isoformat():
                    continue
            eligible.append(item)
    drafts = eligible
    used_drafts = [item for item in drafts if item.status == "used" and item.used_offer_id]
    # Follow outcomes of this draft cohort even when the linked rows were created outside the window.
    origin_ids = {item.used_offer_id for item in used_drafts}
    linked_deals = list((await db.scalars(select(Deal).where(Deal.offer_id.in_(origin_ids)))).all()) if origin_ids else []
    changed_counts = [len(item.changed_fields or []) for item in used_drafts]
    offers = list((await db.execute(offer_query)).scalars().all())
    origin_offers = list((await db.scalars(select(Offer).where(Offer.id.in_(origin_ids)))).all()) if origin_ids else []
    rejected_offers = [item for item in offers if item.status == "rejected"]
    deals = list((await db.execute(deal_query)).scalars().all())
    deals_from_drafts = linked_deals
    opportunities = list((await db.execute(opportunity_query)).scalars().all())
    group_offer_query = select(GroupOffer).where(GroupOffer.opportunity_id.in_(select(MarketOpportunity.id).where(MarketOpportunity.created_at>=since)))
    if company_id is not None: group_offer_query=group_offer_query.where(GroupOffer.company_id==company_id)
    group_offers = list((await db.execute(group_offer_query)).scalars().all())
    approvals = len((await db.execute(approval_query)).scalars().all())
    audit_events = list((await db.execute(audit_query)).scalars().all())
    denial_query = select(BusinessDenialEvent).where(BusinessDenialEvent.created_at >= since)
    resilience_query = select(ResilienceEvent).where(ResilienceEvent.created_at >= since,
        ResilienceEvent.event_type == 'automatic_replacement_blocked')
    if company_id is not None:
        denial_query = denial_query.where(BusinessDenialEvent.company_id == company_id)
        # Resilience evidence is scoped by its plan, not by inferred role.
        from ..models import ResiliencePlan
        resilience_query = resilience_query.join(ResiliencePlan, ResiliencePlan.id == ResilienceEvent.plan_id).join(Need, Need.id == ResiliencePlan.need_id).where(Need.company_id == company_id)
    blocked = list((await db.scalars(denial_query)).all())
    resilience_blocked = list((await db.scalars(resilience_query)).all())
    admission_checks = [item for item in audit_events if item.event_type in {'product_published_with_admission','product_specification_checked'}]
    admission_blocked = [item for item in blocked if item.role == 'supplier_admission']
    notes.append('Блокировки допуска и проверки предложения — типизированные события; повтор одинакового отклонённого запроса не увеличивает счётчик. Старые незаписанные отказы неизвестны.')

    opportunity_ids = {item.id for item in opportunities}
    converted_recommendations = {
        item.opportunity_id for item in group_offers
        if item.opportunity_id in opportunity_ids and item.status != "draft"
    }
    recommendations_total = len(opportunities)
    if recommendations_total == 0 and not group_offers:
        notes.append("Рекомендации производителю пока не формировались: конверсия не рассчитана.")

    llm = await _llm_metrics(db, since, company_id)
    if not llm["available"]:
        notes.append("Журнал вызовов LLM Gateway недоступен: метрики модели не рассчитаны.")
    if llm["available"] and llm["total"] > llm["costed"]:
        notes.append("Стоимость части запусков неизвестна: сумма включает только известные оценки, не полный биллинг.")
    if scope == "company":
        notes.append("Запуски без сохранённой компании не включены в персональную статистику.")
    if not drafts:
        notes.append("Черновики предложений за период не формировались.")
    if used_drafts and max(changed_counts) > 0:
        notes.append("Показатель правок помогает понять, какие поля агент угадывает хуже всего.")

    return AgentScorecardOut(
        scope=scope,
        window_days=window_days,
        offer_drafts_total=len(drafts),
        offer_drafts_used=len(used_drafts),
        offer_draft_conversion_pct=_percent(len(used_drafts), len(drafts)),
        average_changed_fields=round(sum(changed_counts) / len(changed_counts), 2) if changed_counts else None,
        offer_drafts_excluded=len(all_drafts) - len(drafts),
        offer_drafts_open=len(drafts)-len(used_drafts),
        agent_timed_runs=llm.get("timed", 0),
        offers_total=len(offers),
        offers_from_drafts=len(origin_offers),
        offer_rejections=len(rejected_offers),
        deals_total=len(deals),
        deals_from_drafts=len(deals_from_drafts),
        selected_origin_offers=len({d.offer_id for d in linked_deals}),
        open_origin_offers=sum(o.status=='sent' and (o.valid_until is None or o.valid_until>=datetime.now(timezone.utc).date()) for o in origin_offers),
        rejected_origin_offers=sum(o.status=='rejected' for o in origin_offers),
        expired_origin_offers=sum(o.status not in {'selected','rejected'} and (o.status!='sent' or (o.valid_until is not None and o.valid_until<datetime.now(timezone.utc).date())) for o in origin_offers),
        recommendations_total=recommendations_total,
        recommendations_converted=len(converted_recommendations),
        recommendation_conversion_pct=_percent(len(converted_recommendations), recommendations_total),
        human_approvals=approvals,
        blocked_actions=len(blocked)+len(resilience_blocked),
        business_denials_by_role={role:sum(e.role==role for e in blocked) for role in {e.role for e in blocked}},
        resilience_blocked=len(resilience_blocked),
        admission_checks=len(admission_checks),
        admission_blocked=len(admission_blocked),
        agent_runs_total=llm.get("total", 0),
        agent_runs_failed=llm.get("failed", 0),
        agent_runs_local_route=llm.get("local_route", 0),
        agent_runs_external_route=llm.get("external_route", 0),
        agent_runs_mixed_route=llm.get("mixed_route", 0),
        agent_runs_rules_route=llm.get("rules_route", 0),
        agent_runs_unknown_route=llm.get("unknown_route", 0),
        agent_costed_runs=llm.get("costed", 0),
        agent_model_versions=sorted(llm.get("models", []) or []),
        agent_prompt_versions=sorted(llm.get("prompts", []) or []),
        agent_average_duration_ms=round(llm["avg_duration"], 1) if llm.get("avg_duration") is not None else None,
        agent_estimated_cost_rub=decimal(llm["cost"]) if llm.get("cost") is not None else None,
        llm_metrics_available=bool(llm["available"]),
        notes=notes,
    )


@router.get("/companies/{company_id}/agent-scorecard", response_model=AgentScorecardOut)
async def company_agent_scorecard(
    company_id: uuid.UUID,
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    window_days: int = Query(default=WINDOW_DAYS_DEFAULT, ge=1, le=365),
):
    """Оценка агентов для компании: конверсия черновиков, правки человека, блокировки.

    Доступна участнику компании с правом покупки или продажи: в отчёте нет
    чужих денег и себестоимости, только собственная активность компании.
    """
    membership = await require_membership(company_id, user, db)
    if not (membership["can_buy"] or membership["can_sell"]):
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="Нет прав компании для просмотра оценки")
    return await scorecard(db, scope="company", company_id=company_id, window_days=window_days)


@router.get("/platform/agent-scorecard", response_model=AgentScorecardOut)
async def platform_agent_scorecard(
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    window_days: int = Query(default=WINDOW_DAYS_DEFAULT, ge=1, le=365),
):
    """Оценка агентов по площадке: доступна администратору маркетплейса."""
    await require_marketplace_admin(user, db)
    return await scorecard(db, scope="platform", company_id=None, window_days=window_days)


from ..agent_quality import role_quality, bank_info as _bank_info, runs_available as _runs_available


@router.get("/companies/{company_id}/role-quality", response_model=RoleQualityOut)
async def company_role_quality(
    company_id: uuid.UUID,
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    window_days: int = Query(default=WINDOW_DAYS_DEFAULT, ge=1, le=365),
):
    """Обоснованная оценка агентных ролей для компании участника."""
    membership = await require_membership(company_id, user, db)
    if not (membership["can_buy"] or membership["can_sell"]):
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="Нет прав компании для просмотра оценки")
    return await role_quality(db, scope="company", company_id=company_id, window_days=window_days)


@router.get("/platform/role-quality", response_model=RoleQualityOut)
async def platform_role_quality(
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    window_days: int = Query(default=WINDOW_DAYS_DEFAULT, ge=1, le=365),
):
    """Обоснованная оценка агентных ролей по площадке: администратор маркетплейса."""
    await require_marketplace_admin(user, db)
    return await role_quality(db, scope="platform", company_id=None, window_days=window_days)
