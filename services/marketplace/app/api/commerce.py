from ..money import Money, Amount
import uuid
from datetime import date, datetime, time, timezone
from decimal import Decimal
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from ..commerce import execution_totals, financials
from ..database import get_db
from ..deps import CurrentUser, get_current_user, notify, require_company_admin, require_company_buyer, require_company_seller, require_membership
from ..matching import order_unit
from ..models import Deal, DealCheckpoint, DealCostSnapshot, DealExecutionEvent, DeliveryArrangement, HumanApprovalRecord, Need, Offer, ParticipantOrder, ResourceReservation
from ..resources import release, consume
from ..resilience_execution import lock_execution_need, require_shipment_allowed
from ..trust import record_human_approval

router = APIRouter(tags=["commercial-accounting"])


class ExecutionIn(BaseModel):
    company_id: uuid.UUID
    kind: Literal["acceptance", "return", "cancellation", "shipment"]
    units: int = Field(gt=0)
    note: str = Field(min_length=3, max_length=1000)
    idempotency_key: uuid.UUID
    human_approved: Literal[True]


class DecisionIn(BaseModel):
    company_id: uuid.UUID
    approved: bool
    human_approved: Literal[True]
    restock_accepted: bool = False


class CostsIn(BaseModel):
    company_id: uuid.UUID
    expected_revision: int = Field(ge=0)
    unit_cost_rub: Money | None = Field(default=None, ge=0)
    attributable_expenses_rub: Amount | None = Field(default=None, ge=0)
    tax_basis: Literal["includes_vat", "no_vat", "unknown"] = "unknown"
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
        await lock_execution_need(db, deal_id)
        stmt = stmt.with_for_update().execution_options(populate_existing=True)
    deal = await db.scalar(stmt)
    if not deal or company_id not in {deal.buyer_company_id, deal.seller_company_id}:
        raise HTTPException(404, "Сделка не найдена")
    await require_membership(company_id, user, db)
    return deal


async def events_for(db, deal_id):
    return list((await db.scalars(select(DealExecutionEvent).where(DealExecutionEvent.deal_id == deal_id)
                                  .order_by(DealExecutionEvent.created_at, DealExecutionEvent.id))).all())


KIND_RU = {"acceptance": "приёмка", "return": "возврат", "cancellation": "отмена"}


async def company_display_name(db, company_id) -> str:
    name = await db.scalar(text("SELECT display_name FROM auth.companies WHERE id = :id"), {"id": company_id})
    return name or str(company_id)


def execution_unit(need) -> str:
    try:
        return order_unit(need.characteristics) if need is not None else "шт"
    except Exception:
        return "шт"


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


