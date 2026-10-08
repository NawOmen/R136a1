import uuid
from datetime import datetime, timezone
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, HTTPException, Response, UploadFile, status
from pydantic import ValidationError
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_db
from ..commerce import product_specification_hash
from ..category_profile_snapshot import profile_after_specification_change
from ..deps import (
    CurrentUser,
    get_current_user,
    require_company_admin,
    require_company_seller,
    require_verified_company,
)
from ..experience import notify_market_watchers, validate_characteristics
from ..models import Product, ProductImage, ProductPriceObservation
from ..resources import lock_company, reservations, occupies
from ..matching import run_market_rematch
from ..schemas import (
    AdmissionChecklistOut,
    ProductImageOut,
    ProductIn,
    ProductOut,
    ProductPatch,
    PublishIn,
)
from ..storage import delete_object, download_object, upload_object
from ..trust import append_audit_event
from ..admission import BUYER_CHECKLIST_NOTE, admission_audit_payload, company_admission, publicly_available_products

router = APIRouter(tags=["products"])
MAX_IMAGE_SIZE = 8 * 1024 * 1024
ALLOWED_IMAGE_TYPES = {"image/png", "image/jpeg", "image/webp"}


async def _product_out(product: Product, db: AsyncSession) -> ProductOut:
    images = (await db.execute(
        select(ProductImage).where(ProductImage.product_id == product.id).order_by(ProductImage.position)
    )).scalars().all()
    payload = {column.name: getattr(product, column.name) for column in Product.__table__.columns}
    return ProductOut.model_validate({**payload, "images": images})


@router.get("/products", response_model=list[ProductOut])
async def list_catalog(db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(Product).where(Product.is_published.is_(True)).order_by(Product.created_at.desc())
    )
    return [await _product_out(product, db) for product in await publicly_available_products(db, list(result.scalars()))]


