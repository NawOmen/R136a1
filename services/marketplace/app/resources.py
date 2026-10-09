"""Shared stock/capacity accounting. All writers hold the same company lock.

Stock is physical on-hand; committed/held rows subtract availability. Shipment
consumes physical stock once. Capacity includes consumed work and cannot be sold
again. A return never silently restocks goods of unknown quality.
"""
from datetime import date, datetime, timedelta, timezone
import uuid

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
    stmt = select(ResourceReservation).where(ResourceReservation.company_id == company_id)
    return list((await db.scalars(stmt.execution_options(populate_existing=True))).all())


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
        # Блокировка не обновляет identity map: товар могли отгрузить после
        # его чтения вызывающей стороной. Перечитываем под блокировкой.
        await db.refresh(product)
        if product.company_id != company_id:
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
        ).order_by(CapacityEntry.date, CapacityEntry.category.desc()).execution_options(populate_existing=True))).all())
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


async def consume(db, *, company_id, anchor_type, anchor_id, units=None):
    """Отгрузка по обязательству: весь объём либо указанная часть.

    Полный вызов сохраняет прежнее поведение (строки переходят в consumed).
    Частичное исполнение уменьшает закреплённый остаток inplace — новые строки
    не создаются, ограничения уникальности anchor/ресурс не нарушаются.
    При частичной отгрузке использованная мощность вычитается из доступности
    в единицах ресурса. Полностью consumed-строка сама занимает мощность,
    поэтому дополнительно вычитать её из доступности нельзя.
    """
    if units is not None and units <= 0:
        raise HTTPException(422, "Количество отгрузки должно быть положительным")
    await lock_company(db, company_id)
    rows = [r for r in await reservations(db, company_id)
            if r.anchor_type == anchor_type and r.anchor_id == anchor_id and r.status == "committed"]
    if units is not None and sum(r.units for r in rows) < units:
        raise HTTPException(409, "Объём отгрузки превышает закреплённое обязательство")
    remaining = units if units is not None else sum(r.units for r in rows)
    consumed = 0
    for row in rows:
        take = min(remaining, row.units)
        if not take:
            break
        coefficient = (row.resource_conversion or {}).get("resource_units_per_order_unit", 1)
        resource_taken = take * coefficient
        if row.product_id:
            product = await db.get(Product, row.product_id)
            await db.refresh(product)
            if product.stock_units is None or product.stock_units < take:
                raise HTTPException(409, "Складской остаток требует сверки перед отгрузкой")
            product.stock_units -= take
            product.stock_updated_at = datetime.now(timezone.utc)
            product.revision += 1
        elif take < row.units:
            entry = await db.get(CapacityEntry, row.capacity_entry_id)
            if entry is None:
                raise HTTPException(409, "Запись мощности требует сверки перед отгрузкой")
            await db.refresh(entry)
            if entry.available_units < resource_taken:
                raise HTTPException(409, "Доступная мощность требует сверки перед отгрузкой")
            entry.available_units -= resource_taken
        if take == row.units:
            row.status = "consumed"
        else:
            resize_reservation(row, row.units - take)
        from .trust import append_audit_event
        await append_audit_event(
            db, event_type="resource_consumed", entity_type="resource_reservation", entity_id=row.id,
            actor_company_id=company_id, source_refs=[{"type": anchor_type, "id": str(anchor_id)}],
            explanation="Зафиксирован фактически использованный ресурс без освобождения исполненного объёма.",
            payload={"anchor_type": anchor_type, "anchor_id": str(anchor_id), "units": take,
                     "resource_units": resource_taken,
                     "product_id": str(row.product_id) if row.product_id else None,
                     "capacity_entry_id": str(row.capacity_entry_id) if row.capacity_entry_id else None},
        )
        consumed += take
        remaining -= take
        if not remaining:
            break
    await db.flush()
    return consumed


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


