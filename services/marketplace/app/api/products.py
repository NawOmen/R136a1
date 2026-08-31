import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_db
from ..deps import (
    CurrentUser,
    get_current_user,
    require_company_admin,
    require_company_seller,
    require_verified_company,
)
from ..models import Product
from ..matching import run_market_rematch
from ..schemas import ProductIn, ProductOut, ProductPatch, PublishIn

router = APIRouter(tags=["products"])


@router.get("/products", response_model=list[ProductOut])
async def list_catalog(db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(Product).where(Product.is_published.is_(True)).order_by(Product.created_at.desc())
    )
    return result.scalars().all()


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
    return result.scalars().all()


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
    return product


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
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(product, field, value)
    await run_market_rematch(db, "product_terms_changed", product.id)
    await db.commit()
    await db.refresh(product)
    return product


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
    return product
