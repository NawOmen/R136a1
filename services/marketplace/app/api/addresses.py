import uuid
import httpx
from ..config import settings
from ..address_limits import reserve_address_request

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_db
from ..deps import CurrentUser, get_current_user, require_company_admin, require_company_buyer
from ..models import DeliveryAddress, Need
from ..schemas import DeliveryAddressIn, DeliveryAddressOut, DeliveryAddressPatch, AddressSuggestionOut

router = APIRouter(prefix="/companies", tags=["addresses"])


async def _require_unreferenced_address(db: AsyncSession, address_id: uuid.UUID) -> None:
    referenced = await db.scalar(select(Need.id).where(Need.delivery_address_id == address_id).limit(1))
    if referenced is not None:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail="Адрес используется в потребности. Создайте новый адрес и измените потребность, "
            "чтобы заново согласовать условия доставки.",
        )


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
    changes = data.model_dump(exclude_unset=True)
    if any(value is None for value in changes.values()):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Поля адреса не могут быть пустыми")
    if any(field in changes and changes[field] != getattr(address, field) for field in ("address", "city", "region")):
        await _require_unreferenced_address(db, address_id)
    if data.is_default:
        await _unset_default(db, company_id)
    for field, value in changes.items():
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
    await _require_unreferenced_address(db, address_id)
    await db.delete(address)
    await db.commit()


@router.get("/{company_id}/address-suggestions", response_model=list[AddressSuggestionOut])
async def suggest_addresses(
    company_id: uuid.UUID,
    query: str = Query(min_length=3, max_length=250),
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """v1: только введённый адрес, без файлов и контекста компании."""
    await require_company_buyer(company_id, user, db)
    if not settings.dadata_api_key:
        raise HTTPException(503, "Подсказки адресов не подключены. Введите адрес вручную или проверьте его на карте.")
    await reserve_address_request(db, company_id)
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            response = await client.post(
                "https://suggestions.dadata.ru/suggestions/api/4_1/rs/suggest/address",
                headers={"Authorization": f"Token {settings.dadata_api_key}"},
                json={"query": query, "count": 5, "locations": [{"country_iso_code": "RU"}], "restrict_value": True},
            )
            response.raise_for_status()
            items = response.json().get("suggestions", [])
            return [
                {"label": item["value"], "address": item["value"],
                 "city": item["data"].get("city") or item["data"].get("settlement") or item["data"].get("region"),
                 "region": item["data"].get("region_with_type"),
                 "house": item["data"].get("house")}
                for item in items if item.get("data", {}).get("country_iso_code") == "RU"
            ]
    except (httpx.HTTPError, ValueError, KeyError, TypeError, AttributeError):
        raise HTTPException(503, "Подсказки временно недоступны. Введите адрес вручную или проверьте его на карте.") from None
