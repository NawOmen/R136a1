"""Deterministic specification comparison; unknown never scores as agreement."""
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from .category_registry import registry_snapshot, resolve_category, normalize_label
from .category_units import order_unit
from .category_characteristics import _number

_FIELDS = registry_snapshot()['characteristic_fields']
_LEGACY = {'body_material':'material', 'материал корпуса':'material','inner_coating':'coating'}


def canonical_key(key, fields=None):
    key = normalize_label(str(key))
    for name, field in (fields or _FIELDS).items():
        if key in {normalize_label(value) for value in [name, *field['aliases']]}: return name
    return _LEGACY.get(key, key)


def canonical_value(key, value, fields=None):
    field = (fields or _FIELDS).get(key)
    if key == 'unit': return order_unit({'unit':value})
    if field and field['type'] in {'number','integer'}:
        try:
            number = _number(value,field)
            return number if number.is_finite() else ('invalid',str(value))
        except (ValueError,InvalidOperation): return ('invalid',str(value))
    if isinstance(value,str): return ' '.join(normalize_label(value).split())
    if isinstance(value,list):return [canonical_value('',item,{}) for item in value]
    if isinstance(value,dict):return {normalize_label(str(k)):canonical_value('',v,{}) for k,v in value.items()}
    return value


def equal_value(left, right):
    if isinstance(left, bool) or isinstance(right, bool):
        return type(left) is type(right) and left == right
    if isinstance(left, dict) or isinstance(right, dict):
        return isinstance(left, dict) and isinstance(right, dict) and left.keys() == right.keys() and all(equal_value(left[key], right[key]) for key in left)
    if isinstance(left, list) or isinstance(right, list):
        return isinstance(left, list) and isinstance(right, list) and len(left) == len(right) and all(equal_value(a,b) for a,b in zip(left,right))
    if isinstance(left, (int,float,Decimal)) or isinstance(right, (int,float,Decimal)):
        try:
            a,b = Decimal(str(left)),Decimal(str(right))
            return a.is_finite() and b.is_finite() and a == b
        except InvalidOperation:
            return False
    return left == right


def canonical_characteristics(values, fields=None):
    result = {}
    for key,value in (values or {}).items():
        name = canonical_key(key,fields)
        result.setdefault(name,[]).append(canonical_value(name,value,fields))
    result.setdefault('unit',[order_unit(values)])
    return result


@dataclass(frozen=True)
class CompatibilityResult:
    state: str
    reason: str
    category_id: str | None
    product_profile_version: int | None
    need_profile_version: int | None

    @property
    def matches(self): return self.state == 'match'


def compare_specifications(product, need):
    actual_leaf = resolve_category(product.category, getattr(product,'subcategory',None))
    requested_leaf = resolve_category(need.category, getattr(need,'subcategory',None))
    p = getattr(product,'category_profile',None) or {}
    n = getattr(need,'category_profile',None) or {}
    category_id = requested_leaf['id'] if requested_leaf else None
    def result(state,reason):return CompatibilityResult(state,reason,category_id,p.get('profile_version'),n.get('profile_version'))
    if actual_leaf is None or requested_leaf is None:
        return result('unknown','не подтверждена листовая классификация товара или потребности')
    if actual_leaf['id'] != requested_leaf['id']:
        return result('mismatch','подкатегория товара не совпадает с потребностью')
    if p and n and (p.get('category_id'),p.get('profile_version')) != (n.get('category_id'),n.get('profile_version')):
        return result('unknown','версии профиля различаются; сравните изменения и явно примите правила')
    fields = n.get('fields') or p.get('fields') or _FIELDS
    actual = canonical_characteristics(product.characteristics,fields)
    for key, requested in canonical_characteristics(need.characteristics,fields).items():
        supplied = actual.get(key)
        if not supplied or any(value is None or value == '' for value in supplied):
            return result('unknown',f'не подтверждена характеристика «{key}»')
        for value in requested:
            if value is None or value == '': return result('unknown',f'не заполнена характеристика потребности «{key}»')
            if any(not equal_value(candidate, value) for candidate in supplied):
                return result('mismatch',f'характеристика «{key}» не совпадает')
    multiple = product.characteristics.get('order_multiple', product.characteristics.get('кратность',1))
    try:
        if isinstance(multiple, bool) or Decimal(str(multiple)) != Decimal(str(multiple)).to_integral_value():
            return result("unknown", "не подтверждена целая кратность заказа")
        if int(multiple) < 1 or need.volume_units % int(multiple):
            return result('mismatch','объём не соблюдает кратность заказа товара')
    except (ValueError,TypeError,InvalidOperation):return result('unknown','не подтверждена кратность заказа')
    return result('match','')
