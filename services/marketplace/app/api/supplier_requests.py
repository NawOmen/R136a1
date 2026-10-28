"""Private supplier board and human-sent conversations, contract supplier-workflow-1."""
import asyncio
import hashlib
import uuid
from datetime import date, datetime, timezone
from typing import Literal
from types import SimpleNamespace
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from .. import storage
from ..category_units import order_unit
from ..database import get_db
from ..deps import CurrentUser, get_current_user, notify, require_company_admin, require_company_buyer, require_company_seller
from ..file_safety import validate_upload
from ..models import Need, Product, SupplierRequest, SupplierRequestMessage, SupplierReplyFile
from ..money import Money, exact_json
from ..trust import record_human_approval

router = APIRouter(tags=["supplier-workflow"])
Status = Literal["draft", "sent", "replied", "selected"]
Basis = Literal["unknown", "unit", "total"]


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid")
    company_id: uuid.UUID


class CreateIn(Input):
    seller_company_id: uuid.UUID
    expected_need_revision: int = Field(ge=1)


class UpdateIn(Input):
    expected_revision: int = Field(ge=1)
    status: Status
    quoted_price_rub: Money | None = Field(default=None, ge=0)
    price_basis: Basis = "unknown"
    lead_time_days: int | None = Field(default=None, ge=0, le=3650)
    delivery_date: date | None = None
    note: str = Field(default="", max_length=2000)
    human_approved: Literal[True]


class MessageIn(Input):
    message: str = Field(min_length=1, max_length=6000)
    request_key: uuid.UUID
    expected_revision: int = Field(ge=1)
    human_approved: Literal[True]

    @field_validator("message")
    @classmethod
    def nonempty(cls, value):
        if not value.strip():
            raise ValueError("Введите сообщение")
        return value.strip()


class RequestOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    contract_version: Literal["supplier-workflow-1"] = "supplier-workflow-1"
    id: uuid.UUID
    need_id: uuid.UUID
    need_revision: int
    buyer_company_id: uuid.UUID
    seller_company_id: uuid.UUID
    buyer_name: str
    seller_name: str
    specification: dict
    status: Status
    revision: int
    quoted_price_rub: Money | None
    price_basis: Basis
    lead_time_days: int | None
    delivery_date: date | None
    note: str
    sent_at: datetime | None
    updated_at: datetime


class MessageOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    author_company_id: uuid.UUID
    message: str
    created_at: datetime


class FileOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    file_name: str
    content_type: str
    content_hash: str
    created_at: datetime


async def buyer_need(db, need_id, company_id, user, *, lock=False):
    await require_company_buyer(company_id, user, db)
    query = select(Need).where(Need.id == need_id, Need.company_id == company_id)
    need = await db.scalar(query.with_for_update() if lock else query)
    if not need:
        raise HTTPException(404, "Потребность не найдена")
    return need


async def party(db, request_id, company_id, user, *, lock=False, buyer_only=False):
    row = await db.get(SupplierRequest, request_id)
    if not row or company_id not in {row.buyer_company_id, row.seller_company_id}:
        raise HTTPException(404, "Запрос поставщику не найден")
    buyer = company_id == row.buyer_company_id
    if not buyer and (buyer_only or row.status == "draft"):
        raise HTTPException(404, "Запрос поставщику не найден")
    await (require_company_buyer if buyer else require_company_seller)(company_id, user, db)
    if lock:
        # Same Need -> Request order as creation and specification edits.
        await db.scalar(select(Need).where(Need.id == row.need_id).with_for_update())
        row = await db.scalar(select(SupplierRequest).where(SupplierRequest.id == row.id)
                              .with_for_update().execution_options(populate_existing=True))
    return row


def visible(row, company_id):
    result = RequestOut.model_validate(row)
    if company_id == row.seller_company_id:
        # Buyer notes, prices from other channels and file analysis remain private.
        result = result.model_copy(update={"note": "", "quoted_price_rub": None, "price_basis": "unknown", "lead_time_days": None, "delivery_date": None})
    return result


async def company(db, company_id):
    value = (await db.execute(text("SELECT id, display_name, country, verification_status FROM auth.companies WHERE id=:id"), {"id": company_id})).mappings().first()
    if not value or value["country"] != "RU":
        raise HTTPException(404, "Российская компания не найдена")
    return value


async def approve(db, row, user, action, payload):
    await record_human_approval(db, action=action, entity_type="supplier_request", entity_id=row.id,
        actor_user_id=user.id, actor_company_id=row.buyer_company_id, permission="can_buy",
        decision="approved", payload=payload, explanation="Пользователь подтвердил действие в работе с поставщиком")


