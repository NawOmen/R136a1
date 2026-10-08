"""Explicit daily resource coefficients; historic reservations keep their own copy."""
from .category_registry import registry_snapshot, resolve_category
from .category_units import canonical_unit


def find_leaf(identifier):
    return next((leaf for group in registry_snapshot()['groups'] for leaf in group['leaves'] if leaf['id'] == identifier),None)


def prepare_conversions(values, approved):
    if values and approved is not True:
        raise ValueError('Подтвердите коэффициенты расхода ресурса для выбранного дня')
    result=[]
    for raw in values:
        item=dict(raw)
        leaf=find_leaf(item['category_id'])
        if leaf is None or leaf['admission_state']=='unsupported':
            raise ValueError('Выберите поддерживаемую листовую категорию ресурса')
        unit=canonical_unit(item['order_unit'])
        if unit not in leaf['technical_profile']['passport']['units']['allowed']:
            raise ValueError('Единица заказа не соответствует категории')
        item.update(order_unit=unit,profile_version=leaf['technical_profile']['version'])
        if any(previous['category_id']==item['category_id'] and previous['order_unit']==unit for previous in result):
            raise ValueError('Повторяющийся коэффициент категории и единицы')
        result.append(item)
    return result


def conversion_for(entry, category, subcategory, unit):
    leaf=resolve_category(category,subcategory)
    if leaf is None: return None
    unit=canonical_unit(unit)
    declared=getattr(entry,'category_conversions',None) or []
    for item in declared:
        if (item['category_id'],item['order_unit'],item['profile_version']) == (leaf['id'],unit,leaf['technical_profile']['version']):
            return {**item,'resource_unit':entry.unit,'period_date':entry.date.isoformat(),'resource_key':str(getattr(entry,'id','unpersisted'))}
    return None


def occupied_units(row):
    value=getattr(row,'resource_units',None)
    return row.units if value is None else value


def resize_reservation(row, units):
    coefficient=(getattr(row,'resource_conversion',None) or {}).get('resource_units_per_order_unit',1)
    row.units=units
    if getattr(row,'resource_units',None) is not None: row.resource_units=units*coefficient
