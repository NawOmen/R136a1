"""Versioned, bilateral fulfillment. No arbitration, payments or external LLM."""
import copy
import hashlib
import uuid
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Literal

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, Response
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool

from .. import storage
from ..commerce import execution_totals
from ..database import get_db
from ..deps import CurrentUser, get_current_user, notify, require_company_admin
from ..experience import classify_cargo
from ..models import DealAttachment, DealFulfillment, DealExecutionEvent, DeliveryArrangement, DeliveryAddress, Need, ResourceReservation, DealCheckpoint, DealMessage
from ..money import Amount
from ..resources import consume, release, return_stock
from ..resilience_execution import require_shipment_allowed
from ..trust import payload_hash
from .commerce import party, events_for, audit, shipping_totals
from .stage9 import _ensure_checkpoints

router = APIRouter(tags=["fulfillment"])


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class Command(Strict):
    company_id: uuid.UUID
    expected_revision: int = Field(ge=0)
    terms_version: int = Field(ge=1)
    idempotency_key: uuid.UUID
    human_approved: Literal[True]
    action: Literal["prepare", "production", "logistics", "shipment", "receipt", "inspection", "dispute_response", "dispute_decision", "request", "decision", "return_complete", "complete", "message", "proposal", "proposal_decision"]
    payload: dict


class Evidence(Strict):
    note: str = Field(min_length=3, max_length=1000)
    attachments: list[uuid.UUID] = Field(default_factory=list, max_length=10)


class Step(Evidence):
    expected_date: date


class Dispatch(Step):
    address: str = Field(min_length=5, max_length=500)
    city: str = Field(min_length=2, max_length=120)
    region: str = Field(min_length=2, max_length=120)
    country: Literal["RU"] = "RU"
    packaging: str = Field(min_length=2, max_length=500)
    weight_kg: float = Field(gt=0, le=1e9, allow_inf_nan=False)
    volume_m3: float = Field(gt=0, le=1e9, allow_inf_nan=False)
    places: int = Field(gt=0, le=1000000)
    restrictions: str = Field(default="", max_length=1000)
    hazard_class: Literal["1", "2", "3", "4", "5", "6", "7", "8", "9"] | None = None


class Logistics(Step):
    method: Literal["self_pickup", "buyer_carrier", "seller_delivery"]
    carrier: str = Field(default="", max_length=255)
    cost_rub: Amount | None = Field(default=None, ge=0)
    manual_confirmation: bool = False


class Shipment(Step):
    batch: str = Field(min_length=1, max_length=120)
    units: int = Field(gt=0)


class Receipt(Step):
    batch_id: uuid.UUID
    line_id: uuid.UUID
    received: int = Field(ge=0)
    missing: int = Field(ge=0)


class Inspection(Step):
    batch_id: uuid.UUID
    line_id: uuid.UUID
    accepted: int = Field(ge=0)
    rejected: int = Field(ge=0)


class DisputeResponse(Evidence):
    dispute_id: uuid.UUID
    resolution: Literal["accept", "credit"]


class DisputeDecision(Evidence):
    dispute_id: uuid.UUID
    approved: bool


class Request(Evidence):
    kind: Literal["return", "cancellation"]
    units: int = Field(gt=0)


class Decision(Evidence):
    event_id: uuid.UUID
    approved: bool


class ReturnComplete(Evidence):
    event_id: uuid.UUID
    restock_accepted: bool = False


class Message(Evidence):
    pass


class Proposal(Logistics):
    pass


class ProposalDecision(Evidence):
    proposal_id: uuid.UUID
    approved: bool


MODELS = {"prepare": Dispatch, "production": Step, "logistics": Logistics, "shipment": Shipment,
          "receipt": Receipt, "inspection": Inspection, "dispute_response": DisputeResponse, "dispute_decision": DisputeDecision,
          "request": Request, "decision": Decision, "return_complete": ReturnComplete, "complete": Step,
          "message": Message, "proposal": Proposal, "proposal_decision": ProposalDecision}


def now():
    return datetime.now(timezone.utc).isoformat()


def fail(message):
    raise HTTPException(409, message)