async def return_stock(db, *, company_id, product_id, units, quality_accepted,
                     return_event_id=None, actor_user_id=None):
    """Возврат на склад только по явному решению о качестве.

    Без подтверждённого качества остаток не увеличивается. Привязка к событию
    возврата (DealExecutionEvent kind=return, status=confirmed) делает повтор
    идемпотентным: второе применение того же события возвращает текущий остаток
    без повторного начисления, а факт фиксируется записью Human Approval.
    Использованный ресурс при этом сохраняется в истории, а не стирается.
    """
    if units <= 0:
        raise HTTPException(422, "Количество возврата должно быть положительным")
    if not quality_accepted:
        raise HTTPException(409, "Возврат не увеличивает доступный склад без проверки качества и явного решения")
    await lock_company(db, company_id)
    from .models import Deal, DealExecutionEvent, HumanApprovalRecord, Need, TrustAuditEvent
    event = await db.get(DealExecutionEvent, return_event_id) if return_event_id else None
    if event is None or event.kind != "return" or event.status != "confirmed":
        raise HTTPException(409, "Возврат на склад возможен только по подтверждённому решению о возврате")
    deal = await db.get(Deal, event.deal_id)
    if deal is None or deal.seller_company_id != company_id or event.units != units:
        raise HTTPException(409, "Событие возврата не соответствует компании или количеству")
    shipment_events = list((await db.scalars(select(TrustAuditEvent).where(
        TrustAuditEvent.event_type == "resource_consumed",
        TrustAuditEvent.actor_company_id == company_id,
        TrustAuditEvent.payload["anchor_type"].astext == "deal",
        TrustAuditEvent.payload["anchor_id"].astext == str(deal.id),
        TrustAuditEvent.payload["product_id"].astext == str(product_id),
    ))).all())
    if shipment_events:
        shipped_units = sum(item.payload["units"] for item in shipment_events)
    else:
        # До появления событий ресурсного исполнения полный consumed-объём
        # известен по ledger; неизвестную частичную историю не выдумываем.
        shipped_units = sum(row.units for row in await reservations(db, company_id)
                            if row.anchor_type == "deal" and row.anchor_id == deal.id
                            and row.product_id == product_id and row.status == "consumed")
    if shipped_units < units:
        raise HTTPException(409, "Товар возврата не соответствует отгруженному складскому ресурсу")
    applied = await db.scalar(select(HumanApprovalRecord).where(
        HumanApprovalRecord.action == "stock_return",
        HumanApprovalRecord.entity_type == "deal_execution_event",
        HumanApprovalRecord.entity_id == return_event_id,
    ))
    product = await db.get(Product, product_id)
    if not product or product.company_id != company_id:
        raise HTTPException(409, "Возврат возможен только на склад своей компании")
    await db.refresh(product)
    if applied is not None:
        return product.stock_units
    from .category_units import canonical_unit
    from .matching import order_unit
    historical = (deal.commercial_snapshot or {}).get("need", {}).get("characteristics")
    if historical is None:
        need = await db.get(Need, deal.need_id)
        historical = need.characteristics if need else {}
    if canonical_unit(order_unit(historical)) != canonical_unit(order_unit(product.characteristics)):
        raise HTTPException(409, "Единица складского товара изменилась после сделки: возврат требует сверки")
    before = product.stock_units
    product.stock_units = (product.stock_units or 0) + units
    product.stock_updated_at = datetime.now(timezone.utc)
    if hasattr(product, "revision"):
        product.revision += 1
    if return_event_id is not None:
        from .trust import record_human_approval
        await record_human_approval(
            db, action="stock_return", entity_type="deal_execution_event", entity_id=return_event_id,
            actor_user_id=actor_user_id, actor_company_id=company_id, permission="company_admin",
            decision="approved", payload={"product_id": str(product_id), "units": units, "before": before, "after": product.stock_units},
            source_refs=[{"type": "deal_execution_event", "id": str(return_event_id)}],
            explanation="Возврат принят на склад после проверки качества; повтор события не начисляет остаток.",
        )
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
    active = [row for row in rows if row.status in {"held", "committed"}]
    seen_resource: dict[tuple, int] = {}
    for row in active:
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
        # Распределение одного заказа по нескольким дням — норма: дублем
        # считается только повтор одного и того же ресурса под одним основанием.
        resource_key = (row.anchor_type, str(row.anchor_id), str(row.product_id), str(row.capacity_entry_id))
        seen_resource[resource_key] = seen_resource.get(resource_key, 0) + 1
    for (anchor_type, anchor_id, _product, _entry), count in seen_resource.items():
        if count > 1:
            issues.append({
                "code": "duplicate_anchor",
                "message": "Одно основание дважды занимает один и тот же ресурс",
                "anchor_type": anchor_type,
                "anchor_id": anchor_id,
            })
    obligations = await _anchor_obligations(db, active, products, entries, company_id=company_id)
    issues.extend(obligation["issue"] for obligation in obligations if obligation["issue"] is not None)
    return {
        "stock": stock,
        "capacity": capacity,
        "issues": issues,
        "obligations": [
            {key: value for key, value in obligation.items() if key != "issue"}
            for obligation in obligations
        ],
    }


