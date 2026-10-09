"""Shared stock/capacity accounting. All writers hold the same company lock.

Stock is physical on-hand; committed/held rows subtract availability. Shipment
consumes physical stock once. Capacity includes consumed work and cannot be sold
again. A return never silently restocks goods of unknown quality.
"""
from datetime import date, datetime, timedelta, timezone

from fastapi import HTTPException
from sqlalchemy import or_, select

from .models import CapacityEntry, Product, ResourceReservation
from sqlalchemy import text
from .resource_scopes import conversion_for, occupied_units, resize_reservation


async def lock_company(db, company_id):
    await db.execute(text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"), {"key": f"resource:{company_id}"})


def occupies(row, *, stock=False):
    if row.status == "held":
        return row.expires_at is not None and row.expires_at > datetime.now(timezone.utc)
    return row.status == "committed" or (not stock and row.status == "consumed")


async def reservations(db, company_id):
    return list((await db.scalars(select(ResourceReservation).where(ResourceReservation.company_id == company_id))).all())


async def free_stock(db, product, rows=None):
    rows = await reservations(db, product.company_id) if rows is None else rows
    return max(0, (product.stock_units or 0) - sum(row.units for row in rows if row.product_id == product.id and occupies(row, stock=True)))


async def reserve(db, *, company_id, anchor_type, anchor_id, units, deadline, resource_kind="capacity", product_id=None, expires_at=None, start=None, category="", subcategory=None, unit="шт"):
    await lock_company(db, company_id)
    rows = await reservations(db, company_id)
    previous = [row for row in rows if row.anchor_type == anchor_type and row.anchor_id == anchor_id]
    if previous:
        # Reconfirmation is a fresh allocation, never a second hold on the same source.
        for row in previous:
            if row.status == "consumed":
                raise HTTPException(409, "Использованный ресурс нельзя перераспределить")
            await db.delete(row)
        rows = [row for row in rows if row not in previous]
        await db.flush()
    state = "held" if expires_at else "committed"
    allocation = []
    if resource_kind == "stock":
        product = await db.get(Product, product_id) if product_id else None
        if not product or product.company_id != company_id:
            raise HTTPException(409, "Для складского предложения выберите товар своей компании")
        if product.stock_updated_at is None or product.stock_updated_at < datetime.now(timezone.utc) - timedelta(days=7):
            raise HTTPException(409, "Остаток склада не подтверждён за последние 7 дней. Продавцу нужно обновить наличие")
        if await free_stock(db, product, rows) < units:
            raise HTTPException(409, "Свободного остатка недостаточно: часть товара уже зарезервирована")
        allocation.append(ResourceReservation(company_id=company_id, anchor_type=anchor_type, anchor_id=anchor_id, product_id=product.id, units=units, status=state, expires_at=expires_at))
    else:
        entries = list((await db.scalars(select(CapacityEntry).where(
            CapacityEntry.company_id == company_id,
            CapacityEntry.date >= max(date.today(), start or date.today()),
            CapacityEntry.date <= deadline,
        ).order_by(CapacityEntry.date, CapacityEntry.category.desc()))).all())
        remaining = units
        for entry in entries:
            conversion = conversion_for(entry,category,subcategory,unit)
            if conversion is None: continue
            coefficient = conversion["resource_units_per_order_unit"]
            occupied = sum(occupied_units(row) for row in rows if row.capacity_entry_id == entry.id and occupies(row))
            take = min(remaining, max(0, entry.available_units - occupied) // coefficient)
            if take:
                allocation.append(ResourceReservation(company_id=company_id, anchor_type=anchor_type, anchor_id=anchor_id, capacity_entry_id=entry.id, units=take, resource_units=take*coefficient, resource_conversion=conversion, status=state, expires_at=expires_at))
                remaining -= take
            if not remaining: break
        if remaining:
            raise HTTPException(409, f"Свободной мощности к сроку недостаточно. Не распределено {remaining} единиц. Продавцу нужно обновить календарь")
    db.add_all(allocation)
    await db.flush()
    return allocation


async def release(db, *, company_id, anchor_type, anchor_id, units=None):
    await lock_company(db, company_id)
    rows = [r for r in await reservations(db, company_id) if r.anchor_type == anchor_type and r.anchor_id == anchor_id and r.status in {"held", "committed"}]
    remaining = units if units is not None else sum(r.units for r in rows)
    for row in reversed(rows):
        take = min(remaining, row.units)
        if take == row.units:
            row.status = "released"
        elif take:
            resize_reservation(row,row.units-take)
        remaining -= take
        if not remaining: break
    await db.flush()


async def consume(db, *, company_id, anchor_type, anchor_id):
    await lock_company(db, company_id)
    for row in await reservations(db, company_id):
        if row.anchor_type != anchor_type or row.anchor_id != anchor_id or row.status != "committed":
            continue
        if row.product_id:
            product = await db.get(Product, row.product_id)
            if product.stock_units is None or product.stock_units < row.units:
                raise HTTPException(409, "Складской остаток требует сверки перед отгрузкой")
            product.stock_units -= row.units
            product.stock_updated_at = datetime.now(timezone.utc)
            product.revision += 1
        row.status = "consumed"
    await db.flush()


async def activate_hold(db, *, company_id, anchor_id, units):
    await lock_company(db, company_id)
    rows = [r for r in await reservations(db, company_id) if r.anchor_type == "reserve" and r.anchor_id == anchor_id]
    held = [r for r in rows if r.status == "held" and occupies(r, stock=r.product_id is not None)]
    if sum(r.units for r in held) < units:
        raise HTTPException(409, "Резерв истёк или недостаточен: требуется новое подтверждение продавца")
    remaining = units
    for row in held:
        take = min(remaining, row.units)
        if take:
            resize_reservation(row,take)
            row.status, row.expires_at = "committed", None
            remaining -= take
        else:
            row.status = "released"
    await db.flush()
