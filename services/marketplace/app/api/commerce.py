import uuid
from datetime import date, datetime, time, timezone
from decimal import Decimal
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..commerce import execution_totals, financials
from ..database import get_db
from ..deps import CurrentUser, get_current_user, require_company_admin, require_company_buyer, require_company_seller, require_membership
from ..models import Deal, DealCheckpoint, DealCostSnapshot, DealExecutionEvent, Need, Offer
from ..resources import release
from ..trust import record_human_approval

router = APIRouter(tags=["commercial-accounting"])


class ExecutionIn(BaseModel):
    company_id: uuid.UUID
    kind: Literal["acceptance", "return", "cancellation"]
    units: int = Field(gt=0)
    note: str = Field(min_length=3, max_length=1000)
    idempotency_key: uuid.UUID
    human_approved: Literal[True]


class DecisionIn(BaseModel):
    company_id: uuid.UUID
    approved: bool
    human_approved: Literal[True]


class CostsIn(BaseModel):
    company_id: uuid.UUID
    expected_revision: int = Field(ge=0)
    unit_cost_rub: Decimal | None = Field(default=None, ge=0, max_digits=18, decimal_places=2)
    attributable_expenses_rub: Decimal | None = Field(default=None, ge=0, max_digits=18, decimal_places=2)
    note: str = Field(min_length=3, max_length=1000)
    human_approved: Literal[True]


class EventOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    actor_company_id: uuid.UUID
    kind: str
    units: int
    note: str
    status: str
    created_at: datetime
    decided_at: datetime | None


async def party(db, deal_id, company_id, user, *, lock=False):
    stmt = select(Deal).where(Deal.id == deal_id)
    if lock:
        stmt = stmt.with_for_update()
    deal = await db.scalar(stmt)
    if not deal or company_id not in {deal.buyer_company_id, deal.seller_company_id}:
        raise HTTPException(404, "Сделка не найдена")
    await require_membership(company_id, user, db)
    return deal


async def events_for(db, deal_id):
    return list((await db.scalars(select(DealExecutionEvent).where(DealExecutionEvent.deal_id == deal_id)
                                 .order_by(DealExecutionEvent.created_at, DealExecutionEvent.id))).all())


def validate_quantity(deal, events, kind, units):
    totals = execution_totals(deal, events)
    limit = totals["net_units"] if kind == "return" else totals["open_units"]
    if units > limit:
        raise HTTPException(409, f"Количество превышает доступное для операции: {limit}")


def sync_status(deal, events):
    totals = execution_totals(deal, events)
    if totals["open_units"] == 0:
        deal.status = ("cancelled" if totals["cancelled_units"] == deal.units
                       else "returned" if totals["returned_units"] and totals["net_units"] == 0 else "fulfilled")
    elif totals["accepted_units"]:
        deal.status = "partially_accepted"


async def audit(db, deal, company_id, user, action, payload, approved=True):
    await record_human_approval(db, action=action, entity_type="deal", entity_id=deal.id,
        actor_user_id=user.id, actor_company_id=company_id, permission="company_admin+deal_party",
        decision="approved" if approved else "rejected", payload=payload,
        source_refs=[{"type": "deal", "id": str(deal.id)}],
        explanation="Участник сделки явно подтвердил операцию учёта исполнения.")


