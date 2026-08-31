import uuid
from datetime import date

from fastapi import APIRouter, Depends
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_db
from ..deps import CurrentUser, get_current_user, require_company_admin, require_company_seller
from ..models import CapacityEntry
from ..matching import run_market_rematch
from ..schemas import CapacityEntryIn, CapacityPutIn

router = APIRouter(prefix="/companies", tags=["capacity"])


@router.get("/{company_id}/capacity", response_model=list[CapacityEntryIn])
async def list_capacity(
    company_id: uuid.UUID,
    start: date | None = None,
    end: date | None = None,
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await require_company_seller(company_id, user, db)
    query = select(CapacityEntry).where(CapacityEntry.company_id == company_id)
    if start:
        query = query.where(CapacityEntry.date >= start)
    if end:
        query = query.where(CapacityEntry.date <= end)
    result = await db.execute(query.order_by(CapacityEntry.date))
    return [CapacityEntryIn(date=e.date, available_units=e.available_units) for e in result.scalars().all()]


@router.put("/{company_id}/capacity", response_model=list[CapacityEntryIn])
async def put_capacity(
    company_id: uuid.UUID,
    data: CapacityPutIn,
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await require_company_seller(company_id, user, db)
    await require_company_admin(company_id, user, db)
    dates = [e.date for e in data.entries]
    await db.execute(delete(CapacityEntry).where(CapacityEntry.company_id == company_id, CapacityEntry.date.in_(dates)))
    for entry in data.entries:
        db.add(CapacityEntry(company_id=company_id, date=entry.date, available_units=entry.available_units))
    await run_market_rematch(db, "capacity_changed", company_id)
    await db.commit()
    return data.entries
