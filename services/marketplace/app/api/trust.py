import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_db
from ..deps import CurrentUser, get_current_user, notify, require_membership
from ..models import SupportTicket, TrustAuditEvent
from ..schemas import (
    AuditVerificationOut,
    KpiOut,
    SupportTicketIn,
    SupportTicketOut,
    SupportTicketUpdateIn,
    TrustAuditEventOut,
)
from ..trust import GENESIS_HASH, append_audit_event, verify_event

router = APIRouter(tags=["stage-7-trust"])


async def _is_marketplace_admin(db: AsyncSession, user_id: uuid.UUID) -> bool:
    result = await db.execute(
        text("SELECT is_marketplace_admin FROM auth.users WHERE id = :uid"), {"uid": user_id}
    )
    return bool(result.scalar_one_or_none())


async def _require_marketplace_admin(db: AsyncSession, user: CurrentUser) -> None:
    if not await _is_marketplace_admin(db, user.id):
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="Требуются права администратора площадки")


@router.post("/support/tickets", response_model=SupportTicketOut, status_code=status.HTTP_201_CREATED)
async def create_support_ticket(
    data: SupportTicketIn,
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if data.company_id:
        await require_membership(data.company_id, user, db)
    ticket = SupportTicket(user_id=user.id, **data.model_dump())
    db.add(ticket)
    await db.flush()
    await append_audit_event(
        db,
        event_type="support_ticket_created",
        entity_type="support_ticket",
        entity_id=ticket.id,
        actor_user_id=user.id,
        actor_company_id=data.company_id,
        source_refs=[{"type": "user_message", "id": str(ticket.id)}],
        explanation="Пользователь создал внутреннее обращение поддержки.",
        payload={"status": ticket.status, "subject": ticket.subject},
    )
    admin_ids = (await db.execute(text("SELECT id FROM auth.users WHERE is_marketplace_admin = true AND account_status = 'active'"))).scalars().all()
    for admin_id in admin_ids:
        await notify(db, admin_id, f"Новое обращение поддержки: {ticket.subject}", "support_ticket_created")
    await db.commit()
    await db.refresh(ticket)
    return ticket


@router.get("/support/tickets/mine", response_model=list[SupportTicketOut])
async def list_my_support_tickets(
    user: CurrentUser = Depends(get_current_user), db: AsyncSession = Depends(get_db)
):
    result = await db.execute(
        select(SupportTicket).where(SupportTicket.user_id == user.id).order_by(SupportTicket.updated_at.desc())
    )
    return result.scalars().all()


@router.get("/admin/support/tickets", response_model=list[SupportTicketOut])
async def list_support_tickets_admin(
    status_filter: str | None = Query(default=None, alias="status"),
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await _require_marketplace_admin(db, user)
    query = select(SupportTicket).order_by(SupportTicket.updated_at.desc())
    if status_filter:
        query = query.where(SupportTicket.status == status_filter)
    return (await db.execute(query)).scalars().all()


@router.patch("/admin/support/tickets/{ticket_id}", response_model=SupportTicketOut)
async def update_support_ticket_admin(
    ticket_id: uuid.UUID,
    data: SupportTicketUpdateIn,
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await _require_marketplace_admin(db, user)
    ticket = await db.get(SupportTicket, ticket_id)
    if ticket is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Обращение не найдено")
    previous_status = ticket.status
    ticket.status = data.status
    ticket.admin_response = data.admin_response
    ticket.assigned_admin_user_id = user.id
    await append_audit_event(
        db,
        event_type="support_ticket_updated",
        entity_type="support_ticket",
        entity_id=ticket.id,
        actor_user_id=user.id,
        actor_company_id=ticket.company_id,
        source_refs=[{"type": "support_ticket", "id": str(ticket.id)}],
        explanation=f"Администратор изменил статус обращения: {previous_status} → {data.status}.",
        payload={"from_status": previous_status, "to_status": data.status},
    )
    await notify(db, ticket.user_id, f"Поддержка обновила обращение «{ticket.subject}»: {data.status}", "support_ticket_updated")
    await db.commit()
    await db.refresh(ticket)
    return ticket


@router.get("/audit/events", response_model=list[TrustAuditEventOut])
async def list_audit_events(
    company_id: uuid.UUID | None = None,
    limit: int = Query(default=100, ge=1, le=500),
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    admin = await _is_marketplace_admin(db, user.id)
    query = select(TrustAuditEvent).order_by(TrustAuditEvent.sequence.desc()).limit(limit)
    if not admin:
        if company_id:
            await require_membership(company_id, user, db)
            query = query.where(TrustAuditEvent.actor_company_id == company_id)
        else:
            memberships = await db.execute(
                text("SELECT company_id FROM auth.company_members WHERE user_id = :uid"), {"uid": user.id}
            )
            company_ids = list(memberships.scalars().all())
            query = query.where(
                or_(TrustAuditEvent.actor_user_id == user.id, TrustAuditEvent.actor_company_id.in_(company_ids))
            )
    elif company_id:
        query = query.where(TrustAuditEvent.actor_company_id == company_id)
    events = (await db.execute(query)).scalars().all()
    if admin:
        return events
    # Events may reference other coalition participants. Keep the event and
    # explanation visible to the member while hiding cross-company details.
    return [TrustAuditEventOut.model_validate(event).model_copy(update={
        "source_refs": [], "payload": {},
    }) for event in events]


@router.get("/audit/verify", response_model=AuditVerificationOut)
async def verify_audit_chain(
    user: CurrentUser = Depends(get_current_user), db: AsyncSession = Depends(get_db)
):
    await _require_marketplace_admin(db, user)
    events = (await db.execute(select(TrustAuditEvent).order_by(TrustAuditEvent.sequence))).scalars().all()
    previous_hash = GENESIS_HASH
    for expected_sequence, event in enumerate(events, start=1):
        if event.sequence != expected_sequence or not verify_event(previous_hash, event):
            return AuditVerificationOut(valid=False, checked_events=expected_sequence, broken_sequence=event.sequence)
        previous_hash = event.event_hash
    return AuditVerificationOut(valid=True, checked_events=len(events))


@router.get("/kpi", response_model=KpiOut)
async def calculate_kpi(
    company_id: uuid.UUID | None = None,
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    admin = await _is_marketplace_admin(db, user.id)
    if company_id:
        if not admin:
            await require_membership(company_id, user, db)
    elif not admin:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Укажите свою компанию")

    rows = (await db.execute(select(TrustAuditEvent))).scalars().all()
    if company_id:
        rows = [
            event for event in rows
            if event.actor_company_id == company_id
            or event.payload.get("seller_company_id") == str(company_id)
        ]
    payloads = [event.payload for event in rows]
    buyer_actions = {"confirm_resilience_plan", "approve_recovery", "select_offer_and_create_deal"}
    buyer_approvals = sum(
        event.event_type == "human_approval_recorded" and event.payload.get("action") in buyer_actions
        for event in rows
    )
    seller_approvals = sum(
        event.event_type == "human_approval_recorded"
        and event.payload.get("action") == "reserve_commitment_decision"
        for event in rows
    )
    recoveries = [p for e, p in zip(rows, payloads) if e.event_type == "recovery_activated"]
    buyer_value_events = [p for p in payloads if p.get("buyer_value_rub") is not None]
    seller_value_events = [p for p in payloads if p.get("seller_value_rub") is not None]
    buyer_value = sum(float(p["buyer_value_rub"]) for p in buyer_value_events)
    seller_value = sum(float(p["seller_value_rub"]) for p in seller_value_events)
    deal_events = [p for e, p in zip(rows, payloads) if e.event_type == "deal_created"]
    gmv = sum(float(p.get("gmv_rub", 0)) for p in deal_events)
    reserve_units = sum(
        int(p.get("decision_payload", {}).get("capacity_units") or 0)
        for e, p in zip(rows, payloads)
        if e.event_type == "human_approval_recorded" and p.get("action") == "reserve_commitment_decision"
    )
    return KpiOut(
        scope="company" if company_id else "marketplace",
        company_id=company_id,
        generated_from_events=len(rows),
        buyer={
            "created_value_rub": round(buyer_value, 2),
            "value_events": len(buyer_value_events),
            "human_approvals": buyer_approvals,
            "successful_recoveries": len(recoveries),
        },
        seller={
            "created_value_rub": round(seller_value, 2),
            "value_events": len(seller_value_events),
            "confirmed_reserve_units": reserve_units,
            "sales_gmv_rub": round(gmv, 2),
            "human_approvals": seller_approvals,
        },
        marketplace={"gmv_rub": round(gmv, 2), "audited_events": len(rows), "deals": len(deal_events)},
        baseline_note="Созданная ценность — разница с зафиксированной до оптимизации базовой конфигурацией. При нуле событий с сопоставимой базой данных для оценки нет.",
    )
