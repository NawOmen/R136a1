import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_db
from ..deps import (
    CurrentUser,
    get_company,
    get_current_user,
    get_membership,
    notify,
    require_company_buyer,
    require_company_seller,
    require_verified_company,
)
from ..models import Deal, Need, Offer
from ..schemas import DealOut, OfferIn, OfferOut

router = APIRouter(tags=["offers"])


@router.get("/needs/{need_id}/offers", response_model=list[OfferOut])
async def list_offers(
    need_id: uuid.UUID,
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    need = await db.get(Need, need_id)
    if need is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Потребность не найдена")

    membership = await get_membership(db, need.company_id, user.id)
    if membership and membership["can_buy"]:
        query = select(Offer).where(Offer.need_id == need.id)
    else:
        seller_companies = (
            await db.execute(
                text(
                    "SELECT company_id FROM auth.company_members "
                    "WHERE user_id = :uid AND can_sell = true"
                ),
                {"uid": user.id},
            )
        ).scalars().all()
        if not seller_companies:
            return []
        result = await db.execute(
            select(Offer).where(
                Offer.need_id == need.id, Offer.company_id.in_(seller_companies)
            )
        )
        return result.scalars().all()

    result = await db.execute(query.order_by(Offer.created_at))
    return result.scalars().all()


@router.post("/needs/{need_id}/offers", response_model=OfferOut, status_code=status.HTTP_201_CREATED)
async def create_offer(
    need_id: uuid.UUID,
    data: OfferIn,
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    need = await db.get(Need, need_id)
    if need is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Потребность не найдена")
    if need.status != "open_for_offers":
        raise HTTPException(status.HTTP_409_CONFLICT, detail="Потребность не открыта для предложений")
    if need.visibility != "open_anonymized":
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="Потребность недоступна этой компании")
    if need.company_id == data.company_id:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail="Нельзя отправить предложение на потребность своей компании",
        )

    await require_company_seller(data.company_id, user, db)
    await require_verified_company(data.company_id, user, db)
    existing = await db.execute(
        select(Offer).where(Offer.need_id == need.id, Offer.company_id == data.company_id)
    )
    if existing.scalar_one_or_none() is not None:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail="Компания уже отправила предложение по этой потребности",
        )

    offer = Offer(
        need_id=need.id,
        company_id=data.company_id,
        created_by_user_id=user.id,
        price_rub=data.price_rub,
        available_units=data.available_units,
        lead_time_days=data.lead_time_days,
    )
    db.add(offer)
    if need.created_by_user_id:
        await notify(db, need.created_by_user_id, "По вашей потребности поступило новое предложение", "offer_received")
    await db.commit()
    await db.refresh(offer)
    return offer


@router.post("/offers/{offer_id}/select", response_model=DealOut, status_code=status.HTTP_201_CREATED)
async def select_offer(
    offer_id: uuid.UUID,
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    offer = await db.get(Offer, offer_id)
    if offer is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Предложение не найдено")

    need = (
        await db.execute(select(Need).where(Need.id == offer.need_id).with_for_update())
    ).scalar_one_or_none()
    if need is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Потребность не найдена")

    await require_company_buyer(need.company_id, user, db)
    await require_verified_company(need.company_id, user, db)
    if need.status != "open_for_offers":
        raise HTTPException(status.HTTP_409_CONFLICT, detail="Потребность уже не открыта для предложений")
    if offer.status != "sent":
        raise HTTPException(status.HTTP_409_CONFLICT, detail="Предложение уже обработано")
    seller_company = await get_company(db, offer.company_id)
    if seller_company is None or seller_company["verification_status"] != "verified":
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail="Компания продавца больше не допущена к сделкам",
        )
    if offer.available_units < need.volume_units:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail="Предложение не покрывает требуемый объём",
        )
    total_price = round(offer.price_rub * need.volume_units, 2)
    if need.budget_rub is not None and total_price > need.budget_rub:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail="Стоимость предложения превышает бюджет потребности",
        )

    deal = Deal(
        offer_id=offer.id,
        need_id=need.id,
        buyer_company_id=need.company_id,
        seller_company_id=offer.company_id,
        performed_by_user_id=user.id,
        units=need.volume_units,
        total_price_rub=total_price,
        status="created",
    )
    offer.status = "selected"
    others = await db.execute(select(Offer).where(Offer.need_id == need.id, Offer.id != offer.id))
    for other in others.scalars():
        other.status = "rejected"
    need.status = "matched"

    db.add(deal)
    if offer.created_by_user_id:
        await notify(db, offer.created_by_user_id, "Ваше предложение выбрано покупателем", "offer_selected")
    await db.commit()
    await db.refresh(deal)
    return deal