async def shipping_totals(db, deal, events):
    totals = execution_totals(deal, events)
    from ..models import DealFulfillment
    fulfillment = await db.get(DealFulfillment, deal.id)
    if fulfillment:
        from .fulfillment import unshipped
        return {"shipped_units": sum(b["units"] for b in fulfillment.data["batches"]), "unshipped_units": unshipped(deal, fulfillment.data, totals)}
    checkpoint = await db.scalar(select(DealCheckpoint).where(DealCheckpoint.deal_id == deal.id, DealCheckpoint.kind == "shipment"))
    shipped = deal.units - totals["cancelled_units"] if checkpoint and checkpoint.status == "completed" else sum(
        event.units for event in events if event.kind == "shipment" and event.status == "confirmed")
    return {"shipped_units": shipped, "unshipped_units": max(0, deal.units-totals["cancelled_units"]-shipped)}


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
              "events": [EventOut.model_validate(e) for e in events], **await shipping_totals(db, deal, events)}
    # Seller costs are private, including cost notes and revisions.
    if company_id == deal.seller_company_id:
        costs = await db.get(DealCostSnapshot, deal.id)
        result["financials"] = financials(deal, totals, costs)
        result["cost_revision"] = costs.revision if costs else 0
        result["cost_tax_basis"] = costs.tax_basis if costs else "unknown"
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
    from ..fulfillment import require_legacy_execution
    await require_legacy_execution(db, deal.id)
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
        shipped = await shipping_totals(db, deal, events)
        accepted = execution_totals(deal, events)["accepted_units"]
        if data.units > shipped["shipped_units"] - accepted:
            raise HTTPException(409, "Приёмка доступна только на фактически отгруженный объём")
        arrangement = await db.scalar(select(DeliveryArrangement).where(DeliveryArrangement.deal_id == deal.id))
        if arrangement is None:
            raise HTTPException(409, "Приёмка фиксирует получение: сначала выберите способ получения")
    if data.kind == "shipment":
        if data.company_id != deal.seller_company_id:
            raise HTTPException(403, "Отгрузку подтверждает производитель")
        await require_shipment_allowed(db, deal)
        production = await db.scalar(select(DealCheckpoint).where(DealCheckpoint.deal_id == deal.id, DealCheckpoint.kind == "production"))
        if not production or production.status != "completed":
            raise HTTPException(409, "Сначала подтвердите производство")
        shipping = await shipping_totals(db, deal, events)
        if data.units > shipping["unshipped_units"]:
            raise HTTPException(409, "Объём отгрузки превышает неотгруженный остаток")
        await consume(db, company_id=deal.seller_company_id, anchor_type="deal", anchor_id=deal.id, units=data.units)
    if data.kind == "cancellation":
        shipping = await shipping_totals(db, deal, events)
        if data.units > shipping["unshipped_units"]:
            raise HTTPException(409, "Отгруженный объём нельзя перенести или отменить как остаток")
    validate_quantity(deal, events, data.kind, data.units)
    event = DealExecutionEvent(deal_id=deal.id, actor_company_id=data.company_id, actor_user_id=user.id,
        idempotency_key=data.idempotency_key, kind=data.kind, units=data.units, note=data.note,
        status="confirmed" if data.kind in {"acceptance", "shipment"} else "pending")
    if event.status == "confirmed":
        event.decided_by_user_id, event.decided_at = user.id, datetime.now(timezone.utc)
    db.add(event)
    await db.flush()
    sync_status(deal, [*events, event])
    if data.kind == "shipment":
        shipment = await db.scalar(select(DealCheckpoint).where(DealCheckpoint.deal_id == deal.id, DealCheckpoint.kind == "shipment"))
        shipping = await shipping_totals(db, deal, [*events, event])
        deal.status = "shipped" if shipping["unshipped_units"] == 0 else "partially_shipped"
        if shipment and shipping["unshipped_units"] == 0:
            shipment.status, shipment.completed_at, shipment.confirmed_by_user_id = "completed", datetime.now(timezone.utc), user.id
    if data.kind == "acceptance" and execution_totals(deal, [*events, event])["open_units"] == 0:
        from .stage9 import _ensure_checkpoints
        checkpoints = await _ensure_checkpoints(deal.id, db)
        checkpoints[-1].status = "completed"
        checkpoints[-1].completed_at = datetime.now(timezone.utc)
        checkpoints[-1].confirmed_by_user_id = user.id
    need = await db.get(Need, deal.need_id)
    offer = await db.get(Offer, deal.offer_id)
    await audit(db, deal, data.company_id, user, "record_execution",
                {"event_id": str(event.id), "kind": event.kind, "units": event.units,
                 "need_revision": need.revision if need else None,
                 "offer_revision": offer.revision if offer else None})
    if data.kind in {"return", "cancellation"}:
        other_company_id = deal.seller_company_id if data.company_id == deal.buyer_company_id else deal.buyer_company_id
        other_users = (await db.execute(text(
            "SELECT user_id FROM auth.company_members WHERE company_id = :company_id"
        ), {"company_id": other_company_id})).scalars().all()
        actor_name = await company_display_name(db, data.company_id)
        unit = execution_unit(need)
        for other_user_id in set(other_users):
            await notify(db, other_user_id,
                         f"Требуется решение: {KIND_RU.get(event.kind, event.kind)} {event.units} {unit} "
                         f"по сделке {deal.id} (запрос {event.id} от {actor_name}).",
                         "deal_execution_requested")
    await db.commit()
    return event


