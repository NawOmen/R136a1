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
from ..models import DealCostVersion, CommercialReportSnapshot, Deal, DealCheckpoint, DealCostSnapshot, DealExecutionEvent, DeliveryArrangement, HumanApprovalRecord, Need, Offer, ParticipantOrder, ResourceReservation
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
    effective_from: datetime | None = None


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
    membership = await require_membership(company_id, user, db)
    if company_id == deal.seller_company_id and membership["can_sell"]:
        costs = await db.get(DealCostSnapshot, deal.id)
        result["financials"] = financials(deal, totals, costs)
        result["cost_revision"] = costs.revision if costs else 0
        result["cost_tax_basis"] = costs.tax_basis if costs else "unknown"
        result["cost_updated_at"] = costs.updated_at if costs else None
        result["unit_cost_rub"] = costs.unit_cost_rub if costs else None
        result["cost_note"] = costs.note if costs else ""
        versions = (await db.scalars(select(DealCostVersion).where(DealCostVersion.deal_id == deal.id).order_by(DealCostVersion.revision))).all()
        result["cost_history"] = [{"revision": c.revision, "unit_cost_rub": c.unit_cost_rub,
            "attributable_expenses_rub": c.attributable_expenses_rub, "tax_basis": c.tax_basis,
            "source": c.note, "effective_from": c.effective_from, "recorded_at": c.recorded_at,
            "legacy_history_unknown": c.legacy_history_unknown} for c in versions]
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
    await require_company_seller(data.company_id, user, db)
    costs = await db.get(DealCostSnapshot, deal.id)
    revision = costs.revision if costs else 0
    if data.expected_revision != revision:
        raise HTTPException(409, "Расходы уже изменены. Обновите данные перед сохранением")
    now = datetime.now(timezone.utc)
    effective = data.effective_from or now
    if effective.tzinfo is None or effective > now or effective < deal.created_at:
        raise HTTPException(422, "Начало действия затрат: дата UTC между созданием сделки и текущим временем")
    if costs and not await db.get(DealCostVersion, (deal.id, revision)):
        db.add(DealCostVersion(deal_id=deal.id, revision=revision, unit_cost_rub=costs.unit_cost_rub,
            attributable_expenses_rub=costs.attributable_expenses_rub, tax_basis=costs.tax_basis,
            note=costs.note, effective_from=costs.updated_at, recorded_at=costs.updated_at,
            updated_by_user_id=costs.updated_by_user_id, legacy_history_unknown=True))
    if costs is None:
        costs = DealCostSnapshot(deal_id=deal.id)
        db.add(costs)
    costs.unit_cost_rub, costs.attributable_expenses_rub = data.unit_cost_rub, data.attributable_expenses_rub
    costs.tax_basis = data.tax_basis
    costs.revision, costs.note, costs.updated_by_user_id = revision + 1, data.note, user.id
    db.add(DealCostVersion(deal_id=deal.id, revision=costs.revision, unit_cost_rub=data.unit_cost_rub,
        attributable_expenses_rub=data.attributable_expenses_rub, tax_basis=data.tax_basis, note=data.note,
        effective_from=effective, recorded_at=now, updated_by_user_id=user.id, legacy_history_unknown=False))
    # Public deal audit contains only revision, never seller-private amounts.
    await audit(db, deal, data.company_id, user, "update_cost_snapshot", {"cost_revision": costs.revision})
    await db.commit()
    return {"revision": costs.revision}


def _csv_cell(value) -> str:
    text_value = "Нет данных" if value is None else str(value)
    if text_value[:1] in ("=", "+", "-", "@") or (text_value[:1].isspace() and text_value.lstrip()[:1] in ("=", "+", "-", "@")):
        text_value = "'" + text_value
    return '"' + text_value.replace('"', '""') + '"'


from ..analytics import commercial_report as _commercial_report