async def _anchor_obligations(db, active, products, entries, *, company_id):
    """Основание каждой активной записи: сущность, версия, статус и ресурс.

    Возвращает список обязательств с возможным issue: отсутствующая
    бизнес-сущность (orphan_anchor) либо устаревшее основание
    (stale_obligation) при отменённом обязательстве.
    """
    from .models import Coalition, Deal, ReserveCommitment, ResiliencePlan
    product_names = {p.id: p.name for p in products}
    entry_dates = {e.id: e.date.isoformat() for e in entries}
    grouped: dict[tuple, list] = {}
    for row in active:
        grouped.setdefault((row.anchor_type, str(row.anchor_id)), []).append(row)
    obligations = []
    for (anchor_type, anchor_id), anchor_rows in grouped.items():
        entity = None
        business_status = None
        version = None
        owner_matches = False
        try:
            entity_id = uuid.UUID(anchor_id)
        except (TypeError, ValueError):
            entity_id = None
        if anchor_type == "deal" and entity_id is not None:
            entity = await db.get(Deal, entity_id)
            business_status = entity.status if entity else None
            owner_matches = entity is not None and entity.seller_company_id == company_id
        elif anchor_type == "coalition" and entity_id is not None:
            entity = await db.get(Coalition, entity_id)
            business_status = entity.status if entity else None
            version = entity.version if entity else None
            owner_matches = entity is not None and entity.producer_company_id == company_id
        elif anchor_type == "resilience_primary" and entity_id is not None:
            entity = await db.get(ResiliencePlan, entity_id)
            business_status = entity.status if entity else None
            version = entity.version if entity else None
            owner_matches = entity is not None and any(
                str(item.get("company_id")) == str(company_id) for item in entity.baseline_allocations
            )
        elif anchor_type == "reserve" and entity_id is not None:
            entity = await db.get(ReserveCommitment, entity_id)
            business_status = entity.confirmation_status if entity else None
            owner_matches = entity is not None and entity.company_id == company_id
        else:
            business_status = "unknown_anchor_type"
        issue = None
        if business_status == "unknown_anchor_type":
            issue = {
                "code": "unknown_anchor_type",
                "message": f"Неизвестный тип основания {anchor_type}: связь с обязательством не проверена",
                "anchor_type": anchor_type,
                "anchor_id": anchor_id,
            }
        elif entity is None:
            issue = {
                "code": "orphan_anchor",
                "message": "Ресурс закреплён за отсутствующим обязательством",
                "anchor_type": anchor_type,
                "anchor_id": anchor_id,
            }
        elif not owner_matches:
            issue = {
                "code": "foreign_anchor",
                "message": "Основание не соответствует компании, которой принадлежит ресурс",
                "anchor_type": anchor_type,
                "anchor_id": anchor_id,
            }
            entity, business_status, version = None, None, None
        elif business_status in {"cancelled", "expired", "rejected", "stale"}:
            issue = {
                "code": "stale_obligation",
                "message": f"Основание {business_status}: активные удержания требуют освобождения или нового решения",
                "anchor_type": anchor_type,
                "anchor_id": anchor_id,
            }
        resources = []
        for row in anchor_rows:
            if row.product_id is not None:
                resources.append(f"склад «{product_names.get(row.product_id, '?')}»: {row.units} шт., {row.status}")
            else:
                resources.append(f"мощность {entry_dates.get(row.capacity_entry_id, '?')}: {row.units} ед., {row.status}")
        obligations.append({
            "anchor_type": anchor_type,
            "anchor_id": anchor_id,
            "units": sum(row.units for row in anchor_rows),
            "business_exists": entity is not None,
            "business_status": business_status,
            "business_version": version,
            "resources": resources,
            "issue": issue,
        })
    return obligations
