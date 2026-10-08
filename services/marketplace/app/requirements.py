"""One specification revision boundary; existing obligations stay immutable."""
import copy
import hashlib
import json
from datetime import datetime, timezone

from fastapi import HTTPException
from sqlalchemy import select, text

from .models import (Need, NeedRevision, Offer, OfferDraft, Deal, Coalition, CoalitionMember,
    GroupOffer, ParticipantOrder, OptimizationVariantRecord, ResiliencePlan, ReserveCommitment,
    ResourceReservation)
from .trust import append_audit_event, record_human_approval
from .category_units import order_unit
from .resources import lock_company

SPEC_FIELDS = ("category", "subcategory", "characteristics", "volume_units", "budget_rub",
               "deadline_date", "valid_until", "delivery_address_id")


def specification(need):
    return {key: getattr(need, key) for key in SPEC_FIELDS}


def canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, default=str, separators=(",", ":"))


async def evidence_snapshot(db, data, user, *, lock=True):
    now = datetime.now(timezone.utc).isoformat()
    values = {**data.characteristics, "quantity_units": data.volume_units, "budget_rub": data.budget_rub,
              "deadline_date": data.deadline_date.isoformat(), "category": data.category,
              "subcategory": data.subcategory, "delivery_address_id": str(data.delivery_address_id or "")}
    fields = {key: {"value": str(value) if not isinstance(value, (str, int, bool, list, dict, type(None))) else value,
        "original_value": str(value), "original_unit": order_unit(data.characteristics) if key == "quantity_units" else ("руб" if key == "budget_rub" else None),
        "normalized_unit": order_unit(data.characteristics) if key == "quantity_units" else ("руб" if key == "budget_rub" else None), "status": "confirmed", "origin": "manual",
        "confirmed_by_user_id": str(user.id), "confirmed_at": now, "sources": []}
        for key, value in values.items()}
    physical = data._physical_quantity_input
    if physical:
        fields["quantity_units"].update(original_value=physical["value"], original_unit=physical["unit"])
    snapshot = {"version": "need-evidence-1", "fields": fields, "run": None, "resolved_conflicts": []}
    if data.agent_run_id is None:
        if data.agent_run_revision is not None:
            raise HTTPException(422, "Для версии анализа укажите агентный процесс")
        return snapshot
    # Services already share PostgreSQL (capability search/scorecard); this is a
    # read of the Gateway's authoritative confirmation, never client assertions.
    row = (await db.execute(text("SELECT id,revision,state,result,user_id,company_id FROM agents.agent_runs WHERE id=:id" +
        (" FOR UPDATE" if lock else "")), {"id": data.agent_run_id})).mappings().first()
    if row is None or row["user_id"] != user.id or row["company_id"] != data.company_id:
        raise HTTPException(403, "Анализ не принадлежит покупателю выбранной компании")
    if row["revision"] != data.agent_run_revision or row["state"] != "confirmed_by_user":
        raise HTTPException(409, "Требования анализа изменились или не подтверждены. Проверьте актуальную версию")
    result = row["result"]
    if result.get("conflicts") or result.get("questions") or not result.get("can_confirm"):
        raise HTTPException(409, "Сначала разрешите конфликты требований")
    for prop in result.get("properties", []):
        key = prop["key"]
        if prop.get("status") == "needs_clarification":
            raise HTTPException(409, "Есть неподтверждённые требования")
        if key not in fields:
            continue
        observed = prop.get("value")
        # Forms render scalar facts as text; lists are displayed with commas.
        comparable = ", ".join(map(str, observed)) if isinstance(observed, list) else str(observed)
        if comparable.strip().casefold() == str(fields[key]["value"]).strip().casefold():
            fields[key] = {**fields[key], "origin": "agent", "extraction_status": prop.get("status"),
                           "sources": prop.get("sources", [])}
        else:
            fields[key]["previous_evidence"] = prop
            fields[key]["origin"] = "manual_override"
    snapshot["run"] = {"id": str(row["id"]), "revision": row["revision"]}
    snapshot["resolved_conflicts"] = result.get("resolved_conflicts", [])
    return snapshot