def role(deal, company, buyer=False):
    if company != (deal.buyer_company_id if buyer else deal.seller_company_id):
        raise HTTPException(403, "Действие подтверждает покупатель" if buyer else "Действие подтверждает продавец")


async def initial(db, deal):
    events = await events_for(db, deal.id)
    totals = execution_totals(deal, events)
    checkpoints = list((await db.scalars(select(DealCheckpoint).where(DealCheckpoint.deal_id == deal.id))).all())
    shipped = (await shipping_totals(db, deal, events))["shipped_units"]
    stages = {c.kind: {"actual_date": c.completed_at.isoformat() if c.completed_at else None,
              "expected_date": None, "note": c.note or "Подтверждено ранее", "attachments": []}
              for c in checkpoints if c.status == "completed"}
    if "production" in stages:
        stages["prepare"] = {**stages["production"], "note": "Историческое исполнение до учёта партий"}
    batches = []
    if shipped:
        batches.append({"id": str(uuid.uuid5(deal.id, "historical-shipment")), "batch": "Ранее отгружено",
                        "line_id": str(deal.need_id), "units": shipped, "inspected": totals["accepted_units"],
                        "received": shipped if "delivery" in stages else totals["accepted_units"], "accepted": totals["accepted_units"], "rejected": 0, "missing": 0,
                        "actual_date": stages.get("shipment", {}).get("actual_date"), "expected_date": None,
                        "note": "Историческая отгрузка", "attachments": []})
    need = await db.get(Need, deal.need_id)
    address = await db.get(DeliveryAddress, need.delivery_address_id) if need and need.delivery_address_id else None
    arrangement = await db.scalar(select(DeliveryArrangement).where(DeliveryArrangement.deal_id == deal.id))
    logistics = None
    if arrangement:
        logistics = {"method": arrangement.method, "carrier": arrangement.carrier_name or "", "cost_rub": str(deal.delivery_price_rub) if deal.delivery_price_rub is not None else None,
                     "expected_date": need.deadline_date.isoformat() if need else None, "note": "Ранее согласовано",
                     "attachments": [], "confirmed": arrangement.method != "seller_delivery", "manual_confirmation": False}
    messages = list((await db.scalars(select(DealMessage).where(DealMessage.deal_id == deal.id).order_by(DealMessage.created_at, DealMessage.id))).all())
    historical_messages = [{"id": str(m.id), "company_id": str(m.author_company_id), "terms_version": 1,
        "actual_date": m.created_at.isoformat(), "note": m.message, "attachments": []} for m in messages]
    return {"terms_version": 1, "dispatch": None, "destination": address.address if address else None,
            "stages": stages, "batches": batches, "disputes": [], "requests": [{"id": str(e.id), "kind": e.kind, "units": e.units,
            "status": e.status, "company_id": str(e.actor_company_id), "note": e.note,
            "terms_version": 1, "attachments": [], "actual_date": e.created_at.isoformat()}
            for e in events if e.kind in {"return", "cancellation"}], "messages": historical_messages, "proposals": [],
            "logistics": logistics, "terms_history": [], "operations": {}, "history": [{**step, "id": str(uuid.uuid5(deal.id, "legacy-" + kind)),
                "company_id": str(deal.buyer_company_id if kind == "delivery" else deal.seller_company_id),
                "terms_version": 1, "action": "receipt" if kind == "delivery" else kind}
                for kind, step in stages.items()], "completed": False}


def unshipped(deal, state, totals):
    credited = sum(d["units"] for d in state["disputes"] if d.get("resolution") == "credit" and d["status"] == "closed")
    return max(0, deal.units - totals["cancelled_units"] + credited - sum(b["units"] for b in state["batches"]))


