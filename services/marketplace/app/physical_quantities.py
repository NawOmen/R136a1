"""API v2 converts reviewed physical quantities into exact integer base units."""
from copy import deepcopy
from decimal import Decimal, InvalidOperation
from .category_units import order_unit, canonical_unit
from .category_registry import registry_snapshot, normalize_label


def decimal_value(value):
    if isinstance(value,bool):raise ValueError('Объём должен быть числом')
    try:
        number=Decimal(str(value).strip().replace(',','.'))
        if not number.is_finite():raise ValueError
        return number
    except (InvalidOperation,ValueError):raise ValueError('Укажите конечное число') from None


def quantity(value,factor, *, zero=False):
    result=decimal_value(value)*factor
    if result<0 or (result==0 and not zero) or result!=result.to_integral_value() or result>2147483647:
        raise ValueError('Объём выходит за допустимую точность или диапазон; округление запрещено')
    return int(result)


def normalize_physical(kind,raw, *, require_approval=True):
    if not isinstance(raw,dict):raise ValueError("Передайте структурированные параметры")
    if not isinstance(raw.get("characteristics",{}),dict):raise ValueError("Характеристики должны быть объектом")
    data=deepcopy(raw)
    aliases=[canonical_unit(value) for key,value in data.get('characteristics',{}).items() if normalize_label(str(key)) in {'unit','единица измерения'}]
    if len(set(aliases)) > 1:raise ValueError('Единицы заказа в синонимах противоречат друг другу')
    unit=order_unit(data.get('characteristics',{}))
    definition=registry_snapshot()['quantity_units'].get(unit,{'base':unit,'factor':1})
    factor=Decimal(definition['factor'])
    if require_approval and factor!=1 and data.get('quantity_conversion_approved') is not True:
        raise ValueError('Просмотрите точный пересчёт в меньшую единицу и подтвердите его')
    data.pop('quantity_conversion_approved',None)
    chars=data.setdefault('characteristics',{})
    for key in list(chars):
        if normalize_label(str(key)) in {'unit','единица измерения'}:chars.pop(key)
    chars['unit']=definition['base']
    qty_keys=['volume_units'] if kind=='need' else ['moq_units','stock_units']
    for key in qty_keys:
        if key in data and data[key] is not None:data[key]=quantity(data[key],factor,zero=key=='stock_units')
    if kind=='product':
        if 'price_rub' in data:
            price=decimal_value(data['price_rub'])/factor
            if price<=0 or price.as_tuple().exponent < -12:raise ValueError('Уточните цену за меньшую единицу; автоматическое округление не выполняется')
            data['price_rub']=price
        for tier in data.get('price_tiers',[]):
            tier['min_units']=quantity(tier['min_units'],factor)
            price=decimal_value(tier['unit_price_rub'])/factor
            if price<=0 or price.as_tuple().exponent < -12:raise ValueError('Цена уровня требует точного пересчёта без округления')
            tier['unit_price_rub']=price
        for key in ('order_multiple','кратность'):
            if key in chars:chars[key]=quantity(chars[key],factor)
    return data,{'input_unit':unit,'stored_unit':definition['base'],'factor':int(factor),
                'quantities':{key:data.get(key) for key in qty_keys if key in data},'price_rub':data.get('price_rub'),'price_tiers':data.get('price_tiers',[])}