async def evidence_is_current(db, need, *, lock=False):
    run = (getattr(need, "requirements_evidence", None) or {}).get("run")
    if not run:
        return True
    row = (await db.execute(text("SELECT revision,state FROM agents.agent_runs WHERE id=:id" + (" FOR UPDATE" if lock else "")),
        {"id": run["id"]})).first()
    return bool(row and row[0] == run["revision"] and row[1] == "confirmed_by_user")


async def require_current_evidence(db, need):
    if not await evidence_is_current(db, need, lock=True):
        raise HTTPException(409, "Источник требований изменён или удалён. Покупателю нужно подтвердить новую версию спецификации")


async def revision_impact(db, need, data):
    new = data.model_dump(mode="python", include=set(SPEC_FIELDS))
    new["valid_until"] = data.valid_until or data.deadline_date
    changes = {key: {"before": getattr(need, key), "after": new[key]} for key in SPEC_FIELDS
               if (getattr(need, key) != new[key] if key == "budget_rub" else canonical(getattr(need, key)) != canonical(new[key]))}
    old_run = (getattr(need, "requirements_evidence", None) or {}).get("run")
    new_run = {"id": str(data.agent_run_id), "revision": data.agent_run_revision} if data.agent_run_id else None
    # An omitted binding preserves the current evidence for a label-only edit.
    if data.agent_run_id and canonical(old_run) != canonical(new_run):
        changes["evidence"] = {"before": old_run, "after": new_run}
    if not await evidence_is_current(db, need):
        changes["evidence"] = {"before": old_run, "after": new_run, "reason": "source_stale"}
    offers = list((await db.scalars(select(Offer).where(Offer.need_id == need.id, Offer.status.in_(["sent", "draft"])))).all())
    drafts = list((await db.scalars(select(OfferDraft).where(OfferDraft.need_id == need.id, OfferDraft.status == "draft"))).all())
    coalition_ids = list((await db.scalars(select(CoalitionMember.coalition_id).where(CoalitionMember.need_id == need.id))).all())
    coalitions = list((await db.scalars(select(Coalition).where(Coalition.id.in_(coalition_ids), Coalition.status.not_in(["cancelled", "expired"])))).all())
    plans = list((await db.scalars(select(ResiliencePlan).where(ResiliencePlan.need_id == need.id, ResiliencePlan.status != "stale"))).all())
    variants = list((await db.scalars(select(OptimizationVariantRecord).where(OptimizationVariantRecord.need_id == need.id))).all())
    committed = bool(await db.scalar(select(Deal.id).where(Deal.need_id == need.id).limit(1)) or
                     await db.scalar(select(ParticipantOrder.id).where(ParticipantOrder.need_id == need.id).limit(1)) or
                     any(plan.confirmed_at is not None for plan in plans))
    affected = {"offers": [str(item.id) for item in sorted(offers, key=lambda item: str(item.id))], "offer_drafts": [str(item.id) for item in sorted(drafts, key=lambda item: str(item.id))],
        "coalitions": [str(item.id) for item in sorted(coalitions, key=lambda item: str(item.id))], "resource_plans": [str(item.id) for item in sorted(plans, key=lambda item: str(item.id))],
        "optimization_variants": [str(item.id) for item in sorted(variants, key=lambda item: str(item.id))]}
    payload = {"expected_revision": need.revision, "changes": changes, "affected": affected,
               "dependency_versions": {"offers": {str(row.id): row.revision for row in offers},
                   "coalitions": {str(row.id): row.version for row in coalitions},
                   "plans": {str(row.id): row.version for row in plans}},
               "editable": not committed, "requires_confirmation": bool(changes and need.status != "draft")}
    payload = json.loads(canonical(payload))
    payload["impact_hash"] = hashlib.sha256(canonical(payload).encode()).hexdigest()
    return payload, (offers, drafts, coalitions, plans, variants)