@router.post("/deals/{deal_id}/execution/{event_id}/decision", response_model=EventOut)
async def decide_event(deal_id: uuid.UUID, event_id: uuid.UUID, data: DecisionIn, user: CurrentUser = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    deal = await party(db, deal_id, data.company_id, user, lock=True)
    await require_company_admin(data.company_id, user, db)
    from ..fulfillment import require_legacy_execution
    await require_legacy_execution(db, deal.id)
    events = await events_for(db, deal.id)
    event = next((e for e in events if e.id == event_id), None)
    if not event:
        raise HTTPException(404, "Операция не найдена")
    if event.kind in {"acceptance", "shipment"} or event.actor_company_id == data.company_id:
        raise HTTPException(403, "Запрос подтверждает другая сторона сделки")
    requested = "confirmed" if data.approved else "rejected"
    if event.status != "pending":
        if event.status == requested:
            if event.kind == "return" and data.approved:
                restocked = await db.scalar(select(HumanApprovalRecord.id).where(
                    HumanApprovalRecord.action == "stock_return",
                    HumanApprovalRecord.entity_type == "deal_execution_event",
                    HumanApprovalRecord.entity_id == event.id,
                ))
                if bool(restocked) != data.restock_accepted:
                    raise HTTPException(409, "Решение о качестве возврата уже принято с другими условиями")
            return event
        raise HTTPException(409, "По запросу уже принято другое решение")
    if data.approved:
        validate_quantity(deal, events, event.kind, event.units)
    if data.approved and event.kind == "cancellation":
        if event.units > (await shipping_totals(db, deal, events))["unshipped_units"]:
            raise HTTPException(409, "Отгруженный объём нельзя отменить как остаток")
        await release(db, company_id=deal.seller_company_id, anchor_type="deal", anchor_id=deal.id, units=event.units)
    event.status = requested
    event.decided_by_user_id, event.decided_at = user.id, datetime.now(timezone.utc)
    if data.approved and event.kind == "return" and data.restock_accepted:
        from ..resources import return_stock
        product_id = await db.scalar(select(ResourceReservation.product_id).where(
            ResourceReservation.company_id == deal.seller_company_id,
            ResourceReservation.anchor_type == "deal",
            ResourceReservation.anchor_id == deal.id,
            ResourceReservation.product_id.is_not(None),
        ))
        if product_id is None:
            raise HTTPException(409, "Возврат на склад неприменим: сделка выполнена мощностью без складского товара")
        await return_stock(db, company_id=deal.seller_company_id, product_id=product_id,
                           units=event.units, quality_accepted=True,
                           return_event_id=event.id, actor_user_id=user.id)
    sync_status(deal, events)
    need = await db.get(Need, deal.need_id)
    offer = await db.get(Offer, deal.offer_id)
    await audit(db, deal, data.company_id, user, "decide_execution", {"event_id": str(event.id), "kind": event.kind, "units": event.units, "restock_accepted": data.restock_accepted, "need_revision": need.revision if need else None, "offer_revision": offer.revision if offer else None}, data.approved)
    requester_users = (await db.execute(text(
        "SELECT user_id FROM auth.company_members WHERE company_id = :company_id"
    ), {"company_id": event.actor_company_id})).scalars().all()
    unit = execution_unit(need)
    verdict = "подтверждено" if data.approved else "отклонено"
    for requester_id in set(requester_users):
        await notify(db, requester_id,
                     f"Решение принято: {KIND_RU.get(event.kind, event.kind)} {event.units} {unit} "
                     f"по сделке {deal.id} (запрос {event.id}) — {verdict}.",
                     "deal_execution_decided")
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
    costs.tax_basis = data.tax_basis
    costs.revision, costs.note, costs.updated_by_user_id = revision + 1, data.note, user.id
    # Public deal audit contains only revision, never seller-private amounts.
    await audit(db, deal, data.company_id, user, "update_cost_snapshot", {"cost_revision": costs.revision})
    await db.commit()
    return {"revision": costs.revision}


def _csv_cell(value) -> str:
    text_value = "Нет данных" if value is None else str(value)
    if text_value[:1] in ("=", "+", "-", "@") or (text_value[:1].isspace() and text_value.lstrip()[:1] in ("=", "+", "-", "@")):
        text_value = "'" + text_value
    return '"' + text_value.replace('"', '""') + '"'


async def _commercial_report(db, company_id, role, *, start=None, end=None, category=None,
                             status=None, counterparty=None, product=None, source="all"):
    if start and end and start > end:
        raise HTTPException(422, "Начало периода должно быть не позже окончания")
    if source not in ("all", "direct", "group"):
        raise HTTPException(422, "Источник заказа: all, direct или group")
    built_at = datetime.now(timezone.utc)
    # Explicit order cohort: period filters creation, execution is current for that cohort.
    owner = Deal.seller_company_id if role == "seller" else Deal.buyer_company_id
    query = select(Deal, Need).join(Need, Need.id == Deal.need_id).where(owner == company_id)
    if start:
        query = query.where(Deal.created_at >= datetime.combine(start, time.min, tzinfo=timezone.utc))
    if end:
        query = query.where(Deal.created_at <= datetime.combine(end, time.max, tzinfo=timezone.utc))
    if category:
        query = query.where(Need.category == category)
    if status:
        query = query.where(Deal.status == status)
    pairs = list((await db.execute(query.order_by(Deal.created_at.desc()))).all())
    if counterparty:
        wanted = counterparty.strip().lower()
        other_ids = list({getattr(d, "buyer_company_id" if role == "seller" else "seller_company_id") for d, _ in pairs})
        names = dict((await db.execute(text(
            "SELECT id, display_name FROM auth.companies WHERE id = ANY(:ids)"),
            {"ids": other_ids})).all()) if other_ids else {}
        pairs = [(d, n) for d, n in pairs
                 if wanted in (names.get(getattr(d, "buyer_company_id" if role == "seller" else "seller_company_id")) or "").lower()]
    if product:
        offer_ids = [d.offer_id for d, _ in pairs]
        prod_of_offer = {}
        titles: dict = {}
        if offer_ids:
            prod_of_offer = {o.id: o.product_id for o in (await db.scalars(select(Offer).where(Offer.id.in_(offer_ids)))).all()}
            product_ids = list({pid for pid in prod_of_offer.values() if pid})
            if product_ids:
                titles = dict((await db.execute(text(
                    "SELECT id, name FROM marketplace.products WHERE id = ANY(:ids)"),
                    {"ids": product_ids})).all())
        wanted = product.strip().lower()
        pairs = [(d, n) for d, n in pairs
                 if wanted in (titles.get(prod_of_offer.get(d.offer_id)) or "").lower()]
    ids = [deal.id for deal, _ in pairs]
    all_events = list((await db.scalars(select(DealExecutionEvent).where(DealExecutionEvent.deal_id.in_(ids)))).all()) if ids else []
    costs_by_id = {c.deal_id: c for c in (await db.scalars(select(DealCostSnapshot).where(DealCostSnapshot.deal_id.in_(ids)))).all()} if ids and role == "seller" else {}
    by_deal = {}
    for event in all_events:
        by_deal.setdefault(event.deal_id, []).append(event)
    rows = []
    for deal, need in pairs:
        totals = execution_totals(deal, by_deal.get(deal.id, []))
        costs = costs_by_id.get(deal.id)
        values = financials(deal, totals, costs)
        if role == "seller":
            values["cost_tax_basis"] = costs.tax_basis if costs else "unknown"
        if role == "buyer":
            values = {key: value for key, value in values.items() if key in {"unit_price_rub", "ordered_value_rub", "delivery_price_rub", "net_goods_revenue_rub", "payments_rub"}}
        rows.append({"deal_id": deal.id, "category": need.category, "unit": order_unit(need.characteristics), "created_at": deal.created_at, "status": deal.status, **totals, **values})
    aggregate = {}
    keys = ("ordered_value_rub", "net_goods_revenue_rub", "cost_of_goods_rub", "gross_profit_rub", "attributable_expenses_rub", "contribution_rub") if role == "seller" else ("ordered_value_rub", "net_goods_revenue_rub")
    for key in keys:
        known = [row[key] for row in rows if row[key] is not None]
        aggregate[key] = sum(known, Decimal(0)) if len(known) == len(rows) else None
        aggregate[f"{key}_known_orders"] = len(known)
    # Average price only over comparable executed volume: one line per unit.
    by_unit: dict = {}
    for row in rows:
        if row["accepted_units"] and row["net_goods_revenue_rub"] is not None:
            slot = by_unit.setdefault(row["unit"], {"value": Decimal(0), "units": 0})
            slot["value"] += row["net_goods_revenue_rub"]
            slot["units"] += row["accepted_units"]
    average_prices = [{"unit": unit, "accepted_units": slot["units"],
                       "average_unit_price_rub": (slot["value"] / slot["units"]).quantize(Decimal("0.01"))}
                      for unit, slot in sorted(by_unit.items()) if slot["units"] > 0]
    # Rejections are separate from execution; never fold them into cancellations.
    # Cohort: offers created in the period. Known outcomes: rejected + selected;
    # sent is open, anything else expired without a decision.
    offer_query = select(Offer).join(Need, Need.id == Offer.need_id).where((Offer.company_id if role == "seller" else Need.company_id) == company_id)
    if start: offer_query = offer_query.where(Offer.created_at >= datetime.combine(start, time.min, tzinfo=timezone.utc))
    if end: offer_query = offer_query.where(Offer.created_at <= datetime.combine(end, time.max, tzinfo=timezone.utc))
    if category: offer_query = offer_query.where(Need.category == category)
    offers = list((await db.scalars(offer_query)).all())
    rejected = sum(o.status == "rejected" for o in offers)
    selected = sum(o.status == "selected" for o in offers)
    open_offers = sum(o.status == "sent" for o in offers)
    stale = sum(o.status not in ("rejected", "selected", "sent") for o in offers)
    known = rejected + selected
    rejection_rate = {"offers_total": len(offers), "rejected": rejected, "selected": selected,
                      "open": open_offers, "stale": stale, "known_outcomes": known,
                      "rate_pct": round(rejected / known * 100, 1) if known else None}
    monthly_buckets: dict = {}
    for row in rows:
        month = row["created_at"].strftime("%Y-%m")
        slot = monthly_buckets.setdefault(month, {"orders": 0, "value": Decimal(0), "value_known": 0,
                                                  "units": 0, "unit": row["unit"], "mixed_units": False})
        slot["orders"] += 1
        if row["net_goods_revenue_rub"] is not None:
            slot["value"] += row["net_goods_revenue_rub"]
            slot["value_known"] += 1
        if row["unit"] != slot["unit"]:
            slot["mixed_units"] = True
        else:
            slot["units"] += row["accepted_units"] or 0
    monthly = [{"month": month, "orders_count": slot["orders"],
                "accepted_value_rub": slot["value"] if slot["value_known"] else None,
                "accepted_units": None if slot["mixed_units"] else slot["units"],
                "unit": None if slot["mixed_units"] else slot["unit"]}
               for month, slot in sorted(monthly_buckets.items())]
    group_owner = ParticipantOrder.seller_company_id if role == "seller" else ParticipantOrder.buyer_company_id
    group_query = select(ParticipantOrder, Need).join(Need, Need.id == ParticipantOrder.need_id).where(
        group_owner == company_id, ParticipantOrder.status != "superseded")
    if start: group_query = group_query.where(ParticipantOrder.created_at >= datetime.combine(start, time.min, tzinfo=timezone.utc))
    if end: group_query = group_query.where(ParticipantOrder.created_at <= datetime.combine(end, time.max, tzinfo=timezone.utc))
    if category: group_query = group_query.where(Need.category == category)
    group_orders = [{"order_id": item.id, "coalition_id": item.coalition_id, "category": need.category,
                     "unit": order_unit(need.characteristics), "created_at": item.created_at, "status": item.status, "units": item.units,
                     "contract_value_rub": Decimal(str(item.total_price_rub)), "payments_rub": None}
                    for item, need in (await db.execute(group_query.order_by(ParticipantOrder.created_at.desc()))).all()]
    if source == "direct":
        group_orders = []
    if source == "group":
        rows, average_prices, monthly = [], [], []
        aggregate = {k: (0 if k.endswith("_known_orders") else None) for k in aggregate}
    return {"company_id": company_id, "role": role, "period_basis": "order_created_at_utc", "built_at": built_at,
            "filters": {"start": start.isoformat() if start else None, "end": end.isoformat() if end else None,
                        "category": category, "status": status, "counterparty": counterparty, "product": product, "source": source},
            "orders_count": len(rows),
            "offers_count": len(offers), "rejected_offers_count": rejected, "rejection_rate": rejection_rate,
            "average_prices": average_prices, "monthly": monthly,
            "payments_rub": None, "totals": aggregate, "orders": rows,
            "group_orders_count": len(group_orders), "group_orders": group_orders,
            "explanation": "Когорта — заказы, созданные в период (даты UTC включительно: начало 00:00, конец 23:59:59); исполнение — текущее состояние этих заказов на момент построения отчёта. Принятый сегодня заказ прошлого периода остаётся в прошлом периоде. Групповые обязательства показаны отдельно: их сумма не включена в выручку до учёта исполнения, групповой заказ не удваивает оборот. Выручка от товаров учитывает приёмку минус подтверждённые возвраты, без доставки. Себестоимость относится на принятое количество; прочие прямые затраты относятся на заказ целиком. Прибыль — на налоговой базе из карточки затрат продавца (unknown — база не подтверждена, сравнение условно); платежи не подключены, чистая прибыль не выводится. Отказы — когорта предложений, созданных в период: известны решения (отклонено/выбрано), открытые и истекшие показаны отдельно. Количества сравниваются внутри заказа; средние цены — только в одинаковых единицах."}


def _report_csv(report: dict) -> str:
    role = report["role"]
    header = ["Тип заказа", "Заказ", "Категория", "Единица измерения", "Создан (UTC)", "Статус", "Заказано", "Принято", "Возвращено", "Отменено", "Ожидается", "Цена за единицу, ₽", "Сумма заказа, ₽", "Товары после возвратов, ₽"]
    if role == "seller":
        header += ["Себестоимость принятых товаров, ₽", "Валовая прибыль, ₽", "Прочие затраты, ₽", "Результат после затрат, ₽"]
    lines = [header]
    for row in report["orders"]:
        values: list = ["Прямой", row["deal_id"], row["category"], row["unit"], row["created_at"], row["status"],
                        row["ordered_units"], row["accepted_units"], row["returned_units"], row["cancelled_units"],
                        row["open_units"], row["unit_price_rub"], row["ordered_value_rub"], row["net_goods_revenue_rub"]]
        if role == "seller":
            values += [row.get("cost_of_goods_rub"), row.get("gross_profit_rub"),
                       row.get("attributable_expenses_rub"), row.get("contribution_rub")]
        lines.append(values)
    for row in report["group_orders"]:
        values = ["Групповой", row["order_id"], row["category"], row["unit"], row["created_at"], row["status"],
                  row["units"], None, None, None, None, None, row["contract_value_rub"], None]
        if role == "seller":
            values += [None, None, None, None]
        lines.append(values)
    totals = report["totals"]
    total_row: list = ["Итого по отчёту", None, None, None, None, None, None, None, None, None, None, None,
                       totals.get("ordered_value_rub"), totals.get("net_goods_revenue_rub")]
    if role == "seller":
        total_row += [totals.get("cost_of_goods_rub"), totals.get("gross_profit_rub"),
                      totals.get("attributable_expenses_rub"), totals.get("contribution_rub")]
    lines.append(total_row)
    filters = report["filters"]
    lines.append(["Отчёт сформирован (UTC)", report["built_at"]] + [None] * (len(header) - 2))
    lines.append([f"Период и фильтры: с {filters['start']} по {filters['end']}; категория: {filters['category']}; "
                  f"статус: {filters['status']}; контрагент: {filters['counterparty']}; товар: {filters['product']}; "
                  f"источник: {filters['source']}"] + [None] * (len(header) - 1))
    return "\r\n".join(",".join(_csv_cell(v) for v in row) for row in lines)


@router.get("/companies/{company_id}/commercial-analytics")
async def analytics(company_id: uuid.UUID, role: Literal["buyer", "seller"], start: date | None = None, end: date | None = None,
                    category: str | None = None, status: str | None = None, counterparty: str | None = None,
                    product: str | None = None, source: Literal["all", "direct", "group"] = "all",
                    user: CurrentUser = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    await (require_company_seller if role == "seller" else require_company_buyer)(company_id, user, db)
    return await _commercial_report(db, company_id, role, start=start, end=end, category=category,
                                    status=status, counterparty=counterparty, product=product, source=source)


@router.get("/companies/{company_id}/commercial-report.csv")
async def analytics_csv(company_id: uuid.UUID, role: Literal["buyer", "seller"], start: date | None = None, end: date | None = None,
                        category: str | None = None, status: str | None = None, counterparty: str | None = None,
                        product: str | None = None, source: Literal["all", "direct", "group"] = "all",
                        user: CurrentUser = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """Выгрузка использует те же данные, фильтры и определения, что экран; права проверяются при каждом запросе."""
    from fastapi.responses import PlainTextResponse
    await (require_company_seller if role == "seller" else require_company_buyer)(company_id, user, db)
    report = await _commercial_report(db, company_id, role, start=start, end=end, category=category,
                                      status=status, counterparty=counterparty, product=product, source=source)
    stamp = (report["filters"]["start"] or "all") + "_" + (report["filters"]["end"] or "all")
    return PlainTextResponse("\ufeff" + _report_csv(report), media_type="text/csv; charset=utf-8",
                             headers={"Content-Disposition": f"attachment; filename=porukam-{role}-{stamp}.csv"})