@router.get("/deals/{deal_id}/execution")
async def execution(deal_id: uuid.UUID, company_id: uuid.UUID, user: CurrentUser = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    deal = await party(db, deal_id, company_id, user)
    events = await events_for(db, deal.id)
    totals = execution_totals(deal, events)
    result = {"deal_id": deal.id, "status": deal.status, **totals,
              "events": [EventOut.model_validate(e) for e in events]}
    # Seller costs are private, including cost notes and revisions.
    if company_id == deal.seller_company_id:
        costs = await db.get(DealCostSnapshot, deal.id)
        result["financials"] = financials(deal, totals, costs)
        result["cost_revision"] = costs.revision if costs else 0
        result["unit_cost_rub"] = costs.unit_cost_rub if costs else None
        result["cost_note"] = costs.note if costs else ""
    else:
        result["financials"] = {key: value for key, value in financials(deal, totals).items()
                                if key in {"unit_price_rub", "ordered_value_rub", "delivery_price_rub", "net_goods_revenue_rub", "payments_rub"}}
    return result


@router.post("/deals/{deal_id}/execution", response_model=EventOut, status_code=201)
async def create_event(deal_id: uuid.UUID, data: ExecutionIn, user: CurrentUser = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    deal = await party(db, deal_id, data.company_id, user, lock=True)
    await require_company_admin(data.company_id, user, db)
    events = await events_for(db, deal.id)
    existing = next((e for e in events if e.actor_company_id == data.company_id and e.idempotency_key == data.idempotency_key), None)
    if existing:
        if (existing.kind, existing.units, existing.note) != (data.kind, data.units, data.note):
            raise HTTPException(409, "Ключ операции уже использован для других данных")
        return existing
    if data.kind in {"acceptance", "return"} and data.company_id != deal.buyer_company_id:
        raise HTTPException(403, "Приёмку и запрос возврата оформляет покупатель")
    if data.kind == "acceptance":
        shipment = await db.scalar(select(DealCheckpoint).where(DealCheckpoint.deal_id == deal.id, DealCheckpoint.kind == "shipment"))
        if not shipment or shipment.status != "completed":
            raise HTTPException(409, "Приёмка доступна после подтверждения отгрузки")
    validate_quantity(deal, events, data.kind, data.units)
    event = DealExecutionEvent(deal_id=deal.id, actor_company_id=data.company_id, actor_user_id=user.id,
        idempotency_key=data.idempotency_key, kind=data.kind, units=data.units, note=data.note,
        status="confirmed" if data.kind == "acceptance" else "pending")
    if event.status == "confirmed":
        event.decided_by_user_id, event.decided_at = user.id, datetime.now(timezone.utc)
    db.add(event)
    await db.flush()
    sync_status(deal, [*events, event])
    await audit(db, deal, data.company_id, user, "record_execution", {"event_id": str(event.id), "kind": event.kind, "units": event.units})
    await db.commit()
    return event


@router.post("/deals/{deal_id}/execution/{event_id}/decision", response_model=EventOut)
async def decide_event(deal_id: uuid.UUID, event_id: uuid.UUID, data: DecisionIn, user: CurrentUser = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    deal = await party(db, deal_id, data.company_id, user, lock=True)
    await require_company_admin(data.company_id, user, db)
    events = await events_for(db, deal.id)
    event = next((e for e in events if e.id == event_id), None)
    if not event:
        raise HTTPException(404, "Операция не найдена")
    if event.kind == "acceptance" or event.actor_company_id == data.company_id:
        raise HTTPException(403, "Запрос подтверждает другая сторона сделки")
    requested = "confirmed" if data.approved else "rejected"
    if event.status != "pending":
        if event.status == requested:
            return event
        raise HTTPException(409, "По запросу уже принято другое решение")
    if data.approved:
        validate_quantity(deal, events, event.kind, event.units)
    if data.approved and event.kind == "cancellation":
        await release(db, company_id=deal.seller_company_id, anchor_type="deal", anchor_id=deal.id, units=event.units)
    event.status = requested
    event.decided_by_user_id, event.decided_at = user.id, datetime.now(timezone.utc)
    sync_status(deal, events)
    await audit(db, deal, data.company_id, user, "decide_execution", {"event_id": str(event.id), "kind": event.kind, "units": event.units}, data.approved)
    await db.commit()
    return event


@router.put("/deals/{deal_id}/costs")
async def save_costs(deal_id: uuid.UUID, data: CostsIn, user: CurrentUser = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    deal = await party(db, deal_id, data.company_id, user, lock=True)
    if data.company_id != deal.seller_company_id:
        raise HTTPException(403, "Себестоимость доступна только продавцу")
    await require_company_admin(data.company_id, user, db)
    costs = await db.get(DealCostSnapshot, deal.id)
    revision = costs.revision if costs else 0
    if data.expected_revision != revision:
        raise HTTPException(409, "Расходы уже изменены. Обновите данные перед сохранением")
    if costs is None:
        costs = DealCostSnapshot(deal_id=deal.id)
        db.add(costs)
    costs.unit_cost_rub, costs.attributable_expenses_rub = data.unit_cost_rub, data.attributable_expenses_rub
    costs.revision, costs.note, costs.updated_by_user_id = revision + 1, data.note, user.id
    # Public deal audit contains only revision, never seller-private amounts.
    await audit(db, deal, data.company_id, user, "update_cost_snapshot", {"cost_revision": costs.revision})
    await db.commit()
    return {"revision": costs.revision}


@router.get("/companies/{company_id}/commercial-analytics")
async def analytics(company_id: uuid.UUID, role: Literal["buyer", "seller"], start: date | None = None, end: date | None = None,
                    category: str | None = None, user: CurrentUser = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    await (require_company_seller if role == "seller" else require_company_buyer)(company_id, user, db)
    if start and end and start > end:
        raise HTTPException(422, "Начало периода должно быть не позже окончания")
    # Explicit order cohort: period filters creation, execution is current for that cohort.
    owner = Deal.seller_company_id if role == "seller" else Deal.buyer_company_id
    query = select(Deal, Need.category).join(Need, Need.id == Deal.need_id).where(owner == company_id)
    if start:
        query = query.where(Deal.created_at >= datetime.combine(start, time.min, tzinfo=timezone.utc))
    if end:
        query = query.where(Deal.created_at <= datetime.combine(end, time.max, tzinfo=timezone.utc))
    if category:
        query = query.where(Need.category == category)
    pairs = (await db.execute(query.order_by(Deal.created_at.desc()))).all()
    ids = [deal.id for deal, _ in pairs]
    all_events = list((await db.scalars(select(DealExecutionEvent).where(DealExecutionEvent.deal_id.in_(ids)))).all()) if ids else []
    costs_by_id = {c.deal_id: c for c in (await db.scalars(select(DealCostSnapshot).where(DealCostSnapshot.deal_id.in_(ids)))).all()} if ids and role == "seller" else {}
    by_deal = {}
    for event in all_events:
        by_deal.setdefault(event.deal_id, []).append(event)
    rows = []
    for deal, category_name in pairs:
        totals = execution_totals(deal, by_deal.get(deal.id, []))
        values = financials(deal, totals, costs_by_id.get(deal.id))
        if role == "buyer":
            values = {key: value for key, value in values.items() if key in {"unit_price_rub", "ordered_value_rub", "delivery_price_rub", "net_goods_revenue_rub", "payments_rub"}}
        rows.append({"deal_id": deal.id, "category": category_name, "created_at": deal.created_at, "status": deal.status, **totals, **values})
    aggregate = {}
    keys = ("ordered_value_rub", "net_goods_revenue_rub", "cost_of_goods_rub", "gross_profit_rub", "attributable_expenses_rub", "contribution_rub") if role == "seller" else ("ordered_value_rub", "net_goods_revenue_rub")
    for key in keys:
        known = [row[key] for row in rows if row[key] is not None]
        aggregate[key] = sum(known, Decimal(0)) if len(known) == len(rows) else None
        aggregate[f"{key}_known_orders"] = len(known)
    # Rejections are separate from execution; never fold them into cancellations.
    offer_query = select(Offer).join(Need, Need.id == Offer.need_id).where((Offer.company_id if role == "seller" else Need.company_id) == company_id)
    if start: offer_query = offer_query.where(Offer.created_at >= datetime.combine(start, time.min, tzinfo=timezone.utc))
    if end: offer_query = offer_query.where(Offer.created_at <= datetime.combine(end, time.max, tzinfo=timezone.utc))
    if category: offer_query = offer_query.where(Need.category == category)
    offers = list((await db.scalars(offer_query)).all())
    return {"company_id": company_id, "role": role, "period_basis": "order_created_at_utc", "orders_count": len(rows),
            "offers_count": len(offers), "rejected_offers_count": sum(o.status == "rejected" for o in offers),
            "payments_rub": None, "totals": aggregate, "orders": rows,
            "explanation": "Период — дата создания заказа (UTC); исполнение — текущее состояние этих заказов. Выручка от товаров учитывает приёмку минус подтверждённые возвраты, без доставки. Прибыль рассчитана по указанным продавцом затратам; платежи не подключены. Отказы относятся к предложениям, созданным в выбранный период. Количества сравниваются внутри заказа."}
