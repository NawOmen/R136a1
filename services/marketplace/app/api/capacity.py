import uuid
from datetime import date

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_db
from ..deps import CurrentUser, get_current_user, require_company_admin, require_company_seller
from ..models import CapacityEntry
from ..resources import lock_company, reservations, occupies
from ..resource_scopes import prepare_conversions, occupied_units, find_leaf
from ..trust import record_human_approval
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
        occupied = sum(occupied_units(row) for row in held if row.capacity_entry_id == entry.id and occupies(row))
        output.append(CapacityEntryOut(date=entry.date, category=entry.category, unit=entry.unit, category_conversions=entry.category_conversions, available_units=entry.available_units, reserved_units=occupied, free_units=max(0, entry.available_units-occupied)))
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
    keys = [(entry.date, entry.category, entry.unit) for entry in data.entries]
    if len(keys) != len(set(keys)):
        raise HTTPException(422, "Ресурс одной категории и единицы не должен повторяться в одном дне")
    dates = [e.date for e in data.entries]
    await lock_company(db, company_id)
    existing = {(row.date, row.category, row.unit): row for row in (await db.scalars(select(CapacityEntry).where(CapacityEntry.company_id == company_id, CapacityEntry.date.in_(dates)))).all()}
    held = await reservations(db, company_id)
    saved_entries = []
    for entry in data.entries:
        if entry.category and not find_leaf(entry.category):
            raise HTTPException(422,"Для отдельной мощности выберите листовую категорию")
        try:
            conversions=prepare_conversions([value.model_dump() for value in entry.category_conversions],entry.conversions_approved)
        except ValueError as exc:
            raise HTTPException(422,str(exc)) from None
        if entry.category:
            leaf=find_leaf(entry.category)
            if leaf['admission_state']=='unsupported' or entry.unit not in leaf['technical_profile']['passport']['units']['allowed']:
                raise HTTPException(422,"Единица или назначение мощности не поддерживается")
            if conversions and any(item['category_id'] != entry.category or item['order_unit'] != entry.unit or item['resource_units_per_order_unit'] != 1 for item in conversions):
                raise HTTPException(422,"Отдельная мощность допускает только свою категорию и пересчёт один к одному")
            conversions=[{'category_id':entry.category,'order_unit':entry.unit,'resource_units_per_order_unit':1,'profile_version':leaf['technical_profile']['version']}]
        current = existing.get((entry.date, entry.category, entry.unit))
        occupied = sum(occupied_units(row) for row in held if current and row.capacity_entry_id == current.id and occupies(row))
        if entry.available_units < occupied:
            raise HTTPException(409, f"На {entry.date} уже распределено {occupied} единиц мощности")
        saved_entries.append(CapacityEntryIn(**{**entry.model_dump(), "category_conversions": conversions}))
        if current:
            current.available_units = entry.available_units
            current.category_conversions = conversions
        else:
            db.add(CapacityEntry(company_id=company_id, date=entry.date, category=entry.category, unit=entry.unit, available_units=entry.available_units, category_conversions=conversions))
    if any(entry.category_conversions for entry in data.entries):
        await record_human_approval(db,action="capacity_conversion_confirmed",entity_type="company",entity_id=company_id,
            actor_user_id=user.id,actor_company_id=company_id,permission="company_admin",decision="approved",
            payload={"entries":[entry.model_dump(mode="json") for entry in saved_entries]},
            explanation="Продавец подтвердил коэффициенты и дневные периоды общего ресурса")
    await run_market_rematch(db, "capacity_changed", company_id)
    await db.commit()
    return saved_entries
