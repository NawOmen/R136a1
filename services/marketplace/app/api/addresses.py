import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_db
from ..deps import CurrentUser, get_current_user, require_company_admin, require_company_buyer
from ..models import DeliveryAddress
from ..schemas import DeliveryAddressIn, DeliveryAddressOut, DeliveryAddressPatch

router = APIRouter(prefix="/companies", tags=["addresses"])


async def _unset_default(db: AsyncSession, company_id: uuid.UUID) -> None:
    await db.execute(
        DeliveryAddress.__table__.update()
        .where(DeliveryAddress.company_id == company_id)
        .values(is_default=False)
    )


@router.get("/{company_id}/addresses", response_model=list[DeliveryAddressOut])
async def list_addresses(
    company_id: uuid.UUID,
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await require_company_buyer(company_id, user, db)
    result = await db.execute(
        select(DeliveryAddress).where(DeliveryAddress.company_id == company_id).order_by(DeliveryAddress.created_at)
    )
    return result.scalars().all()


@router.post("/{company_id}/addresses", response_model=DeliveryAddressOut, status_code=status.HTTP_201_CREATED)
async def create_address(
    company_id: uuid.UUID,
    data: DeliveryAddressIn,
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await require_company_buyer(company_id, user, db)
    await require_company_admin(company_id, user, db)
    if data.is_default:
        await _unset_default(db, company_id)
    address = DeliveryAddress(company_id=company_id, **data.model_dump())
    db.add(address)
    await db.commit()
    await db.refresh(address)
    return address


@router.patch("/{company_id}/addresses/{address_id}", response_model=DeliveryAddressOut)
async def update_address(
    company_id: uuid.UUID,
    address_id: uuid.UUID,
    data: DeliveryAddressPatch,
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await require_company_buyer(company_id, user, db)
    await require_company_admin(company_id, user, db)
    address = await db.get(DeliveryAddress, address_id)
    if address is None or address.company_id != company_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Адрес не найден")
    if data.is_default:
        await _unset_default(db, company_id)
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(address, field, value)
    await db.commit()
    await db.refresh(address)
    return address


@router.delete("/{company_id}/addresses/{address_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_address(
    company_id: uuid.UUID,
    address_id: uuid.UUID,
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await require_company_buyer(company_id, user, db)
    await require_company_admin(company_id, user, db)
    address = await db.get(DeliveryAddress, address_id)
    if address is None or address.company_id != company_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Адрес не найден")
    await db.delete(address)
    await db.commit()
