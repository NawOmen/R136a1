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
    if not rows:
        return 0
    remaining = units if units is not None else sum(r.units for r in rows)
    released = 0
    for row in reversed(rows):
        take = min(remaining, row.units)
        if take == row.units:
            row.status = "released"
            released += take
        elif take:
            resize_reservation(row,row.units-take)
            released += take
        remaining -= take
        if not remaining: break
    await db.flush()
    return released


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
            if hasattr(product, "revision"):
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


async def free_capacity_for_entry(db, entry, rows=None):
    """Свободная мощность дневной записи: доступность минус занятое."""
    if rows is None:
        rows = await reservations(db, entry.company_id)
    occupied = sum(occupied_units(row) for row in rows if row.capacity_entry_id == entry.id and occupies(row))
    return max(0, entry.available_units - occupied)


async def sweep_expired_holds(db, *, company_id):
    """Идемпотентно освобождает просроченные удержания held.

    Повторный вызов без новых просрочек возвращает 0 и ничего не меняет.
    """
    await lock_company(db, company_id)
    now = datetime.now(timezone.utc)
    swept = 0
    for row in await reservations(db, company_id):
        if row.status == "held" and row.expires_at is not None and row.expires_at <= now:
            row.status = "released"
            swept += 1
    await db.flush()
    return swept


async def return_stock(db, *, company_id, product_id, units, quality_accepted):
    """Возврат на склад только по явному решению о качестве.

    Без подтверждённого качества остаток не увеличивается: требуется отдельное
    решение ответственного. Повторный вызов с тем же смыслом выполняется
    вызывающей стороной отдельным согласованным действием, а не автоматически.
    """
    if units <= 0:
        raise HTTPException(422, "Количество возврата должно быть положительным")
    if not quality_accepted:
        raise HTTPException(409, "Возврат не увеличивает доступный склад без проверки качества и явного решения")
    await lock_company(db, company_id)
    product = await db.get(Product, product_id)
    if not product or product.company_id != company_id:
        raise HTTPException(409, "Возврат возможен только на склад своей компании")
    product.stock_units = (product.stock_units or 0) + units
    product.stock_updated_at = datetime.now(timezone.utc)
    if hasattr(product, "revision"):
        product.revision += 1
    await db.flush()
    return product.stock_units


async def reconcile_company(db, *, company_id):
    """Сверка ledger компании: занятость, свежесть и расхождения.

    Только чтение, ничего не исправляет. Исправление выполняет отдельный
    контролируемый вызов (sweep_expired_holds / repair), а не молчаливая правка.
    """
    rows = await reservations(db, company_id)
    products = list((await db.scalars(select(Product).where(Product.company_id == company_id))).all())
    entries = list((await db.scalars(select(CapacityEntry).where(CapacityEntry.company_id == company_id))).all())
    now = datetime.now(timezone.utc)
    issues: list[dict] = []
    stock = []
    for product in products:
        held_committed = sum(
            row.units for row in rows
            if row.product_id == product.id and occupies(row, stock=True)
        )
        free = max(0, (product.stock_units or 0) - held_committed)
        stale = product.stock_updated_at is None or product.stock_updated_at < now - timedelta(days=7)
        if (product.stock_units or 0) - held_committed < 0:
            issues.append({
                "code": "negative_stock",
                "message": f"По товару «{product.name}» занято больше физического остатка",
                "product_id": str(product.id),
            })
        stock.append({
            "product_id": str(product.id),
            "name": product.name,
            "on_hand": product.stock_units,
            "occupied": held_committed,
            "free": free,
            "stale": stale,
            "stock_updated_at": product.stock_updated_at.isoformat() if product.stock_updated_at else None,
        })
    capacity = []
    for entry in entries:
        occupied = sum(occupied_units(row) for row in rows if row.capacity_entry_id == entry.id and occupies(row))
        free = max(0, entry.available_units - occupied)
        if entry.available_units - occupied < 0:
            issues.append({
                "code": "negative_capacity",
                "message": f"На {entry.date} распределено больше доступной мощности",
                "capacity_entry_id": str(entry.id),
            })
        capacity.append({
            "capacity_entry_id": str(entry.id),
            "date": entry.date.isoformat(),
            "available": entry.available_units,
            "occupied": occupied,
            "free": free,
        })
    product_ids = {p.id for p in products}
    entry_ids = {e.id for e in entries}
    active_by_anchor: dict[tuple, int] = {}
    for row in rows:
        if row.product_id is not None and (row.product_id not in product_ids or row.company_id != company_id):
            issues.append({
                "code": "orphan_reservation",
                "message": "Удержание ссылается на отсутствующий товар своей компании",
                "reservation_id": str(row.id),
            })
        if row.capacity_entry_id is not None and row.capacity_entry_id not in entry_ids:
            issues.append({
                "code": "orphan_reservation",
                "message": "Удержание ссылается на отсутствующую запись мощности",
                "reservation_id": str(row.id),
            })
        if row.status == "held" and row.expires_at is not None and row.expires_at <= now:
            issues.append({
                "code": "expired_hold",
                "message": "Просроченное удержание ещё числится held; требуется контролируемое освобождение",
                "reservation_id": str(row.id),
            })
        if row.status in {"held", "committed"}:
            key = (row.anchor_type, str(row.anchor_id))
            active_by_anchor[key] = active_by_anchor.get(key, 0) + 1
    for (anchor_type, anchor_id), count in active_by_anchor.items():
        if count > 1 and anchor_type == "deal":
            issues.append({
                "code": "duplicate_anchor",
                "message": "По одному обязательству числится несколько активных удержаний",
                "anchor_type": anchor_type,
                "anchor_id": anchor_id,
            })
    return {"stock": stock, "capacity": capacity, "issues": issues}
