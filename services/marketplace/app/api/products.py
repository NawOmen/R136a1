import uuid
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, HTTPException, Response, UploadFile, status
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_db
from ..deps import (
    CurrentUser,
    get_current_user,
    require_company_admin,
    require_company_seller,
    require_verified_company,
)
from ..models import Product, ProductImage
from ..matching import run_market_rematch
from ..schemas import ProductImageOut, ProductIn, ProductOut, ProductPatch, PublishIn
from ..storage import delete_object, download_object, upload_object

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
    return [await _product_out(product, db) for product in result.scalars().all()]


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
    product = Product(company_id=company_id, created_by_user_id=user.id, **data.model_dump())
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
    patch = data.model_dump(exclude_unset=True)
    current = {
        "name": product.name, "category": product.category, "subcategory": product.subcategory,
        "characteristics": product.characteristics, "price_rub": product.price_rub,
        "price_tiers": product.price_tiers, "moq_units": product.moq_units,
        "lead_time_days": product.lead_time_days,
    }
    # Повторно проверяем объединённое состояние: частичный PATCH не должен
    # рассинхронизировать МОЗ, базовую цену и ценовые ступени.
    validated = ProductIn.model_validate({**current, **patch})
    for field, value in validated.model_dump().items():
        setattr(product, field, value)
    await run_market_rematch(db, "product_terms_changed", product.id)
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
    if data.published:
        await require_verified_company(product.company_id, user, db)
    product.is_published = data.published
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