async def projection(db, deal, state, revision):
    totals = execution_totals(deal, await events_for(db, deal.id))
    return {"deal_id": str(deal.id), "line_id": str(deal.need_id), "revision": revision,
            "commercial": {"seller_total_rub": str(deal.total_price_rub), "seller_delivery_rub": str(deal.delivery_price_rub) if deal.delivery_price_rub is not None else None,
             "external_carrier_rub": None if not state["logistics"] else state["logistics"]["cost_rub"] if state["logistics"]["method"] != "seller_delivery" else "0.00",
             "original_snapshot": deal.commercial_snapshot},
            "status": deal.status, "totals": {**totals, "shipped_units": sum(b["units"] for b in state["batches"]),
             "unshipped_units": unshipped(deal, state, totals), "received_units": sum(b["received"] for b in state["batches"])}, **{k: v for k, v in state.items() if k != "operations"},
            "rating_rule": "Отзывы компаний по подтверждённым сделкам; один отзыв от компании на сделку, после получения и приёмки, без полного возврата. Средняя оценка и число отзывов открыты в профиле."}


@router.get("/deals/{deal_id}/fulfillment")
async def get_fulfillment(deal_id: uuid.UUID, company_id: uuid.UUID, user: CurrentUser = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    deal = await party(db, deal_id, company_id, user, lock=True)
    row = await db.get(DealFulfillment, deal.id)
    return await projection(db, deal, row.data if row else await initial(db, deal), row.revision if row else 0)


async def attachments_guard(db, deal, company, version, ids):
    for attachment_id in ids:
        item = await db.get(DealAttachment, attachment_id)
        if not item or item.deal_id != deal.id or item.company_id != company or item.terms_version != version:
            raise HTTPException(404, "Материал не относится к этой компании, сделке и версии")


async def event(db, deal, user, command, kind, units, note, status="confirmed"):
    item = DealExecutionEvent(deal_id=deal.id, actor_company_id=command.company_id, actor_user_id=user.id,
        idempotency_key=command.idempotency_key, kind=kind, units=units, note=note, status=status)
    if status == "confirmed":
        item.decided_by_user_id, item.decided_at = user.id, datetime.now(timezone.utc)
    db.add(item)
    await db.flush()
    return item


def find(items, ident):
    result = next((i for i in items if i["id"] == str(ident)), None)
    if not result:
        raise HTTPException(404, "Запись не найдена в выбранной сделке")
    return result


async def put_arrangement(db, deal, user, state):
    dispatch, value = state["dispatch"], state["logistics"]
    if not dispatch or not value:
        return
    item = await db.scalar(select(DeliveryArrangement).where(DeliveryArrangement.deal_id == deal.id))
    if not item:
        item = DeliveryArrangement(deal_id=deal.id)
        db.add(item)
    item.weight_kg, item.volume_m3, item.hazard_class = dispatch["weight_kg"], dispatch["volume_m3"], dispatch["hazard_class"]
    item.cargo_class, item.classification_note = classify_cargo(item.weight_kg, item.volume_m3, item.hazard_class)
    item.method, item.carrier_name = value["method"], value["carrier"] or None
    item.buyer_responsible, item.confirmed_by_user_id = value["method"] != "seller_delivery", user.id


async def validate_logistics(db, deal, state, value):
    if value.method == "buyer_carrier" and not value.carrier:
        fail("Укажите перевозчика покупателя")
    if value.cost_rub is None:
        fail("Тариф неизвестен: укажите стоимость в рублях до согласования")
    need = await db.get(Need, deal.need_id)
    total = deal.total_price_rub - (deal.delivery_price_rub or Decimal(0)) + value.cost_rub
    if need.budget_rub is not None and total > need.budget_rub:
        fail("Смета с перевозкой превышает согласованный бюджет")
    if value.expected_date > need.deadline_date:
        fail("Срок получения выходит за согласованный срок потребности")
    dispatch = state["dispatch"]
    if not dispatch:
        fail("Сначала продавец подтверждает параметры отгрузки")
    classification = classify_cargo(dispatch["weight_kg"], dispatch["volume_m3"], dispatch["hazard_class"])[0]
    if (classification in {"manual_review", "large"} or 12 < dispatch["volume_m3"] < 15) and not value.manual_confirmation:
        fail("Ограничения груза требуют ручного уточнения условий перевозки")


@router.post("/deals/{deal_id}/fulfillment")
async def command(deal_id: uuid.UUID, data: Command, user: CurrentUser = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    try:
        value = MODELS[data.action].model_validate(data.payload)
    except ValidationError as exc:
        raise HTTPException(422, exc.errors(include_context=False))
    deal = await party(db, deal_id, data.company_id, user, lock=True)
    if data.action != "message":
        await require_company_admin(data.company_id, user, db)
    row = await db.get(DealFulfillment, deal.id)
    state = copy.deepcopy(row.data) if row else await initial(db, deal)
    revision = row.revision if row else 0
    key = f"{data.company_id}:{data.idempotency_key}"
    digest = payload_hash(data.model_dump(mode="json"))
    if key in state["operations"]:
        if state["operations"][key] != digest:
            fail("Ключ операции уже использован для других данных")
        return await projection(db, deal, state, revision)
    if data.expected_revision != revision or data.terms_version != state["terms_version"]:
        fail("Сделка изменилась. Обновите данные перед подтверждением")
    await attachments_guard(db, deal, data.company_id, data.terms_version, value.attachments)
    payload = value.model_dump(mode="json")
    record = {"id": str(uuid.uuid4()), "company_id": str(data.company_id), "terms_version": state["terms_version"],
              "actual_date": now(), **payload}
    events = await events_for(db, deal.id)
    totals = execution_totals(deal, events)
    if deal.status == "cancelled" and data.action not in {"complete", "message"}:
        fail("Заказ отменён; доступны завершение и переписка")
    if state["completed"] and data.action not in {"message", "request", "decision", "return_complete"}:
        fail("Исполнение завершено; доступны переписка и возврат")
    if data.action == "prepare":
        role(deal, data.company_id)
        if state["dispatch"]:
            fail("Параметры подготовки уже зафиксированы")
        record["cargo_class"], record["classification_note"] = classify_cargo(value.weight_kg, value.volume_m3, value.hazard_class)
        state["dispatch"] = record
        state["stages"]["prepare"] = record
    elif data.action == "production":
        role(deal, data.company_id)
        if "prepare" not in state["stages"] or "production" in state["stages"]:
            fail("Подтвердите подготовку; повторное производство недопустимо")
        state["stages"]["production"] = record
    elif data.action == "logistics":
        role(deal, data.company_id, buyer=True)
        if state["logistics"]:
            fail("Получение уже согласовано. Создайте предложение изменения")
        await validate_logistics(db, deal, state, value)
        record["confirmed"] = value.method != "seller_delivery" and not deal.delivery_price_rub
        state["logistics"] = record
        # Seller delivery is accepted only through a bilateral proposal.
        if not record["confirmed"]:
            state["proposals"].append({**record, "status": "pending", "kind": "logistics"})
        else:
            state["terms_history"].append({"version": state["terms_version"], "logistics": copy.deepcopy(record)})
        await put_arrangement(db, deal, user, state)
    elif data.action == "shipment":
        role(deal, data.company_id)
        await require_shipment_allowed(db, deal)
        if "production" not in state["stages"] or not state["logistics"] or not state["logistics"]["confirmed"]:
            fail("Подтвердите производство и согласуйте получение с известным тарифом")
        if value.units > unshipped(deal, state, totals):
            fail("Отгрузка превышает неотгруженный остаток")
        await consume(db, company_id=deal.seller_company_id, anchor_type="deal", anchor_id=deal.id, units=value.units)
        item = await event(db, deal, user, data, "shipment", value.units, value.note)
        state["batches"].append({**record, "id": str(item.id), "line_id": str(deal.need_id), "received": 0, "inspected": 0, "accepted": 0, "rejected": 0, "missing": 0})
        state["stages"]["shipment"] = record
    elif data.action in {"receipt", "inspection"}:
        role(deal, data.company_id, buyer=True)
        if not state["logistics"] or not state["logistics"]["confirmed"]:
            fail("Сначала согласуйте способ получения")
        batch = find(state["batches"], value.batch_id)
        if value.line_id != deal.need_id:
            fail("Строка не относится к выбранной партии")
        if data.action == "receipt":
            count = value.received + value.missing
            if count <= 0 or count > batch["units"] - batch["received"] - batch["missing"]:
                fail("Получение превышает неучтённое количество партии")
            batch["received"] += value.received
            batch["missing"] += value.missing
            disputed, rejected, missing = value.missing, 0, value.missing
        else:
            count = value.accepted + value.rejected
            if count <= 0 or count > batch["received"] - batch["inspected"]:
                fail("Проверка превышает полученное непроверенное количество")
            if value.accepted:
                await event(db, deal, user, data, "acceptance", value.accepted, value.note)
            batch["accepted"] += value.accepted
            batch["rejected"] += value.rejected
            batch["inspected"] += count
            disputed, rejected, missing = value.rejected, value.rejected, 0
        state["stages"][data.action] = record
        if disputed:
            state["disputes"].append({**record, "batch_id": batch["id"], "line_id": str(deal.need_id),
                "rejected": rejected, "missing": missing, "units": disputed,
                "status": "open", "responsible_company_id": str(deal.seller_company_id), "responses": []})
    elif data.action == "dispute_response":
        role(deal, data.company_id)
        dispute = find(state["disputes"], value.dispute_id)
        if dispute["status"] not in {"open", "responded"}:
            fail("Расхождение уже закрыто")
        dispute["responses"].append(record)
        dispute["status"] = "responded"
    elif data.action == "dispute_decision":
        role(deal, data.company_id, buyer=True)
        dispute = find(state["disputes"], value.dispute_id)
        if dispute["status"] != "responded":
            fail("Ожидается ответ ответственного продавца")
        if value.approved:
            response = dispute["responses"][-1]
            batch = find(state["batches"], dispute["batch_id"])
            if response["resolution"] == "accept":
                await event(db, deal, user, data, "acceptance", dispute["units"], value.note)
                batch["accepted"] += dispute["units"]
                batch["received"] += dispute["missing"]
                batch["inspected"] += dispute["missing"]
                batch["rejected"] -= dispute["rejected"]
                batch["missing"] -= dispute["missing"]
            else:
                # Physically shipped goods are never released back into available resources.
                await event(db, deal, user, data, "cancellation", dispute["units"], value.note)
            dispute["status"], dispute["decision"] = "closed", record
            dispute["resolution"] = response["resolution"]
        else:
            dispute["status"] = "open"
            dispute.setdefault("decisions", []).append(record)
    elif data.action == "request":
        if value.kind == "return":
            role(deal, data.company_id, buyer=True)
        reserved = sum(e.units for e in events if e.kind == value.kind and e.status in {"pending", "approved"})
        limit = totals["net_units"] if value.kind == "return" else unshipped(deal, state, totals)
        if value.units > limit - reserved:
            fail("Запрос превышает доступный остаток с учётом открытых запросов")
        item = await event(db, deal, user, data, value.kind, value.units, value.note, "pending")
        state["requests"].append({**record, "id": str(item.id), "status": "pending"})
    elif data.action in {"decision", "return_complete"}:
        request = find(state["requests"], value.event_id)
        item = next((e for e in events if str(e.id) == request["id"]), None)
        if not item:
            fail("Исторический запрос необходимо завершить до перехода к учёту партий")
        if item.actor_company_id == data.company_id:
            raise HTTPException(403, "Запрос подтверждает другая сторона")
        if data.action == "decision":
            if item.status != "pending":
                fail("Решение уже принято")
            if value.approved:
                limit = totals["net_units"] if item.kind == "return" else unshipped(deal, state, totals)
                if item.units > limit:
                    fail("Объём исполнения изменился: согласование невозможно")
                item.status = "approved" if item.kind == "return" else "confirmed"
                if item.kind == "cancellation":
                    await release(db, company_id=deal.seller_company_id, anchor_type="deal", anchor_id=deal.id, units=item.units)
            else:
                item.status = "rejected"
            request["decision"] = record
        else:
            role(deal, data.company_id)
            if item.kind != "return" or item.status != "approved" or item.units > totals["net_units"]:
                fail("Возврат должен быть согласован и ещё не завершён")
            item.status = "confirmed"
            await db.flush()
            if value.restock_accepted:
                product = await db.scalar(select(ResourceReservation.product_id).where(ResourceReservation.anchor_type == "deal",
                    ResourceReservation.anchor_id == deal.id, ResourceReservation.company_id == deal.seller_company_id,
                    ResourceReservation.product_id.is_not(None)))
                if not product:
                    fail("Для сделки нет складского товара; возврат на доступный склад неприменим")
                await return_stock(db, company_id=deal.seller_company_id, product_id=product, units=item.units,
                    quality_accepted=True, return_event_id=item.id, actor_user_id=user.id)
            item.status = "confirmed"
            request["completion"] = record
        item.decided_by_user_id, item.decided_at = user.id, datetime.now(timezone.utc)
        request["status"] = item.status
    elif data.action == "complete":
        role(deal, data.company_id, buyer=True)
        if totals["open_units"] or any(d["status"] != "closed" for d in state["disputes"]) or any(r["status"] in {"pending", "approved"} for r in state["requests"]):
            fail("Остались непроверенные количества, расхождения или открытые запросы")
        if totals["accepted_units"] and "inspection" not in state["stages"] and "delivery" not in state["stages"]:
            fail("Сначала подтвердите проверку полученных партий")
        state["completed"] = True
        state["stages"]["completion"] = record
    elif data.action == "message":
        state["messages"].append(record)
    elif data.action == "proposal":
        if any(p["status"] == "pending" for p in state["proposals"]):
            fail("Сначала примите решение по открытому предложению")
        if state["batches"]:
            fail("Условия получения фиксированы после отгрузки; обсудите исключение в переписке")
        await validate_logistics(db, deal, state, value)
        state["proposals"].append({**record, "status": "pending", "kind": "logistics"})
    elif data.action == "proposal_decision":
        proposal = find(state["proposals"], value.proposal_id)
        if proposal["company_id"] == str(data.company_id):
            raise HTTPException(403, "Изменение согласовывает другая сторона")
        if proposal["status"] != "pending" or proposal["terms_version"] != state["terms_version"] or state["batches"]:
            fail("Предложение устарело или исполнение уже начато")
        proposal["status"] = "approved" if value.approved else "rejected"
        proposal["decision"] = record
        if value.approved:
            state["terms_history"].append({"version": state["terms_version"], "logistics": copy.deepcopy(state["logistics"])})
            state["terms_version"] += 1
            state["logistics"] = {**proposal, "confirmed": True, "terms_version": state["terms_version"]}
            need = await db.get(Need, deal.need_id)
            if date.fromisoformat(proposal["expected_date"]) > need.deadline_date:
                fail("Новый срок выходит за согласованный срок потребности")
            seller_delivery = Decimal(str(proposal["cost_rub"])) if proposal["method"] == "seller_delivery" else Decimal(0)
            if deal.resilience_plan_id and seller_delivery != (deal.delivery_price_rub or Decimal(0)):
                fail("Изменение доставки меняет общую смету плана резерва. Требуется перерасчёт и новое согласование плана")
            new_total = deal.total_price_rub - (deal.delivery_price_rub or Decimal(0)) + seller_delivery
            if need.budget_rub is not None and new_total > need.budget_rub:
                fail("Смета с новой доставкой превышает согласованный бюджет")
            state["terms_history"][-1]["seller_total_rub"] = str(deal.total_price_rub)
            state["terms_history"][-1]["seller_delivery_rub"] = str(deal.delivery_price_rub) if deal.delivery_price_rub is not None else None
            deal.delivery_price_rub, deal.total_price_rub = seller_delivery, new_total
            await put_arrangement(db, deal, user, state)
    state["operations"][key] = digest
    state["history"].append({**record, "action": data.action})
    # A single projection updates both checkpoints and Deal.status in the same transaction.
    await db.flush()
    current_events = await events_for(db, deal.id)
    current = execution_totals(deal, current_events)
    shipping = {"shipped_units": sum(b["units"] for b in state["batches"]), "unshipped_units": unshipped(deal, state, current)}
    checkpoints = await _ensure_checkpoints(deal.id, db)
    delivered = bool(current["accepted_units"]) and current["open_units"] == 0 and not any(d["status"] != "closed" for d in state["disputes"])
    for step in checkpoints:
        done = ("production" in state["stages"] if step.kind == "production" else
                shipping["shipped_units"] > 0 and shipping["unshipped_units"] == 0 if step.kind == "shipment" else delivered)
        step.status = "completed" if done else "pending"
        if done and not step.completed_at:
            step.completed_at, step.confirmed_by_user_id = datetime.now(timezone.utc), user.id
    if current["cancelled_units"] == deal.units:
        deal.status = "cancelled"
    elif current["returned_units"] and current["net_units"] == 0 and current["open_units"] == 0:
        deal.status = "returned"
    elif state["completed"]:
        deal.status = "fulfilled"
    elif delivered:
        deal.status = "delivered"
    elif any(d["status"] != "closed" for d in state["disputes"]):
        deal.status = "disputed"
    elif current["accepted_units"]:
        deal.status = "partially_accepted"
    elif shipping["shipped_units"]:
        deal.status = "shipped" if shipping["unshipped_units"] == 0 else "partially_shipped"
    elif "production" in state["stages"]:
        deal.status = "in_production"
    if row is None:
        row = DealFulfillment(deal_id=deal.id, revision=revision + 1, data=state)
        db.add(row)
    else:
        row.revision, row.data = revision + 1, state
    if data.action != "message":
        await audit(db, deal, data.company_id, user, "fulfillment_" + data.action,
                    {"terms_version": data.terms_version, "revision": revision + 1, "record": record})
    other = deal.seller_company_id if data.company_id == deal.buyer_company_id else deal.buyer_company_id
    recipients = (await db.execute(text("SELECT user_id FROM auth.company_members WHERE company_id = :company"), {"company": other})).scalars().all()
    for recipient in set(recipients):
        await notify(db, recipient, f"Обновлено исполнение сделки {deal.id}: {value.note}", "deal_fulfillment_updated", href=f"/deals?deal={deal.id}")
    result = await projection(db, deal, state, revision + 1)
    await db.commit()
    return result


@router.post("/deals/{deal_id}/attachments", status_code=201)
async def upload_attachment(deal_id: uuid.UUID, company_id: uuid.UUID = Form(...), terms_version: int = Form(...),
                            file: UploadFile = File(...), user: CurrentUser = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    deal = await party(db, deal_id, company_id, user, lock=True)
    row = await db.get(DealFulfillment, deal.id)
    if terms_version != (row.data["terms_version"] if row else 1):
        fail("Версия сделки изменилась. Обновите карточку")
    content = await file.read(10 * 1024 * 1024 + 1)
    mime = file.content_type or ""
    signatures = {"application/pdf": b"%PDF-", "image/png": b"\x89PNG\r\n\x1a\n", "image/jpeg": b"\xff\xd8\xff"}
    if not content or len(content) > 10 * 1024 * 1024 or mime not in signatures or not content.startswith(signatures[mime]):
        raise HTTPException(422, "Допустимы PDF, PNG и JPEG до 10 МБ с соответствующим содержимым")
    from ..file_safety import validate_upload
    try:
        await validate_upload(content, file.content_type or "application/octet-stream")
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from None
    item = DealAttachment(id=uuid.uuid4(), deal_id=deal.id, company_id=company_id, terms_version=terms_version,
        filename=(file.filename or "Материал").replace("/", "_").replace("\\", "_")[:255],
        storage_key=f"deal-materials/{deal.id}/{uuid.uuid4()}", content_type=mime, sha256=hashlib.sha256(content).hexdigest())
    await run_in_threadpool(storage.upload_object, item.storage_key, content, mime)
    try:
        db.add(item)
        await db.commit()
    except Exception:
        await run_in_threadpool(storage.delete_object, item.storage_key)
        raise
    return {"id": str(item.id), "filename": item.filename, "terms_version": item.terms_version}


@router.get("/deals/{deal_id}/attachments/{attachment_id}")
async def download_attachment(deal_id: uuid.UUID, attachment_id: uuid.UUID, company_id: uuid.UUID,
                              user: CurrentUser = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    await party(db, deal_id, company_id, user)
    item = await db.get(DealAttachment, attachment_id)
    if not item or item.deal_id != deal_id:
        raise HTTPException(404, "Материал не найден")
    content = await run_in_threadpool(storage.download_object, item.storage_key)
    return Response(content, media_type=item.content_type, headers={"Content-Disposition": "attachment", "X-Content-Type-Options": "nosniff"})
