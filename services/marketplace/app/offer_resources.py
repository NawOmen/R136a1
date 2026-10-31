"""Read-only, shared resource checks for proposal previews and confirmed edits."""
from datetime import date, datetime, timedelta, timezone
from sqlalchemy import select
from .models import CapacityEntry, Product
from .matching import order_unit
from .resources import reservations, free_stock, occupies
from .resource_scopes import conversion_for, occupied_units
from .commercial import estimate


async def offer_resource(db, need, company_id, resource_kind, product_id=None):
    held = await reservations(db, company_id)
    value = dict(resource_kind=resource_kind, free_units=0, unit=order_unit(need.characteristics),
                 deadline_date=need.deadline_date, stock_updated_at=None, fresh=None, blockers=[])
    if resource_kind == 'stock':
        product = await db.get(Product, product_id) if product_id else None
        if product is None or product.company_id != company_id:
            value['blockers'].append('Выберите товар своей компании на складе')
            return value
        value['free_units'] = await free_stock(db, product, held) if product.stock_units is not None else 0
        value['stock_updated_at'] = product.stock_updated_at
        now = datetime.now(timezone.utc)
        updated = product.stock_updated_at
        value['fresh'] = updated is not None and now - timedelta(days=7) <= updated <= now
        if not value['fresh']:
            value['blockers'].append('Остаток склада не подтверждён за последние 7 дней: обновите наличие товара')
        if product.stock_units is None:
            value['blockers'].append('Количество товара на складе не подтверждено')
    else:
        entries = (await db.scalars(select(CapacityEntry).where(CapacityEntry.company_id == company_id))).all()
        for entry in entries:
            if not date.today() <= entry.date <= need.deadline_date:
                continue
            conversion = conversion_for(entry, need.category, need.subcategory, value['unit'])
            if conversion is None:
                continue
            occupied = sum(occupied_units(row) for row in held if row.capacity_entry_id == entry.id and occupies(row))
            value['free_units'] += max(0, entry.available_units - occupied) // conversion['resource_units_per_order_unit']
    return value


def commercial_send_blockers(data):
    """An explicitly supplied receipt location is required even if a need has an address."""
    result = estimate(units=1, unit_price=data.price_rub, delivery=data.delivery_cost_rub,
                      terms=data.commercial_terms.model_dump() if data.commercial_terms else {},
                      buyer=data.company_id, seller=data.company_id, source={'type': 'offer_send_check'})
    return result['missing']
