import uuid
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_db
from ..deps import CurrentUser, get_current_user, require_company_seller, require_membership
from ..models import CapacityEntry, Deal, DealMessage, Product
from ..schemas import DealMessageIn, DealMessageOut, DealOut, SellerAnalyticsOut

router = APIRouter(tags=["stage8"])


async def _deal_party(deal: Deal, company_id: uuid.UUID, user: CurrentUser, db: AsyncSession) -> None:
    if company_id not in {deal.buyer_company_id, deal.seller_company_id}:
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="Компания не участвует в сделке")
    await require_membership(company_id, user, db)


@router.get("/companies/{company_id}/seller-analytics", response_model=SellerAnalyticsOut)
async def seller_analytics(company_id: uuid.UUID, user: CurrentUser = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    await require_company_seller(company_id, user, db)
    products_total = int(await db.scalar(select(func.count()).select_from(Product).where(Product.company_id == company_id)) or 0)
    products_published = int(await db.scalar(select(func.count()).select_from(Product).where(Product.company_id == company_id, Product.is_published.is_(True))) or 0)
    deals = (await db.execute(select(Deal).where(Deal.seller_company_id == company_id))).scalars().all()
    sold_units = sum(deal.units for deal in deals)
    revenue = sum(deal.total_price_rub for deal in deals)
    capacity = int(await db.scalar(select(func.coalesce(func.sum(CapacityEntry.available_units), 0)).where(CapacityEntry.company_id == company_id, CapacityEntry.date >= date.today())) or 0)
    utilization = round(sold_units / (sold_units + capacity) * 100, 1) if sold_units + capacity else 0.0
    return SellerAnalyticsOut(company_id=company_id, products_total=products_total, products_published=products_published, deals_total=len(deals), sold_units=sold_units, revenue_rub=revenue, available_capacity_units=capacity, capacity_utilization_pct=utilization)


@router.get("/deals/mine", response_model=list[DealOut])
async def my_deals(user: CurrentUser = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    # Членство проверяем SQL-запросом, чтобы одна учётная запись видела сделки обеих своих ролей.
    memberships = (await db.execute(text("SELECT company_id FROM auth.company_members WHERE user_id = :uid"), {"uid": user.id})).scalars().all()
    allowed = set(memberships)
    if not allowed:
        return []
    deals = (await db.execute(select(Deal).where(or_(Deal.buyer_company_id.in_(allowed), Deal.seller_company_id.in_(allowed))).order_by(Deal.created_at.desc()))).scalars().all()
    return deals


@router.get("/deals/{deal_id}/messages", response_model=list[DealMessageOut])
async def list_messages(deal_id: uuid.UUID, company_id: uuid.UUID, user: CurrentUser = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    deal = await db.get(Deal, deal_id)
    if deal is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Сделка не найдена")
    await _deal_party(deal, company_id, user, db)
    return (await db.execute(select(DealMessage).where(DealMessage.deal_id == deal.id).order_by(DealMessage.created_at))).scalars().all()


@router.post("/deals/{deal_id}/messages", response_model=DealMessageOut, status_code=status.HTTP_201_CREATED)
async def post_message(deal_id: uuid.UUID, data: DealMessageIn, user: CurrentUser = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    deal = await db.get(Deal, deal_id)
    if deal is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Сделка не найдена")
    await _deal_party(deal, data.company_id, user, db)
    message = DealMessage(
        deal_id=deal.id, author_user_id=user.id,
        author_company_id=data.company_id, message=data.message,
    )
    db.add(message)
    await db.commit()
    await db.refresh(message)
    return message