@router.get("/companies/{company_id}/products", response_model=list[ProductOut])
async def list_company_products(
    company_id: uuid.UUID,
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await require_company_seller(company_id, user, db)
    result = await db.execute(
        select(Product).where(Product.company_id == company_id).order_by(Product.created_at.desc())
    )
    return [await _product_out(product, db) for product in result.scalars().all()]


@router.post("/companies/{company_id}/products", response_model=ProductOut, status_code=status.HTTP_201_CREATED)
async def create_product(
    company_id: uuid.UUID,
    data: ProductIn,
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await require_company_seller(company_id, user, db)
    await require_company_admin(company_id, user, db)
    payload = data.model_dump()
    product = Product(company_id=company_id, created_by_user_id=user.id, **payload)
    if payload.get("stock_units") is not None:
        product.stock_updated_at = datetime.now(timezone.utc)
    db.add(product)
    await db.commit()
    await db.refresh(product)
    return await _product_out(product, db)


@router.patch("/products/{product_id}", response_model=ProductOut)
async def update_product(
    product_id: uuid.UUID,
    data: ProductPatch,
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    product = await db.get(Product, product_id)
    if product is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Товар не найден")
    await require_company_seller(product.company_id, user, db)
    await require_company_admin(product.company_id, user, db)
    await lock_company(db, product.company_id)
    await db.refresh(product)
    patch = data.model_dump(exclude_unset=True)
    if "stock_units" in patch:
        held = sum(row.units for row in await reservations(db, product.company_id) if row.product_id == product.id and occupies(row, stock=True))
        if held and (patch["stock_units"] is None or patch["stock_units"] < held):
            raise HTTPException(409, f"На складе зарезервировано {held} единиц. Сначала согласуйте отмену обязательств")
    old_price = product.price_rub
    old_category = product.category
    current = {
        "name": product.name, "category": product.category, "subcategory": product.subcategory,
        "characteristics": product.characteristics, "price_rub": product.price_rub,
        "price_tiers": product.price_tiers, "moq_units": product.moq_units,
        "lead_time_days": product.lead_time_days, "stock_units": product.stock_units,
    }
    # Повторно проверяем объединённое состояние: частичный PATCH не должен
    # рассинхронизировать МОЗ, базовую цену и ценовые ступени.
    try:
        validated = ProductIn.model_validate({**current, **patch})
    except ValidationError as exc:
        raise HTTPException(422, "; ".join(error["msg"] for error in exc.errors())) from exc
    from ..category_units import order_unit
    if order_unit(validated.characteristics) != order_unit(product.characteristics):
        if any(row.product_id == product.id and occupies(row,stock=True) for row in await reservations(db,product.company_id)):
            raise HTTPException(409,"Нельзя менять единицу товара с действующим резервом. Сначала согласуйте изменение обязательств")
    # Допуск зависит не только от категории: материал, покрытие и назначение
    # определяют применимость документов, поэтому изменение характеристик тоже
    # требует повторной проверки опубликованного товара.
    admission_inputs_changed = (
        (validated.category, validated.subcategory, validated.characteristics)
        != (old_category, product.subcategory, product.characteristics)
    )
    if product.is_published and admission_inputs_changed:
        admission = await company_admission(
            db,
            product.company_id,
            validated.category,
            validated.subcategory,
            characteristics=validated.characteristics,
            moq_units=validated.moq_units,
        )
        if admission.blocking_open:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                detail=(
                    "Изменение отклонено, пока товар опубликован: "
                    f"{admission.blocking_reasons or admission.summary} "
                    "Сначала снимите товар с публикации."
                ),
            )
        errors, _ = validate_characteristics(validated.category, validated.subcategory, validated.characteristics, validated.moq_units)
        if errors:
            raise HTTPException(422, "; ".join(errors))
    if admission_inputs_changed:
        product.quantity_conversion = None
    product.category_profile = profile_after_specification_change(
        product, validated.category, validated.subcategory, validated.characteristics,
    )
    for field, value in validated.model_dump().items():
        setattr(product, field, value)
    if "stock_units" in patch:
        # Остаток влияет на доступный объём предложения, поэтому фиксируем время.
        product.stock_updated_at = datetime.now(timezone.utc)
    if product.is_published and (product.price_rub != old_price or product.category != old_category):
        db.add(ProductPriceObservation(product_id=product.id, category=product.category, unit_price_rub=product.price_rub, specification_hash=product_specification_hash(product)))
    await run_market_rematch(db, "product_terms_changed", product.id)
    if product.is_published:
        await notify_market_watchers(db, product.category, "supply", exclude_user_id=user.id)
    await db.commit()
    await db.refresh(product)
    return await _product_out(product, db)


@router.post("/products/{product_id}/publish", response_model=ProductOut)
async def publish_product(
    product_id: uuid.UUID,
    data: PublishIn,
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    product = await db.get(Product, product_id)
    if product is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Товар не найден")
    await require_company_seller(product.company_id, user, db)
    await require_company_admin(product.company_id, user, db)
    admission = None
    if data.published:
        await require_verified_company(product.company_id, user, db)
        errors, _ = validate_characteristics(product.category, product.subcategory, product.characteristics, product.moq_units)
        if errors:
            raise HTTPException(422, "; ".join(errors))
        # Проверка компании не подтверждает документы конкретного товара.
        admission = await company_admission(
            db,
            product.company_id,
            product.category,
            product.subcategory,
            characteristics=product.characteristics,
            moq_units=product.moq_units,
        )
        if admission.blocking_open:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                detail=(
                    "Публикация заблокирована: "
                    f"{admission.blocking_reasons or admission.summary}"
                ),
            )
    was_published = product.is_published
    product.is_published = data.published
    if data.published and not was_published and admission is not None:
        db.add(ProductPriceObservation(product_id=product.id, category=product.category, unit_price_rub=product.price_rub, specification_hash=product_specification_hash(product)))
        await append_audit_event(
            db,
            event_type="product_published_with_admission",
            entity_type="product",
            entity_id=product.id,
            actor_user_id=user.id,
            actor_company_id=product.company_id,
            source_refs=[{"type": "product", "id": str(product.id)}],
            explanation="Товар опубликован после программной проверки категорийного допуска.",
            payload={"category": product.category, "admission": admission_audit_payload(admission, specification={
                "category": product.category, "subcategory": product.subcategory,
                "characteristics": product.characteristics, "moq_units": product.moq_units,
                "category_profile": product.category_profile,
            })},
        )
        await notify_market_watchers(db, product.category, "supply", exclude_user_id=user.id)
    await run_market_rematch(db, "product_publication_changed", product.id)
    await db.commit()
    await db.refresh(product)
    return await _product_out(product, db)


@router.post("/products/{product_id}/images", response_model=ProductImageOut, status_code=status.HTTP_201_CREATED)
async def upload_product_image(
    product_id: uuid.UUID,
    file: UploadFile = File(...),
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    product = await db.get(Product, product_id)
    if product is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Товар не найден")
    await require_company_seller(product.company_id, user, db)
    await require_company_admin(product.company_id, user, db)
    content_type = file.content_type or ""
    if content_type not in ALLOWED_IMAGE_TYPES:
        raise HTTPException(status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, detail="Допустимы PNG, JPG и WebP")
    data = await file.read()
    if not data:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="Изображение пустое")
    if len(data) > MAX_IMAGE_SIZE:
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail="Изображение больше 8 МБ")
    positions = set((await db.execute(
        select(ProductImage.position).where(ProductImage.product_id == product.id)
    )).scalars().all())
    if len(positions) >= 5:
        raise HTTPException(status.HTTP_409_CONFLICT, detail="К товару можно добавить не более 5 изображений")
    position = next(position for position in range(5) if position not in positions)
    file_name = (file.filename or "product-image")[:255]
    key = f"products/{product.id}/{uuid.uuid4()}"
    upload_object(key, data, content_type)
    image = ProductImage(
        product_id=product.id, file_name=file_name, file_key=key,
        content_type=content_type, position=position,
    )
    db.add(image)
    try:
        await db.commit()
    except Exception:
        await db.rollback()
        delete_object(key)
        raise
    await db.refresh(image)
    return image


@router.get("/products/{product_id}/admission", response_model=AdmissionChecklistOut)
async def product_admission(product_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    """Чек-лист покупателя: какие обязательные доказательства проверены у продавца.

    Отдаются только состояния требований, без имён файлов и внутренних данных документов.
    """
    product = await db.get(Product, product_id)
    if product is None or not product.is_published:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Товар не найден")
    admission = await company_admission(
        db,
        product.company_id,
        product.category,
        product.subcategory,
        characteristics=product.characteristics,
        moq_units=product.moq_units,
    )
    return AdmissionChecklistOut(
        product_id=product.id,
        category=product.category,
        subcategory=product.subcategory,
        state=admission.state,
        state_label=admission.state_label,
        supported=admission.supported,
        summary=admission.summary,
        checklist=[
            {
                "code": item.code,
                "title": item.title,
                "legal_reference": item.legal_reference,
                "blocking": item.blocking,
                "state": item.state,
                "state_label": item.state_label,
                "seller_hint": item.seller_hint,
                "buyer_note": item.buyer_note,
                "document_ids": [],
                "scope_note": item.scope_note,
            }
            for item in admission.requirements
        ],
        advisories=admission.advisories,
        note=BUYER_CHECKLIST_NOTE,
        checked_at=admission.checked_at,
    )


@router.get("/product-images/{image_id}")
async def get_product_image(image_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    image = await db.get(ProductImage, image_id)
    if image is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Изображение не найдено")
    product = await db.get(Product, image.product_id)
    if product is None or not product.is_published:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Изображение не найдено")
    return Response(
        content=download_object(image.file_key), media_type=image.content_type,
        headers={"Content-Disposition": f"inline; filename*=UTF-8''{quote(image.file_name)}"},
    )


@router.delete("/product-images/{image_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_product_image(
    image_id: uuid.UUID,
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    image = await db.get(ProductImage, image_id)
    if image is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Изображение не найдено")
    product = await db.get(Product, image.product_id)
    if product is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Товар не найден")
    await require_company_seller(product.company_id, user, db)
    await require_company_admin(product.company_id, user, db)
    await db.execute(delete(ProductImage).where(ProductImage.id == image.id))
    await db.commit()
    delete_object(image.file_key)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
