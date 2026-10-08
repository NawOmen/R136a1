import uuid
import hashlib
import json
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, File, HTTPException, Response, UploadFile, status
from sqlalchemy import delete, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import IntegrityError

from ..admission import publicly_available_products
from ..database import get_db
from ..commerce import product_specification_hash
from ..deps import CurrentUser, get_current_user, notify, require_company_admin, require_company_buyer, require_company_seller, require_membership
from ..category_characteristics import validate_profile_values
from ..experience import classify_cargo, validate_characteristics
from ..models import (
    CoalitionMember, Deal, DealCheckpoint, DealExecutionEvent, DealReview, DeliveryArrangement, MarketWatch,
    Need, Product, ProductImage, ProductPriceObservation, ProductionProfile, CapabilityPassport,
)
from ..schemas import (
    BuyerSavingsOut, CharacteristicValidationIn, CharacteristicValidationOut,
    CheckpointUpdateIn, DealCheckpointOut, DealReviewIn, DealReviewOut,
    DeliveryArrangementIn, DeliveryArrangementOut, MarketWatchIn, MarketWatchOut,
    NeedOut, NeedRepeatIn, PriceIndexPoint, PublicProducerOut, PublicProductDetailOut,
)
from ..storage import delete_object, download_object, upload_object
from ..resources import consume
from ..trust import append_audit_event, record_human_approval

router = APIRouter(tags=["stage9"])
CHECKPOINTS = ("production", "shipment", "delivery")
CHECKPOINT_LABELS = {"production": "производство", "shipment": "отгрузка", "delivery": "доставка"}
PRODUCTION_IMAGE_TYPES = {"image/png", "image/jpeg", "image/webp"}


async def _deal_party(deal: Deal, company_id: uuid.UUID, user: CurrentUser, db: AsyncSession) -> None:
    if company_id not in {deal.buyer_company_id, deal.seller_company_id}:
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="Компания не участвует в сделке")
    await require_membership(company_id, user, db)


async def _ensure_checkpoints(deal_id: uuid.UUID, db: AsyncSession) -> list[DealCheckpoint]:
    for kind in CHECKPOINTS:
        await db.execute(text(
            "INSERT INTO marketplace.deal_checkpoints (id, deal_id, kind) "
            "VALUES (:id, :deal_id, :kind) ON CONFLICT (deal_id, kind) DO NOTHING"
        ), {"id": uuid.uuid4(), "deal_id": deal_id, "kind": kind})
    rows = (await db.execute(select(DealCheckpoint).where(DealCheckpoint.deal_id == deal_id))).scalars().all()
    by_kind = {row.kind: row for row in rows}
    return [by_kind[kind] for kind in CHECKPOINTS]


