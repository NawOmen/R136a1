"""Confirmed package equivalents are informational; orders retain their agreed unit."""
from .category_units import order_unit,canonical_unit,UNIT_FAMILIES
from .category_registry import resolve_category
from .trust import payload_hash
from .physical_quantities import decimal_value


def packaging_specification_hash(product):
    return payload_hash({'product_id':str(product.id),'category':product.category,'subcategory':product.subcategory,
                         'characteristics':product.characteristics,'category_profile':product.category_profile})


def packaging_definition(product,target_unit,factor):
    source=order_unit(product.characteristics)
    target=canonical_unit(target_unit)
    leaf=resolve_category(product.category,product.subcategory)
    if leaf is None or leaf['admission_state']=='unsupported':raise ValueError('Выберите поддерживаемую листовую категорию')
    if UNIT_FAMILIES.get(source) not in {'package','roll','set'}:raise ValueError('Коэффициент задаётся для упаковки, рулона или комплекта')
    if target not in leaf['technical_profile']['passport']['units']['allowed'] or UNIT_FAMILIES.get(target) not in {'count','mass','length','area','volume'}:
        raise ValueError('Выберите физическую единицу содержимого, разрешённую для категории')
    if type(factor) is not int or not 0 < factor <= 2147483647:raise ValueError('Укажите положительное целое содержимое в меньшей единице, без округления')
    declared=product.characteristics.get('pack_units',product.characteristics.get('штук в упаковке'))
    if target=='шт' and declared is not None and decimal_value(declared)!=factor:
        raise ValueError('Коэффициент должен совпадать с числом штук в упаковке в спецификации')
    definition = {'from_unit':source,'to_unit':target,'factor':factor,'specification_hash':packaging_specification_hash(product)}
    definition['review_hash'] = payload_hash(definition)
    return definition


def packaging_equivalent(product,quantity):
    proof=getattr(product,'quantity_conversion',None)
    if not proof or proof.get('specification_hash')!=packaging_specification_hash(product):
        raise ValueError('Коэффициент этой спецификации не подтверждён продавцом')
    if type(quantity) is not int or quantity <= 0 or quantity*proof['factor']>2147483647:
        raise ValueError('Объём выходит за допустимый диапазон')
    return {'ordered_quantity':quantity,'ordered_unit':proof['from_unit'],'equivalent_quantity':quantity*proof['factor'],
            'equivalent_unit':proof['to_unit'],'specification_hash':proof['specification_hash'],
            'note':'Эквивалент содержимого. Цена, минимальный заказ, склад и обязательство остаются в согласованной единице товара'}
