"""Reviewable profile updates, including genuinely unknown legacy provenance."""
from .category_profile_snapshot import capture_category_profile
from .trust import payload_hash

SECTION_LABELS = {'identification':'Идентификация','units':'Единицы заказа','producer':'Производитель',
 'commercial':'Коммерческие условия','resource':'Ресурс','documents':'Доказательства',
 'compatibility':'Совместимость','logistics':'Доставка','acceptance':'Приёмка','repeat':'Повтор',
 'sources':'Источники','update_policy':'Обновление правил'}


def revision_preview(record):
    previous = getattr(record,'category_profile',None)
    current = capture_category_profile(record.category,record.subcategory)
    changes = []
    old_fields = (previous or {}).get('fields',{})
    new_fields = (current or {}).get('fields',{})
    for key in sorted(old_fields.keys() | new_fields.keys()):
        before, after = old_fields.get(key),new_fields.get(key)
        if before != after:
            changes.append({'label':(after or before)['label'],'kind':'added' if before is None else 'removed' if after is None else 'changed',
                            'before':before,'after':after})
    old_required = (previous or {}).get('required_for_product',[])
    new_required = (current or {}).get('required_for_product',[])
    if old_required != new_required:
        changes.append({'label':'Обязательные характеристики','kind':'changed',
           'before':[(old_fields.get(key) or {}).get('label',key) for key in old_required],
           'after':[(new_fields.get(key) or {}).get('label',key) for key in new_required]})
    for key,label in SECTION_LABELS.items():
        before,after=(previous or {}).get('passport',{}).get(key),(current or {}).get('passport',{}).get(key)
        if before != after: changes.append({'label':label,'kind':'changed','before':before,'after':after})
    same_profile = previous is not None and current is not None and {key:value for key,value in previous.items() if key != 'registry_version'} == {key:value for key,value in current.items() if key != 'registry_version'}
    return {'state':'unclassified' if current is None else 'unknown' if previous is None else 'current' if same_profile else 'update_available',
            'expected_specification_hash':payload_hash({'category':record.category,'subcategory':record.subcategory,'characteristics':record.characteristics,'quantity':getattr(record,'volume_units',getattr(record,'moq_units',None))}),
            'expected_snapshot_hash':payload_hash(previous),'expected_current_hash':payload_hash(current),
            'previous':previous,'current':current,'changes':changes}
