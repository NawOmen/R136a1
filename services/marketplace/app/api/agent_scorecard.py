"""Оценка работы ИИ-агентов: конверсия сценариев, правки человека, маршруты модели.

Показатели считаются из журналов и таблиц, а не вписываются вручную. Метрики
модели берутся из журнала вызовов LLM Gateway; если он недоступен, показатели
помечаются как отсутствующие, а не подменяются нулями.
"""

from __future__ import annotations
from ..money import amount

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
    GroupOffer,
    HumanApprovalRecord,
    MarketOpportunity,
    Offer,
    OfferDraft,
    TrustAuditEvent,
)
from ..schemas import AgentScorecardOut, RoleQualityBenchmarkOut, RoleQualityOut, RoleQualityRoleOut

router = APIRouter(tags=["agent-scorecard"])

WINDOW_DAYS_DEFAULT = 30
ROLE_QUALITY_METHOD_VERSION = "role-quality-1"
ROLE_QUALITY_MIN_OBSERVATIONS = 5
ROLE_PASSPORTS = {
    "buyer_agent": "buyer_investigation/buyer (паспорт ролей S04)",
    "seller_agent": "seller (паспорт ролей S04)",
}


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
        "coalesce(avg(duration_ms), 0) AS avg_duration, "
        "coalesce(sum(estimated_cost_rub), 0) AS cost, "
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
    rejected_offers = [item for item in offers if item.status == "rejected"]
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
        average_changed_fields=round(sum(changed_counts) / len(changed_counts), 2) if changed_counts else 0.0,
        offers_total=len(offers),
        offers_from_drafts=len([item for item in offers if item.id in used_offer_ids]),
        offer_rejections=len(rejected_offers),
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
        agent_runs_mixed_route=llm.get("mixed_route", 0),
        agent_runs_rules_route=llm.get("rules_route", 0),
        agent_runs_unknown_route=llm.get("unknown_route", 0),
        agent_costed_runs=llm.get("costed", 0),
        agent_model_versions=sorted(llm.get("models", []) or []),
        agent_prompt_versions=sorted(llm.get("prompts", []) or []),
        agent_average_duration_ms=round(llm.get("avg_duration", 0.0), 1),
        agent_estimated_cost_rub=amount(llm.get("cost", 0)),
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


def _bank_info() -> RoleQualityBenchmarkOut:
    """Эталон методики: банк русскоязычных задач с критичными полями.

    Автоматического сопоставления прогонов с задачами банка в рантайме нет:
    входная сводка прогона не содержит полного текста для надёжного matching,
    поэтому методика опирается на телеметрию, а банк — на периодические
    точечные проверки по docs/analytics/role-quality-method.md.
    """
    import json
    import pathlib

    compares = ["expected_category", "critical_fields"]
    for base in (pathlib.Path.cwd(), pathlib.Path.cwd().parent, pathlib.Path("/app"), pathlib.Path("/repo")):
        bank = base / "packages" / "test-fixtures" / "agent-task-bank" / "ru_tasks.json"
        try:
            tasks = json.loads(bank.read_text(encoding="utf-8"))
            count = len(tasks.get("tasks", tasks)) if isinstance(tasks, dict) else len(tasks)
            return RoleQualityBenchmarkOut(tasks=count, compares=compares, available=True)
        except (OSError, ValueError):
            continue
    return RoleQualityBenchmarkOut(compares=compares, available=False)


async def _runs_available(db: AsyncSession) -> bool:
    available = await db.scalar(text("SELECT to_regclass('agents.agent_runs') IS NOT NULL"))
    if not available:
        return False
    return bool(await db.scalar(text(
        "SELECT EXISTS (SELECT 1 FROM information_schema.columns "
        "WHERE table_schema='agents' AND table_name='agent_runs' AND column_name='company_id')"
    )))


