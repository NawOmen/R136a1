import uuid
from datetime import date

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_db
from ..deps import CurrentUser, get_current_user, require_company_admin, require_company_seller
from ..models import CapacityEntry
from ..resources import lock_company, reservations, occupies
from ..matching import run_market_rematch
from ..schemas import CapacityEntryIn, CapacityEntryOut, CapacityPutIn

router = APIRouter(prefix="/companies", tags=["capacity"])


@router.get("/{company_id}/capacity", response_model=list[CapacityEntryOut])
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
    held = await reservations(db, company_id)
    output = []
    for entry in result.scalars().all():
        occupied = sum(row.units for row in held if row.capacity_entry_id == entry.id and occupies(row))
        output.append(CapacityEntryOut(date=entry.date, available_units=entry.available_units, reserved_units=occupied, free_units=max(0, entry.available_units-occupied)))
    return output


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
    await lock_company(db, company_id)
    existing = {row.date: row for row in (await db.scalars(select(CapacityEntry).where(CapacityEntry.company_id == company_id, CapacityEntry.date.in_(dates)))).all()}
    held = await reservations(db, company_id)
    for entry in data.entries:
        current = existing.get(entry.date)
        occupied = sum(row.units for row in held if current and row.capacity_entry_id == current.id and occupies(row))
        if entry.available_units < occupied:
            raise HTTPException(409, f"На {entry.date} уже распределено {occupied} единиц мощности")
        if current:
            current.available_units = entry.available_units
        else:
            db.add(CapacityEntry(company_id=company_id, date=entry.date, available_units=entry.available_units))
    await run_market_rematch(db, "capacity_changed", company_id)
    await db.commit()
    return data.entries
