"""Оценка работы ИИ-агентов: конверсия сценариев, правки человека, маршруты модели.

Показатели считаются из журналов и таблиц, а не вписываются вручную. Метрики
модели берутся из журнала вызовов LLM Gateway; если он недоступен, показатели
помечаются как отсутствующие, а не подменяются нулями.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Query
from sqlalchemy import or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_db
from ..deps import (
    CurrentUser,
    get_current_user,
    require_company_seller,
    require_marketplace_admin,
)
from ..models import (
    Deal,
    GroupOffer,
    HumanApprovalRecord,
    MarketOpportunity,
    Offer,
    OfferDraft,
    TrustAuditEvent,
)
from ..schemas import AgentScorecardOut

router = APIRouter(tags=["agent-scorecard"])

WINDOW_DAYS_DEFAULT = 30


def _percent(part: int, total: int) -> float:
    return round(part / total * 100, 1) if total else 0.0


async def _llm_metrics(db: AsyncSession, since: datetime) -> dict:
    """Метрики вызовов агентов из журнала LLM Gateway, если он доступен."""
    available = await db.scalar(text("SELECT to_regclass('agents.agent_runs') IS NOT NULL"))
    if not available:
        return {"available": False}
    row = (
        await db.execute(
            text(
                "SELECT count(*) AS total, "
                "count(*) FILTER (WHERE error IS NOT NULL OR state = 'failed') AS failed, "
                "count(*) FILTER (WHERE used_route = 'local') AS local_route, "
                "count(*) FILTER (WHERE used_route IS NOT NULL AND used_route <> 'local') AS external_route, "
                "coalesce(avg(duration_ms), 0) AS avg_duration, "
                "coalesce(sum(estimated_cost_rub), 0) AS cost "
                "FROM agents.agent_runs WHERE created_at >= :since"
            ),
            {"since": since},
        )
    ).mappings().one()
    return {
        "available": True,
        "total": int(row["total"] or 0),
        "failed": int(row["failed"] or 0),
        "local_route": int(row["local_route"] or 0),
        "external_route": int(row["external_route"] or 0),
        "avg_duration": float(row["avg_duration"] or 0),
        "cost": float(row["cost"] or 0),
    }


async def scorecard(db: AsyncSession, *, scope: str, company_id: uuid.UUID | None, window_days: int) -> AgentScorecardOut:
    since = datetime.now(timezone.utc) - timedelta(days=window_days)
    notes: list[str] = []

    draft_query = select(OfferDraft).where(OfferDraft.created_at >= since)
    offer_query = select(Offer).where(Offer.created_at >= since)
    deal_query = select(Deal).where(Deal.created_at >= since)
    opportunity_query = select(MarketOpportunity)
    approval_query = select(HumanApprovalRecord).where(HumanApprovalRecord.created_at >= since)
    audit_query = select(TrustAuditEvent).where(TrustAuditEvent.created_at >= since)
    group_offer_query = select(GroupOffer).where(GroupOffer.created_at >= since)
    if company_id is not None:
        draft_query = draft_query.where(OfferDraft.company_id == company_id)
        offer_query = offer_query.where(Offer.company_id == company_id)
        deal_query = deal_query.where(
            or_(Deal.seller_company_id == company_id, Deal.buyer_company_id == company_id)
        )
        opportunity_query = opportunity_query.where(MarketOpportunity.company_id == company_id)
        approval_query = approval_query.where(HumanApprovalRecord.actor_company_id == company_id)
        audit_query = audit_query.where(TrustAuditEvent.actor_company_id == company_id)
        group_offer_query = group_offer_query.where(GroupOffer.company_id == company_id)

    drafts = list((await db.execute(draft_query)).scalars().all())
    used_drafts = [item for item in drafts if item.status == "used"]
    changed_counts = [len(item.changed_fields or []) for item in used_drafts]
    offers = list((await db.execute(offer_query)).scalars().all())
    used_offer_ids = {item.used_offer_id for item in used_drafts if item.used_offer_id}
    deals = list((await db.execute(deal_query)).scalars().all())
    deals_from_drafts = [item for item in deals if item.offer_id in used_offer_ids]
    opportunities = list((await db.execute(opportunity_query)).scalars().all())
    group_offers = list((await db.execute(group_offer_query)).scalars().all())
    approvals = len((await db.execute(approval_query)).scalars().all())
    audit_events = list((await db.execute(audit_query)).scalars().all())
    blocked = [
        item
        for item in audit_events
        if "blocked" in item.event_type or "blocked" in (item.explanation or "").lower()
    ]
    admission_checks = [
        item
        for item in audit_events
        if item.event_type in {"product_published_with_admission", "offer_draft_generated"}
        or item.event_type.startswith("document_")
    ]
    admission_blocked = [item for item in blocked if "admission" in item.event_type or "допуск" in (item.explanation or "").lower()]

    converted_recommendations = {item.coalition_id for item in group_offers if item.coalition_id}
    recommendations_total = len(opportunities)
    if recommendations_total == 0 and not group_offers:
        notes.append("Рекомендации производителю пока не формировались: конверсия не рассчитана.")

    llm = await _llm_metrics(db, since)
    if not llm["available"]:
        notes.append("Журнал вызовов LLM Gateway недоступен: метрики модели не рассчитаны.")
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
        average_changed_fields=round(sum(changed_counts) / len(changed_counts), 2) if changed_counts else 0.0,
        offers_total=len(offers),
        offers_from_drafts=len([item for item in offers if item.id in used_offer_ids]),
        deals_total=len(deals),
        deals_from_drafts=len(deals_from_drafts),
        recommendations_total=recommendations_total,
        recommendations_converted=len(converted_recommendations),
        recommendation_conversion_pct=_percent(len(converted_recommendations), recommendations_total),
        human_approvals=approvals,
        blocked_actions=len(blocked),
        admission_checks=len(admission_checks),
        admission_blocked=len(admission_blocked),
        agent_runs_total=llm.get("total", 0),
        agent_runs_failed=llm.get("failed", 0),
        agent_runs_local_route=llm.get("local_route", 0),
        agent_runs_external_route=llm.get("external_route", 0),
        agent_average_duration_ms=round(llm.get("avg_duration", 0.0), 1),
        agent_estimated_cost_rub=round(llm.get("cost", 0.0), 2),
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
    """Оценка агентов для компании: конверсия черновиков, правки человека, блокировки."""
    await require_company_seller(company_id, user, db)
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