async def role_quality(db: AsyncSession, *, scope: str, company_id: uuid.UUID | None, window_days: int) -> RoleQualityOut:
    since = datetime.now(timezone.utc) - timedelta(days=window_days)
    notes = [
        "Человеко-время напрямую не измеряется: прокси — число подтверждений человека и исправлений; это неполная мера, а не учёт часов.",
        "Кодовые роли (подбор, коалиции, устойчивость) оцениваются конверсиями scorecard и проверками допуска, а не этой методикой: сравниваются только сопоставимые модельные роли.",
        "Нарушение полномочий измеряется счётчиком заблокированных действий журнала; у модельных ролей нет инструментов записи, блокировка — это отклонённый вызов.",
        "Доля успешных сценариев: прогон без сбоя и без ошибки. Итоговый балл не вводится: аспекты не компенсируют друг друга.",
    ]
    if not await _runs_available(db):
        notes.append("Журнал прогонов LLM Gateway недоступен: роли не оценены.")
        return RoleQualityOut(scope=scope, window_days=window_days, method_version=ROLE_QUALITY_METHOD_VERSION,
                              min_observations=ROLE_QUALITY_MIN_OBSERVATIONS, benchmark=_bank_info(), roles=[], notes=notes)
    params: dict = {"since": since, "company_id": company_id}
    if company_id is not None:
        runs_query = text(
            "SELECT id, agent_type, state, error, duration_ms, estimated_cost_rub, model_version, prompt_version, "
            "COALESCE(result, '{}') AS result FROM agents.agent_runs WHERE created_at >= :since "
            "AND company_id = CAST(:company_id AS uuid)")
    else:
        runs_query = text(
            "SELECT id, agent_type, state, error, duration_ms, estimated_cost_rub, model_version, prompt_version, "
            "COALESCE(result, '{}') AS result FROM agents.agent_runs WHERE created_at >= :since")
    rows = (await db.execute(runs_query, params)).mappings().all()
    clarified = set((await db.execute(text(
        "SELECT DISTINCT run_id FROM agents.tool_calls WHERE tool_name = 'apply_user_clarification' AND status = 'success'"
    ))).scalars().all()) if await db.scalar(text("SELECT to_regclass('agents.tool_calls') IS NOT NULL")) else set()
    if company_id is not None:
        blocked_query = text(
            "SELECT COUNT(*) FROM marketplace.trust_audit_events WHERE created_at >= :since "
            "AND actor_company_id = CAST(:company_id AS uuid) "
            "AND (event_type LIKE '%blocked%' OR explanation ILIKE '%заблокировано%')")
    else:
        blocked_query = text(
            "SELECT COUNT(*) FROM marketplace.trust_audit_events WHERE created_at >= :since "
            "AND (event_type LIKE '%blocked%' OR explanation ILIKE '%заблокировано%')")
    blocked = await db.scalar(blocked_query, params) or 0
    corrections = 0
    if company_id is not None:
        corrections = await db.scalar(text(
            "SELECT COALESCE(SUM(jsonb_array_length(changed_fields)), 0) FROM marketplace.offer_drafts "
            "WHERE company_id = CAST(:company_id AS uuid) AND status = 'used' AND created_at >= :since"
        ), params) or 0
    else:
        corrections = await db.scalar(text(
            "SELECT COALESCE(SUM(jsonb_array_length(changed_fields)), 0) FROM marketplace.offer_drafts "
            "WHERE status = 'used' AND created_at >= :since"
        ), params) or 0
    by_role: dict[str, list] = {}
    for row in rows:
        by_role.setdefault(row["agent_type"], []).append(row)
    roles = []
    for agent_type in sorted(by_role):
        sample = by_role[agent_type]
        evaluated = len(sample) >= ROLE_QUALITY_MIN_OBSERVATIONS
        completed = [r for r in sample if r["state"] != "failed" and r["error"] is None]
        props_total = props_confirmed = conflicts = 0
        for r in sample:
            result = r["result"] or {}
            for prop in result.get("properties", []) or []:
                props_total += 1
                if prop.get("status") == "confirmed":
                    props_confirmed += 1
            conflicts += len(result.get("conflicts", []) or [])
        durations = [r["duration_ms"] for r in sample if r["duration_ms"] is not None]
        costs = [float(r["estimated_cost_rub"]) for r in sample if r["estimated_cost_rub"] is not None]
        role = RoleQualityRoleOut(
            role=agent_type, passport=ROLE_PASSPORTS.get(agent_type, "паспорт не описан"),
            sample=len(sample), status="evaluated" if evaluated else "not_evaluated",
            completed_runs=len(completed),
            completed_share_pct=round(len(completed) / len(sample) * 100, 1) if evaluated else None,
            critical_fields_total=props_total, critical_fields_confirmed=props_confirmed,
            critical_completeness_pct=round(props_confirmed / props_total * 100, 1) if evaluated and props_total else None,
            conflicts_found=conflicts,
            clarification_runs=len([r for r in sample if r["id"] in clarified]),
            human_corrections=corrections if agent_type == "seller_agent" else 0,
            blocked_actions=blocked,
            average_duration_ms=round(sum(durations) / len(durations), 1) if evaluated and durations else None,
            known_cost_rub=round(sum(costs), 4) if evaluated and costs else None,
            costed_share_pct=round(len(costs) / len(sample) * 100, 1) if evaluated else None,
            model_versions=sorted({r["model_version"] for r in sample if r["model_version"]}),
            prompt_versions=sorted({r["prompt_version"] for r in sample if r["prompt_version"]}),
        )
        roles.append(role)
    if not roles:
        notes.append("Прогонов за период нет: роли не оценены.")
    elif any(r.status == "not_evaluated" for r in roles):
        notes.append(f"Для оценки нужно не менее {ROLE_QUALITY_MIN_OBSERVATIONS} наблюдений на роль; меньшие выборки — «Не оценено».")
    return RoleQualityOut(scope=scope, window_days=window_days, method_version=ROLE_QUALITY_METHOD_VERSION,
                          min_observations=ROLE_QUALITY_MIN_OBSERVATIONS, benchmark=_bank_info(), roles=roles, notes=notes)


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