async def invalidate_dependents(db, need, dependents, user, impact):
    offers, drafts, coalitions, plans, variants = dependents
    recipients = {need.company_id}
    reserve_ids = select(ReserveCommitment.id).where(ReserveCommitment.plan_id.in_([row.id for row in plans]))
    affected_rows = list((await db.scalars(select(ResourceReservation).where(
        ((ResourceReservation.anchor_type == "coalition") & ResourceReservation.anchor_id.in_([row.id for row in coalitions])) |
        ((ResourceReservation.anchor_type == "reserve") & ResourceReservation.anchor_id.in_(reserve_ids))
    ))).all())
    # Acquire the whole resource set in one stable order, including cross-group reservations.
    for company_id in sorted({row.company_id for row in affected_rows}, key=str):
        await lock_company(db, company_id)
    for offer in offers:
        offer.status = "stale"
        recipients.add(offer.company_id)
    for draft in drafts:
        draft.status = "stale"
        recipients.add(draft.company_id)
    for coalition in sorted(coalitions, key=lambda value: str(value.id)):
        await db.refresh(coalition, with_for_update=True)
        if coalition.status == "confirmed":
            raise HTTPException(409, "Группа уже создала обязательства; используйте согласованный процесс изменения сделки")
        coalition.status = "cancelled"
        coalition.version += 1
        groups = list((await db.scalars(select(GroupOffer).where(GroupOffer.coalition_id == coalition.id))).all())
        for group in groups:
            group.status, group.seller_approval_status = "recalculation_required", "pending"
            recipients.add(group.company_id)
        members = list((await db.scalars(select(CoalitionMember).where(CoalitionMember.coalition_id == coalition.id))).all())
        for member in members:
            member.approval_status = "pending"
            recipients.add(member.buyer_company_id)
        rows = list((await db.scalars(select(ResourceReservation).where(ResourceReservation.anchor_type == "coalition", ResourceReservation.anchor_id == coalition.id))).all())
        for company_id in sorted({row.company_id for row in rows}, key=str):
            await lock_company(db, company_id)
        for row in rows:
            await db.refresh(row, with_for_update=True)
        if any(row.status in {"committed", "consumed"} for row in rows):
            raise HTTPException(409, "Ресурс уже стал обязательством; требуется отдельное согласование")
        for row in rows:
            if row.status == "held":
                row.status = "released"
    for plan in sorted(plans, key=lambda row: str(row.id)):
        await db.refresh(plan, with_for_update=True)
        if plan.confirmed_at is not None:
            raise HTTPException(409, "План уже подтверждён; требуется изменение обязательств")
        plan.status = "stale"
        plan.version += 1
        reserves = list((await db.scalars(select(ReserveCommitment).where(ReserveCommitment.plan_id == plan.id))).all())
        for reserve in reserves:
            recipients.add(reserve.company_id)
            reserve.confirmation_status = "expired"
            rows = list((await db.scalars(select(ResourceReservation).where(ResourceReservation.anchor_type == "reserve", ResourceReservation.anchor_id == reserve.id))).all())
            for company_id in sorted({row.company_id for row in rows}, key=str):
                await lock_company(db, company_id)
            for row in rows:
                await db.refresh(row, with_for_update=True)
            if any(row.status in {"committed", "consumed"} for row in rows):
                raise HTTPException(409, "Резерв уже активирован; требуется изменение обязательства")
            for row in rows:
                if row.status == "held":
                    row.status = "released"
    for variant in variants:
        variant.result = {**variant.result, "stale": True, "stale_reason": "Спецификация потребности изменена"}
    await db.flush()
    from .deps import notify
    users = set((await db.scalars(text("SELECT DISTINCT user_id FROM auth.company_members WHERE company_id = ANY(:ids)"),
        {"ids": list(recipients)})).all())
    for uid in users:
        await notify(db, uid, f"Потребность {need.id}: версия {need.revision} требует новых КП и согласий. Прежние условия сохранены в истории.", "need_revision")
    await record_human_approval(db, action="need_specification_change", entity_type="need", entity_id=need.id,
        actor_user_id=user.id, actor_company_id=need.company_id, permission="company_admin+buyer",
        decision="approved", payload={"revision": need.revision, "impact": impact, "evidence": need.requirements_evidence},
        explanation="Покупатель подтвердил новую спецификацию и последствия для предварительных условий")
    await append_audit_event(db, event_type="need_specification_changed", entity_type="need", entity_id=need.id,
        actor_user_id=user.id, actor_company_id=need.company_id,
        explanation="Покупатель подтвердил последствия изменения опубликованной спецификации", payload=impact)


def store_revision(db, need, user, impact):
    db.add(NeedRevision(need_id=need.id, revision=need.revision, actor_user_id=user.id,
        snapshot=json.loads(canonical({**specification(need), "requirements_evidence": copy.deepcopy(need.requirements_evidence),
                  "category_profile": copy.deepcopy(need.category_profile)})), impact=json.loads(canonical(impact))))