@router.get("/needs/{need_id}/suppliers")
async def suppliers(need_id: uuid.UUID, company_id: uuid.UUID, user: CurrentUser = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    need = await buyer_need(db, need_id, company_id, user)
    rows = (await db.execute(text("SELECT c.id, c.display_name FROM auth.companies c WHERE c.country='RU' AND c.verification_status='verified' AND c.id<>:id AND EXISTS (SELECT 1 FROM auth.company_members m WHERE m.company_id=c.id AND m.can_sell=true) ORDER BY c.display_name LIMIT 200"), {"id": company_id})).mappings().all()
    products = list((await db.scalars(select(Product).where(Product.is_published.is_(True), Product.company_id.in_([r["id"] for r in rows])).order_by(Product.name))).all()) if rows else []
    result = []
    for row in rows:
        catalog = [p for p in products if p.company_id == row["id"]]
        relevant = [p for p in catalog if p.category == need.category and (not need.subcategory or p.subcategory == need.subcategory)]
        result.append({"company_id": row["id"], "company_name": row["display_name"], "relevant": bool(relevant),
                       "specialization": list(dict.fromkeys(p.category for p in catalog))[:10], "products": [p.name for p in (relevant or catalog)[:5]]})
    return sorted(result, key=lambda r: (not r["relevant"], r["company_name"]))


@router.get("/supplier-requests", response_model=list[RequestOut])
async def list_requests(company_id: uuid.UUID, need_id: uuid.UUID | None = None, role: Literal["buyer", "seller"] = "buyer", user: CurrentUser = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    await (require_company_buyer if role == "buyer" else require_company_seller)(company_id, user, db)
    query = select(SupplierRequest).where((SupplierRequest.buyer_company_id if role == "buyer" else SupplierRequest.seller_company_id) == company_id)
    if role == "seller":
        query = query.where(SupplierRequest.status != "draft", SupplierRequest.sent_at.is_not(None))
    if need_id:
        query = query.where(SupplierRequest.need_id == need_id)
    return [visible(row, company_id) for row in (await db.scalars(query.order_by(SupplierRequest.updated_at.desc()).limit(300))).all()]


@router.post("/needs/{need_id}/supplier-requests", response_model=RequestOut, status_code=201)
async def create_request(need_id: uuid.UUID, data: CreateIn, user: CurrentUser = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    need = await buyer_need(db, need_id, data.company_id, user, lock=True)
    await require_company_admin(data.company_id, user, db)
    if need.revision != data.expected_need_revision:
        raise HTTPException(409, "Требования изменились. Обновите потребность")
    if need.status in {"cancelled", "expired", "matched"} or need.deadline_date < date.today():
        raise HTTPException(409, "Потребность закрыта или срок поставки прошёл")
    if data.seller_company_id == data.company_id:
        raise HTTPException(422, "Выберите другую компанию")
    seller = await company(db, data.seller_company_id)
    if seller["verification_status"] != "verified" or not await db.scalar(text("SELECT EXISTS(SELECT 1 FROM auth.company_members WHERE company_id=:id AND can_sell=true)"), {"id": data.seller_company_id}):
        raise HTTPException(409, "Компания недоступна для запросов поставщику")
    existing = await db.scalar(select(SupplierRequest).where(SupplierRequest.need_id == need.id, SupplierRequest.need_revision == need.revision, SupplierRequest.seller_company_id == data.seller_company_id))
    if existing:
        return visible(existing, data.company_id)
    buyer = await company(db, data.company_id)
    # Only the shared specification, never raw sources, budget or private files.
    specification = exact_json({"category": need.category, "subcategory": need.subcategory, "characteristics": need.characteristics,
                                "quantity": need.volume_units, "unit": order_unit(need.characteristics), "deadline_date": need.deadline_date.isoformat()})
    row = SupplierRequest(need_id=need.id, need_revision=need.revision, buyer_company_id=data.company_id,
        seller_company_id=data.seller_company_id, buyer_name=buyer["display_name"], seller_name=seller["display_name"], specification=specification)
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return visible(row, data.company_id)


@router.patch("/supplier-requests/{request_id}", response_model=RequestOut)
async def update_request(request_id: uuid.UUID, data: UpdateIn, user: CurrentUser = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    row = await party(db, request_id, data.company_id, user, lock=True, buyer_only=True)
    await require_company_admin(data.company_id, user, db)
    if row.revision != data.expected_revision:
        raise HTTPException(409, "Карточка изменилась. Обновите доску и повторите действие")
    if row.status == "draft" and data.status not in {"draft", "sent"}:
        raise HTTPException(409, "Сначала отправьте запрос поставщику")
    if row.status != "draft" and data.status == "draft":
        raise HTTPException(409, "Отправленный запрос нельзя скрыть как черновик")
    if row.status == "draft" and data.status == "sent":
        need = await db.get(Need, row.need_id)
        if need.revision != row.need_revision or need.status in {"cancelled", "expired", "matched"} or need.deadline_date < date.today():
            raise HTTPException(409, "Требования устарели. Создайте запрос по актуальной потребности")
        row.sent_at = datetime.now(timezone.utc)
    for key in ("status", "quoted_price_rub", "price_basis", "lead_time_days", "delivery_date", "note"):
        setattr(row, key, getattr(data, key))
    row.revision += 1
    row.updated_at = datetime.now(timezone.utc)
    await approve(db, row, user, "supplier_board_update", {"revision": row.revision, "status": row.status, "price_basis": row.price_basis})
    await db.commit()
    return visible(row, data.company_id)


@router.get("/supplier-requests/{request_id}/messages", response_model=list[MessageOut])
async def messages(request_id: uuid.UUID, company_id: uuid.UUID, user: CurrentUser = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    await party(db, request_id, company_id, user)
    return (await db.scalars(select(SupplierRequestMessage).where(SupplierRequestMessage.request_id == request_id).order_by(SupplierRequestMessage.created_at, SupplierRequestMessage.id))).all()


@router.post("/supplier-requests/{request_id}/messages", response_model=MessageOut, status_code=201)
async def send_message(request_id: uuid.UUID, data: MessageIn, user: CurrentUser = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    row = await party(db, request_id, data.company_id, user, lock=True)
    old = await db.scalar(select(SupplierRequestMessage).where(SupplierRequestMessage.request_id == request_id, SupplierRequestMessage.author_company_id == data.company_id, SupplierRequestMessage.request_key == data.request_key))
    if old:
        if old.message != data.message:
            raise HTTPException(409, "Ключ отправки уже использован для другого сообщения")
        return old
    if row.revision != data.expected_revision:
        raise HTTPException(409, "Переписка изменилась. Обновите её перед отправкой")
    if row.status == "draft":
        await require_company_admin(data.company_id, user, db)
        need = await db.get(Need, row.need_id)
        if need.revision != row.need_revision or need.status in {"cancelled", "expired", "matched"} or need.deadline_date < date.today():
            raise HTTPException(409, "Требования устарели. Создайте новый запрос")
        row.status, row.sent_at = "sent", datetime.now(timezone.utc)
    elif data.company_id == row.seller_company_id and row.status == "sent":
        row.status = "replied"
    row.revision += 1
    row.updated_at = datetime.now(timezone.utc)
    message = SupplierRequestMessage(request_id=row.id, author_company_id=data.company_id, author_user_id=user.id, request_key=data.request_key, message=data.message)
    db.add(message)
    recipient = row.seller_company_id if data.company_id == row.buyer_company_id else row.buyer_company_id
    recipient_query = (
        text("SELECT DISTINCT user_id FROM auth.company_members WHERE company_id=:id AND can_sell=true")
        if recipient == row.seller_company_id else
        text("SELECT DISTINCT user_id FROM auth.company_members WHERE company_id=:id AND can_buy=true")
    )
    recipients = (await db.scalars(recipient_query, {"id": recipient})).all()
    for user_id in recipients:
        if user_id != user.id:
            await notify(db, user_id, f"Новое сообщение по запросу КП: {row.specification['category']}. Откройте переписку с {'покупателем' if recipient == row.seller_company_id else 'поставщиком'}.")
    await record_human_approval(db, action="supplier_message_send", entity_type="supplier_request", entity_id=row.id,
        actor_user_id=user.id, actor_company_id=data.company_id, permission="can_buy" if data.company_id == row.buyer_company_id else "can_sell", decision="approved",
        payload={"request_key": str(data.request_key), "message_sha256": hashlib.sha256(data.message.encode()).hexdigest()}, explanation="Пользователь проверил и отправил сообщение")
    await db.commit()
    await db.refresh(message)
    return message


@router.get("/supplier-requests/{request_id}/context")
async def context(request_id: uuid.UUID, company_id: uuid.UUID, user: CurrentUser = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    row = await party(db, request_id, company_id, user)
    catalog = (await db.scalars(select(Product).where(Product.company_id == row.seller_company_id, Product.is_published.is_(True)).order_by(Product.name).limit(100))).all()
    relevant = [p for p in catalog if p.category == row.specification["category"] and (not row.specification.get("subcategory") or p.subcategory == row.specification["subcategory"])]
    # Only an owning seller receives draft terms. Category/name similarity is
    # insufficient: compare the complete shared specification and current admission.
    catalog_terms = []
    if company_id == row.seller_company_id:
        from ..admission import publicly_available_products
        from ..category_compatibility import compare_specifications
        requested = SimpleNamespace(category=row.specification["category"], subcategory=row.specification.get("subcategory"),
            characteristics=row.specification.get("characteristics") or {}, volume_units=row.specification["quantity"])
        matching = [p for p in catalog if compare_specifications(p, requested).matches]
        for product in (await publicly_available_products(db, matching))[:3]:
            catalog_terms.append({"product_id": str(product.id), "name": product.name, "price_rub": format(product.price_rub, "f"),
                "moq_units": product.moq_units, "lead_time_days": product.lead_time_days, "unit": order_unit(product.characteristics)})
    recent = (await db.scalars(select(SupplierRequestMessage).where(SupplierRequestMessage.request_id == row.id).order_by(SupplierRequestMessage.created_at.desc(), SupplierRequestMessage.id.desc()).limit(20))).all()
    return {"contract_version": "supplier-workflow-1", "request_id": row.id, "revision": row.revision,
        "buyer_name": row.buyer_name, "seller_name": row.seller_name, "author_role": "buyer" if company_id == row.buyer_company_id else "seller",
        "specification": row.specification, "supplier_products": [p.name for p in (relevant or catalog)[:10]], "specialized": bool(relevant),
        "catalog_terms": catalog_terms,
        "messages": [{"role": "buyer" if m.author_company_id == row.buyer_company_id else "seller", "text": m.message} for m in reversed(recent)]}


@router.get("/supplier-requests/{request_id}/files", response_model=list[FileOut])
async def files(request_id: uuid.UUID, company_id: uuid.UUID, user: CurrentUser = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    await party(db, request_id, company_id, user, buyer_only=True)
    return (await db.scalars(select(SupplierReplyFile).where(SupplierReplyFile.request_id == request_id).order_by(SupplierReplyFile.created_at))).all()


@router.post("/supplier-requests/{request_id}/files", response_model=FileOut, status_code=201)
async def upload_reply(request_id: uuid.UUID, company_id: uuid.UUID, file: UploadFile = File(...), user: CurrentUser = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    await party(db, request_id, company_id, user, lock=True, buyer_only=True)
    await require_company_admin(company_id, user, db)
    content = await file.read(25 * 1024**2 + 1)
    if file.content_type not in {"application/pdf", "image/png", "image/jpeg", "image/webp", "text/plain"}:
        raise HTTPException(415, "Приложите PDF, изображение или текст UTF-8")
    try:
        media = await validate_upload(content, file.content_type)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    digest = hashlib.sha256(content).hexdigest()
    old = await db.scalar(select(SupplierReplyFile).where(SupplierReplyFile.request_id == request_id, SupplierReplyFile.content_hash == digest))
    if old:
        return old
    if (await db.scalar(select(func.count()).select_from(SupplierReplyFile).where(SupplierReplyFile.request_id == request_id))) >= 16:
        raise HTTPException(413, "В карточке уже 16 файлов")
    key = f"supplier-replies/{request_id}/{uuid.uuid4()}"
    await asyncio.to_thread(storage.upload_object, key, content, media)
    try:
        row = SupplierReplyFile(request_id=request_id, file_name=(file.filename or "Ответ поставщика")[:255], file_key=key, content_hash=digest, content_type=media)
        db.add(row)
        await db.commit()
    except BaseException:
        await asyncio.to_thread(storage.delete_object, key)
        raise
    await db.refresh(row)
    return row


@router.get("/supplier-requests/{request_id}/files/{file_id}")
async def download_reply(request_id: uuid.UUID, file_id: uuid.UUID, company_id: uuid.UUID, user: CurrentUser = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    await party(db, request_id, company_id, user, buyer_only=True)
    row = await db.get(SupplierReplyFile, file_id)
    if not row or row.request_id != request_id:
        raise HTTPException(404, "Файл ответа не найден")
    content = await asyncio.to_thread(storage.download_object, row.file_key)
    return Response(content, media_type=row.content_type, headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(row.file_name, safe='')}", "X-Content-Type-Options": "nosniff", "Cache-Control": "no-store"})