@router.get("/products/{product_id}/detail", response_model=PublicProductDetailOut)
async def public_product_detail(product_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    product = await db.get(Product, product_id)
    if product is None or not await publicly_available_products(db, [product]):
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Товар не найден")
    company = (await db.execute(text(
        "SELECT c.display_name, c.legal_form, c.verification_status FROM auth.companies c "
        "WHERE c.id = :id AND EXISTS (SELECT 1 FROM auth.company_members m WHERE m.company_id = c.id AND m.can_sell = true)"
    ), {"id": product.company_id})).mappings().first()
    if company is None or company["verification_status"] != "verified":
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Товар не найден")
    profile = await db.get(ProductionProfile, product.company_id)
    rating, count = (await db.execute(select(func.avg(DealReview.rating), func.count(DealReview.id)).where(
        DealReview.reviewed_company_id == product.company_id
    ))).one()
    images = (await db.execute(select(ProductImage).where(ProductImage.product_id == product.id).order_by(ProductImage.position))).scalars().all()
    payload = {column.name: getattr(product, column.name) for column in Product.__table__.columns}
    producer = PublicProducerOut(
        company_id=product.company_id, display_name=company["display_name"], legal_form=company["legal_form"],
        region=profile.region if profile else None, about=profile.about if profile else None,
        production_site_address=profile.production_site_address if profile else None,
        has_photo=bool(profile and profile.photo_file_key), rating=round(float(rating), 1) if rating else None,
        reviews_count=int(count or 0),
    )
    return PublicProductDetailOut.model_validate({**payload, "images": images, "producer": producer})


@router.get("/producers/{company_id}", response_model=PublicProducerOut)
async def public_producer(company_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    row = (await db.execute(text(
        "SELECT c.display_name, c.legal_form, c.verification_status FROM auth.companies c "
        "WHERE c.id = :id AND EXISTS (SELECT 1 FROM auth.company_members m WHERE m.company_id = c.id AND m.can_sell = true)"
    ), {"id": company_id})).mappings().first()
    if row is None or row["verification_status"] != "verified":
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Производитель не найден")
    profile = await db.get(ProductionProfile, company_id)
    passport = await db.get(CapabilityPassport, company_id)
    rating, count = (await db.execute(select(func.avg(DealReview.rating), func.count(DealReview.id)).where(
        DealReview.reviewed_company_id == company_id
    ))).one()
    return PublicProducerOut(
        capability_details=(passport.details or None) if passport else None,
        company_id=company_id, display_name=row["display_name"], legal_form=row["legal_form"],
        region=profile.region if profile else None, about=profile.about if profile else None,
        production_site_address=profile.production_site_address if profile else None,
        has_photo=bool(profile and profile.photo_file_key), rating=round(float(rating), 1) if rating else None,
        reviews_count=int(count or 0),
    )


@router.get("/producers/{company_id}/photo")
async def production_photo(company_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    profile = await db.get(ProductionProfile, company_id)
    if profile is None or not profile.photo_file_key or not profile.photo_content_type:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Фотография производства не найдена")
    verified = await db.scalar(text("SELECT verification_status = 'verified' FROM auth.companies WHERE id = :id"), {"id": company_id})
    if not verified:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Фотография производства не найдена")
    return Response(content=download_object(profile.photo_file_key), media_type=profile.photo_content_type)


@router.post("/companies/{company_id}/production-photo", status_code=status.HTTP_204_NO_CONTENT)
async def upload_production_photo(company_id: uuid.UUID, file: UploadFile = File(...), user: CurrentUser = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    await require_company_seller(company_id, user, db)
    await require_company_admin(company_id, user, db)
    content_type = file.content_type or ""
    if content_type not in PRODUCTION_IMAGE_TYPES:
        raise HTTPException(status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, detail="Допустимы PNG, JPG и WebP")
    data = await file.read()
    if not data or len(data) > 8 * 1024 * 1024:
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail="Фотография должна быть от 1 байта до 8 МБ")
    profile = await db.get(ProductionProfile, company_id)
    if profile is None:
        profile = ProductionProfile(company_id=company_id)
        db.add(profile)
    previous_key = profile.photo_file_key
    key = f"production/{company_id}/{uuid.uuid4()}"
    upload_object(key, data, content_type)
    profile.photo_file_key, profile.photo_file_name, profile.photo_content_type = key, (file.filename or "production")[:255], content_type
    try:
        await db.commit()
    except Exception:
        await db.rollback(); delete_object(key); raise
    if previous_key:
        delete_object(previous_key)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/needs/{need_id}/repeat", response_model=NeedOut, status_code=status.HTTP_201_CREATED)
async def repeat_need(need_id: uuid.UUID, data: NeedRepeatIn, user: CurrentUser = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    original = await db.get(Need, need_id)
    if original is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Потребность не найдена")
    await require_company_buyer(original.company_id, user, db)
    await require_company_admin(original.company_id, user, db)
    today = datetime.now(timezone.utc).date()
    if data.deadline_date < today or (data.valid_until and data.valid_until < today):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Новые сроки не могут быть в прошлом")
    if data.valid_until and data.valid_until > data.deadline_date:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Срок актуальности не может быть позже срока поставки")
    request_hash = hashlib.sha256(json.dumps({"source_need_id": str(need_id), "deadline_date": data.deadline_date.isoformat(),
        "valid_until": (data.valid_until or data.deadline_date).isoformat()}, sort_keys=True).encode()).hexdigest()
    if data.request_key:
        await db.execute(text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
            {"key": f"need-request:{original.company_id}:{data.request_key}"})
        existing = await db.scalar(select(Need).where(Need.company_id == original.company_id, Need.request_key == data.request_key))
        if existing:
            if existing.request_hash != request_hash:
                raise HTTPException(status.HTTP_409_CONFLICT, detail="Ключ повторного заказа уже использован для других условий")
            return NeedOut.model_validate({**{column.name: getattr(existing, column.name) for column in Need.__table__.columns}, "files": []})
    if original.delivery_address_id is not None:
        address_owner = await db.scalar(text("SELECT company_id FROM marketplace.delivery_addresses WHERE id = :id"),
            {"id": original.delivery_address_id})
        if address_owner != original.company_id:
            raise HTTPException(status.HTTP_409_CONFLICT, detail="Адрес прежнего заказа больше недоступен. Выберите новый адрес")
    errors = validate_profile_values(original.category, original.subcategory, original.characteristics)
    if errors:
        raise HTTPException(422, "; ".join(errors))
    copy = Need(
        company_id=original.company_id, created_by_user_id=user.id, category=original.category, subcategory=original.subcategory,
        characteristics=original.characteristics, volume_units=original.volume_units, budget_rub=original.budget_rub,
        deadline_date=data.deadline_date, delivery_address_id=original.delivery_address_id,
        visibility=original.visibility, status="draft", valid_until=data.valid_until or data.deadline_date,
        request_key=data.request_key, request_hash=request_hash,
    )
    db.add(copy); await db.commit(); await db.refresh(copy)
    return NeedOut.model_validate({**{column.name: getattr(copy, column.name) for column in Need.__table__.columns}, "files": []})


@router.post("/products/validate-characteristics", response_model=CharacteristicValidationOut)
async def validate_product_characteristics(data: CharacteristicValidationIn):
    errors, warnings = validate_characteristics(data.category, data.subcategory, data.characteristics, data.moq_units)
    return CharacteristicValidationOut(valid=not errors, errors=errors, warnings=warnings)


@router.get("/deals/{deal_id}/timeline", response_model=list[DealCheckpointOut])
async def deal_timeline(deal_id: uuid.UUID, company_id: uuid.UUID, user: CurrentUser = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    deal = await db.get(Deal, deal_id)
    if deal is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Сделка не найдена")
    await _deal_party(deal, company_id, user, db)
    result = await _ensure_checkpoints(deal.id, db); await db.commit()
    return result


@router.patch("/deals/{deal_id}/timeline/{kind}", response_model=list[DealCheckpointOut])
async def update_checkpoint(deal_id: uuid.UUID, kind: str, data: CheckpointUpdateIn, user: CurrentUser = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    if kind not in CHECKPOINTS:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Этап сделки не найден")
    deal = await db.scalar(select(Deal).where(Deal.id == deal_id).with_for_update())
    if deal is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Сделка не найдена")
    await _deal_party(deal, data.company_id, user, db)
    await require_company_admin(data.company_id, user, db)
    expected_company = deal.buyer_company_id if kind == "delivery" else deal.seller_company_id
    if data.company_id != expected_company:
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="Этот этап подтверждает другая сторона сделки")
    if deal.status == "cancelled":
        raise HTTPException(status.HTTP_409_CONFLICT, detail="Заказ отменён")
    if kind == "shipment" and not data.completed:
        raise HTTPException(409, "Отгрузку нельзя отменить переключателем. Оформите возврат или отмену остатка")
    if not data.completed:
        recorded = await db.scalar(select(DealExecutionEvent.id).where(DealExecutionEvent.deal_id == deal.id).limit(1))
        if recorded:
            raise HTTPException(status.HTTP_409_CONFLICT, detail="Исполнение уже зафиксировано. Используйте возврат или отмену остатка")
    checkpoints = await _ensure_checkpoints(deal.id, db)
    target = checkpoints[CHECKPOINTS.index(kind)]
    if data.completed and any(item.status != "completed" for item in checkpoints[:CHECKPOINTS.index(kind)]):
        raise HTTPException(status.HTTP_409_CONFLICT, detail="Сначала завершите предыдущий этап")
    if not data.completed and any(item.status == "completed" for item in checkpoints[CHECKPOINTS.index(kind) + 1:]):
        raise HTTPException(status.HTTP_409_CONFLICT, detail="Сначала отмените последующие этапы")
    if target.status == ("completed" if data.completed else "pending") and target.note == data.note:
        return checkpoints
    if kind == "shipment" and data.completed:
        await consume(db, company_id=deal.seller_company_id, anchor_type="deal", anchor_id=deal.id)
    target.status = "completed" if data.completed else "pending"
    target.note = data.note
    target.confirmed_by_user_id = user.id
    target.completed_at = datetime.now(timezone.utc) if data.completed else None
    await record_human_approval(db, action="update_deal_checkpoint", entity_type="deal", entity_id=deal.id,
        actor_user_id=user.id, actor_company_id=data.company_id, permission="deal_party",
        decision="approved", payload={"kind": kind, "completed": data.completed},
        source_refs=[{"type": "deal", "id": str(deal.id)}], explanation="Участник сделки вручную подтвердил изменение контрольной точки.")
    await append_audit_event(db, event_type="deal_checkpoint_updated", entity_type="deal", entity_id=deal.id,
        actor_user_id=user.id, actor_company_id=data.company_id, source_refs=[{"type": "deal", "id": str(deal.id)}],
        explanation="Контрольная точка сделки изменена после явного подтверждения.", payload={"kind": kind, "completed": data.completed})
    if deal.status not in {"fulfilled", "partially_accepted", "cancelled", "returned"}:
        completed = [item.kind for item in checkpoints if item.status == "completed"]
        deal.status = {"delivery": "delivered", "shipment": "shipped", "production": "in_production"}.get(completed[-1], "created") if completed else "created"
    other_company_id = deal.seller_company_id if data.company_id == deal.buyer_company_id else deal.buyer_company_id
    other_users = (await db.execute(text(
        "SELECT user_id FROM auth.company_members WHERE company_id = :company_id"
    ), {"company_id": other_company_id})).scalars().all()
    for other_user_id in set(other_users):
        await notify(db, other_user_id, f"Обновлён этап сделки: {CHECKPOINT_LABELS[kind]}", "deal_checkpoint_updated")
    await db.commit()
    return checkpoints


@router.put("/deals/{deal_id}/delivery", response_model=DeliveryArrangementOut)
async def save_delivery(deal_id: uuid.UUID, data: DeliveryArrangementIn, user: CurrentUser = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    deal = await db.get(Deal, deal_id)
    if deal is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Сделка не найдена")
    await _deal_party(deal, data.company_id, user, db)
    await require_company_admin(data.company_id, user, db)
    if data.company_id != deal.buyer_company_id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="Организацию получения подтверждает покупатель")
    cargo_class, note = classify_cargo(data.weight_kg, data.volume_m3)
    item = (await db.execute(select(DeliveryArrangement).where(DeliveryArrangement.deal_id == deal.id))).scalar_one_or_none()
    values = data.model_dump(exclude={"company_id", "human_approved"})
    if item is None:
        item = DeliveryArrangement(deal_id=deal.id, cargo_class=cargo_class, classification_note=note,
            buyer_responsible=True, confirmed_by_user_id=user.id, **values); db.add(item)
    else:
        for key, value in values.items(): setattr(item, key, value)
        item.cargo_class, item.classification_note, item.confirmed_by_user_id = cargo_class, note, user.id
    await record_human_approval(db, action="confirm_delivery_arrangement", entity_type="deal", entity_id=deal.id,
        actor_user_id=user.id, actor_company_id=data.company_id, permission="company_admin+buyer",
        decision="approved", payload={**values, "cargo_class": cargo_class},
        source_refs=[{"type": "deal", "id": str(deal.id)}], explanation="Покупатель выбрал способ получения; площадка не заключает договор перевозки.")
    await db.commit(); await db.refresh(item); return item


@router.get("/deals/{deal_id}/delivery", response_model=DeliveryArrangementOut | None)
async def get_delivery(deal_id: uuid.UUID, company_id: uuid.UUID, user: CurrentUser = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    deal = await db.get(Deal, deal_id)
    if deal is None: raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Сделка не найдена")
    await _deal_party(deal, company_id, user, db)
    return (await db.execute(select(DeliveryArrangement).where(DeliveryArrangement.deal_id == deal.id))).scalar_one_or_none()


@router.post("/deals/{deal_id}/reviews", response_model=DealReviewOut, status_code=status.HTTP_201_CREATED)
async def create_review(deal_id: uuid.UUID, data: DealReviewIn, user: CurrentUser = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    deal = await db.get(Deal, deal_id)
    if deal is None: raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Сделка не найдена")
    await _deal_party(deal, data.company_id, user, db)
    await require_company_admin(data.company_id, user, db)
    checkpoints = await _ensure_checkpoints(deal.id, db)
    if checkpoints[-1].status != "completed":
        raise HTTPException(status.HTTP_409_CONFLICT, detail="Отзыв доступен только после подтверждённой доставки")
    reviewed = deal.seller_company_id if data.company_id == deal.buyer_company_id else deal.buyer_company_id
    review = DealReview(deal_id=deal.id, reviewer_company_id=data.company_id, reviewed_company_id=reviewed,
        rating=data.rating, comment=data.comment)
    db.add(review)
    try: await db.commit()
    except IntegrityError:
        await db.rollback(); raise HTTPException(status.HTTP_409_CONFLICT, detail="Отзыв по этой сделке уже оставлен")
    await db.refresh(review); return review


@router.get("/producers/{company_id}/reviews", response_model=list[DealReviewOut])
async def producer_reviews(company_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    producer_exists = await db.scalar(text(
        "SELECT EXISTS (SELECT 1 FROM auth.companies c WHERE c.id = :id AND c.verification_status = 'verified' "
        "AND EXISTS (SELECT 1 FROM auth.company_members m WHERE m.company_id = c.id AND m.can_sell = true))"
    ), {"id": company_id})
    if not producer_exists:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Производитель не найден")
    return (await db.execute(select(DealReview).where(DealReview.reviewed_company_id == company_id).order_by(DealReview.created_at.desc()))).scalars().all()


@router.get("/price-index/{category}", response_model=list[PriceIndexPoint])
async def price_index(category: str, product_id: uuid.UUID | None = None, db: AsyncSession = Depends(get_db)):
    # A category average across unrelated SKUs is not a meaningful market index.
    if product_id is None:
        return []
    product = await db.get(Product, product_id)
    if product is None or product.category != category or not await publicly_available_products(db, [product]):
        raise HTTPException(404, "Товар не найден")
    day = func.date(ProductPriceObservation.observed_at)
    latest = select(day.label("day"), ProductPriceObservation.unit_price_rub.label("price"),
        func.row_number().over(partition_by=day, order_by=(ProductPriceObservation.observed_at.desc(), ProductPriceObservation.id.desc())).label("rank")
    ).where(ProductPriceObservation.product_id == product.id,
            ProductPriceObservation.specification_hash == product_specification_hash(product)).subquery()
    rows = (await db.execute(select(latest.c.day, latest.c.price).where(latest.c.rank == 1).order_by(latest.c.day))).all()
    return [PriceIndexPoint(date=row.day, average_unit_price_rub=round(float(row.price), 2), offers_count=1) for row in rows]


@router.get("/market-watches", response_model=list[MarketWatchOut])
async def list_watches(user: CurrentUser = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    return (await db.execute(select(MarketWatch).where(MarketWatch.user_id == user.id).order_by(MarketWatch.category))).scalars().all()


@router.post("/market-watches", response_model=MarketWatchOut, status_code=status.HTTP_201_CREATED)
async def create_watch(data: MarketWatchIn, user: CurrentUser = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    existing = (await db.execute(select(MarketWatch).where(MarketWatch.user_id == user.id, MarketWatch.category == data.category))).scalar_one_or_none()
    if existing:
        existing.demand_changes, existing.supply_changes = data.demand_changes, data.supply_changes; item = existing
    else:
        item = MarketWatch(user_id=user.id, **data.model_dump()); db.add(item)
    await db.commit(); await db.refresh(item); return item


@router.delete("/market-watches/{watch_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_watch(watch_id: uuid.UUID, user: CurrentUser = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    await db.execute(delete(MarketWatch).where(MarketWatch.id == watch_id, MarketWatch.user_id == user.id)); await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/companies/{company_id}/buyer-savings", response_model=BuyerSavingsOut)
async def buyer_savings(company_id: uuid.UUID, user: CurrentUser = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    await require_company_buyer(company_id, user, db)
    members = (await db.execute(select(CoalitionMember).where(CoalitionMember.buyer_company_id == company_id))).scalars().all()
    confirmed = sum(float(item.benefit_rub or 0) for item in members if item.approval_status == "approved")
    calculated = sum(float(item.benefit_rub or 0) for item in members)
    return BuyerSavingsOut(company_id=company_id, confirmed_savings_rub=round(confirmed, 2),
        calculated_variants_rub=round(calculated, 2), coalitions_count=len({item.coalition_id for item in members}),
        explanation="Подтверждённая экономия считается только по одобренным участником вариантам относительно зафиксированной индивидуальной альтернативы.")
