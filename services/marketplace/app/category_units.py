"""Order quantities retain their unit; conversions are exact, explicit and local."""
from decimal import Decimal, InvalidOperation
from .category_registry import normalize_label, resolve_category

UNIT_ALIASES = {
    'шт': ('шт', 'шт.', 'штука', 'штуки', 'штук'),
    'кг': ('кг', 'килограмм', 'килограммы'), 'г': ('г', 'грамм'),
    'т': ('т', 'тонна', 'тонны'), 'м': ('м', 'метр', 'метры'),
    'м²': ('м²', 'м2', 'кв.м', 'кв. м', 'квадратный метр'),
    'м³': ('м³', 'м3', 'куб.м', 'куб. м'), 'л': ('л', 'литр', 'литры'),
    'мл': ('мл', 'миллилитр'), 'рулон': ('рулон', 'рул', 'рул.'),
    'упак': ('упак', 'упак.', 'упаковка', 'упаковки'),
    'мешок': ('мешок','мешки'), 'бухта': ('бухта','бухты'),
    'комплект': ('комплект', 'компл', 'компл.', 'набор'),
}
UNIT_FAMILIES = {'шт':'count','кг':'mass','г':'mass','т':'mass','м':'length','м²':'area',
                 'м³':'volume','л':'volume','мл':'volume','рулон':'roll','упак':'package','комплект':'set','мешок':'package','бухта':'roll','мм':'length','см²':'area','мин':'time','час':'time'}


def canonical_unit(value):
    label = normalize_label(str(value)).rstrip('.')
    for unit, aliases in UNIT_ALIASES.items():
        if label in {normalize_label(alias).rstrip('.') for alias in aliases}:
            return unit
    return label


def order_unit(characteristics):
    values = {normalize_label(str(key)):value for key,value in (characteristics or {}).items()}
    return canonical_unit(values.get('unit') or values.get('единица измерения') or 'шт')


def validate_unit(category, subcategory, characteristics):
    leaf = resolve_category(category, subcategory)
    values = [value for key,value in characteristics.items() if normalize_label(str(key)) in {'unit','единица измерения'}]
    if values and len({canonical_unit(value) for value in values}) > 1:
        return ['Единицы заказа в синонимах противоречат друг другу']
    unit = order_unit(characteristics)
    allowed = leaf['technical_profile'].get('passport', {}).get('units', {}).get('allowed') if leaf else None
    if allowed and unit not in allowed:
        return [f"Для этой категории выберите единицу заказа: {', '.join(allowed)}"]
    return []


def exact_quantity(value, factor):
    """Never round a fractional unit into a physical obligation."""
    try:
        if isinstance(value,bool) or isinstance(factor,bool): raise ValueError
        result = Decimal(str(value).replace(',', '.')) * Decimal(str(factor).replace(',', '.'))
        if not result.is_finite() or result <= 0 or result != result.to_integral_value(): raise ValueError
        return int(result)
    except (InvalidOperation, ValueError):
        raise ValueError('Коэффициент должен давать положительный целый объём без округления') from None