def _report_csv(report: dict) -> str:
    from ..report_labels import display, label
    role = report["role"]
    header = ["Тип заказа", "Заказ", "Категория", "Единица измерения", "Создан (всемирное время)", "Статус", "Заказано", "Принято", "Возвращено", "Отменено", "Ожидается", "Цена за единицу, ₽", "Сумма заказа, ₽", "Товары после возвратов, ₽"]
    if role == "seller":
        header += ["Себестоимость принятых товаров, ₽", "Валовая прибыль, ₽", "Прочие затраты, ₽", "Результат после затрат, ₽"]
    lines = [header]
    for row in report["orders"]:
        values: list = ["Прямой", row["deal_id"], row["category"], row["unit"], row["created_at"], label(row["status"]),
                        row["ordered_units"], row["accepted_units"], row["returned_units"], row["cancelled_units"],
                        row["open_units"], row["unit_price_rub"], row["ordered_value_rub"], row["net_goods_revenue_rub"]]
        if role == "seller":
            values += [row.get("cost_of_goods_rub"), row.get("gross_profit_rub"),
                       row.get("attributable_expenses_rub"), row.get("contribution_rub")]
        lines.append(values)
    for row in report["group_orders"]:
        values = ["Групповой", row["order_id"], row["category"], row["unit"], row["created_at"], label(row["status"]),
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
    lines.append(["Отчёт сформирован (всемирное время)", report["built_at"]] + [None] * (len(header) - 2))
    lines.append([f"Период и фильтры: с {filters['start']} по {filters['end']}; категория: {filters['category']}; "
                  f"статус: {display(filters['status'])}; контрагент: {filters['counterparty']}; товар: {filters['product']}; "
                  f"источник: {display(filters['source'])}"] + [None] * (len(header) - 1))
    detail_keys = ["cohort_key", "product_name", "delivery_price_rub", "discount_rub", "charge_lines",
                   "estimate_complete", "source_refs", "events", "missing"]
    if role == "seller": detail_keys += ["cost_revision", "cost_effective_from", "cost_source", "cost_tax_basis", "profit_missing_reason", "cost_history"]
    lines.append(["Детализация", "Заказ", "Поле", "Значение"])
    for row in report["orders"] + report["group_orders"]:
        for key in detail_keys:
            value = row.get(key)
            lines.append(["Детализация", row.get("deal_id", row.get("order_id")), label(key), display(value)])
    for event in report.get("period_events", []):
        lines.append(["Событие периода", event["deal_id"], event["event_id"], display(event)])
    lines.append(["Снимок отчёта", report.get("report_id"), "Исторический пересчёт", display(report.get("historical_recalculated"))])
    return "\r\n".join(",".join(_csv_cell(v) for v in row) for row in lines)


@router.get("/companies/{company_id}/commercial-analytics")
async def analytics(company_id: uuid.UUID, role: Literal["buyer", "seller"], start: date | None = None, end: date | None = None,
                    category: str | None = None, status: str | None = None, counterparty: str | None = None,
                    product: str | None = None, source: Literal["all", "direct", "group"] = "all",
                    user: CurrentUser = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    # A report spans several tables: freeze one database snapshot for every row.
    await db.rollback()
    await db.connection(execution_options={"isolation_level": "REPEATABLE READ"})
    await (require_company_seller if role == "seller" else require_company_buyer)(company_id, user, db)
    import hashlib, json
    report = await _commercial_report(db, company_id, role, start=start, end=end, category=category,
                                     status=status, counterparty=counterparty, product=product, source=source)
    report["report_id"] = str(uuid.uuid4())
    from ..money import exact_json
    payload = json.loads(json.dumps(exact_json(report), default=lambda v: v.isoformat() if isinstance(v, (date, datetime)) else str(v), ensure_ascii=False))
    digest = hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()
    db.add(CommercialReportSnapshot(id=uuid.UUID(report["report_id"]), user_id=user.id, company_id=company_id,
        role=role, built_at=report["built_at"], payload=payload, payload_hash=digest))
    await db.commit()
    return report


@router.get("/companies/{company_id}/commercial-report.csv")
async def analytics_csv(company_id: uuid.UUID, role: Literal["buyer", "seller"], start: date | None = None, end: date | None = None,
                        category: str | None = None, status: str | None = None, counterparty: str | None = None,
                        product: str | None = None, source: Literal["all", "direct", "group"] = "all",
                        report_id: uuid.UUID | None = None,
                        user: CurrentUser = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """Выгрузка использует те же данные, фильтры и определения, что экран; права проверяются при каждом запросе."""
    from fastapi.responses import PlainTextResponse
    # A report spans several tables: freeze one database snapshot for every row.
    await db.rollback()
    await db.connection(execution_options={"isolation_level": "REPEATABLE READ"})
    await (require_company_seller if role == "seller" else require_company_buyer)(company_id, user, db)
    if report_id:
        snapshot = await db.get(CommercialReportSnapshot, report_id)
        if not snapshot or (snapshot.user_id, snapshot.company_id, snapshot.role) != (user.id, company_id, role):
            raise HTTPException(404, "Снимок отчёта не найден")
        expected = {"start": start.isoformat() if start else None, "end": end.isoformat() if end else None,
                    "category": category or None, "status": status or None, "counterparty": counterparty or None,
                    "product": product or None, "source": source}
        if snapshot.payload["filters"] != expected:
            raise HTTPException(409, "Фильтры не совпадают со снимком отчёта. Обновите экран")
        import hashlib, json
        actual_hash = hashlib.sha256(json.dumps(snapshot.payload, sort_keys=True).encode()).hexdigest()
        if actual_hash != snapshot.payload_hash:
            raise HTTPException(409, "Снимок отчёта повреждён. Постройте новый отчёт")
        report = snapshot.payload
    else:
        report = await _commercial_report(db, company_id, role, start=start, end=end, category=category,
                                          status=status, counterparty=counterparty, product=product, source=source)
    stamp = (report["filters"]["start"] or "all") + "_" + (report["filters"]["end"] or "all")
    return PlainTextResponse("\ufeff" + _report_csv(report), media_type="text/csv; charset=utf-8",
                             headers={"Content-Disposition": f"attachment; filename=porukam-{role}-{stamp}.csv"})
