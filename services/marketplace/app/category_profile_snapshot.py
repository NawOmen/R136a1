"""Server-owned technical definitions captured without rewriting legacy data."""
from copy import deepcopy

from .category_registry import registry_snapshot, resolve_category


def capture_category_profile(category: str | None, subcategory: str | None) -> dict | None:
    leaf = resolve_category(category, subcategory)
    if leaf is None:
        return None
    registry = registry_snapshot()
    profile = leaf['technical_profile']
    return {
        'snapshot_version': 1,
        'registry_version': registry['registry_version'],
        'category_id': leaf['id'],
        'leaf_revision': leaf['revision'],
        'profile_version': profile['version'],
        'state': profile['state'],
        'fields': {key: deepcopy(registry['characteristic_fields'][key]) for key in profile['fields']},
        'required_for_product': list(profile['required_for_product']),
    }


def profile_for_insert(context) -> dict | None:
    """Cover API, CSV, seed and other trusted ORM insert paths consistently."""
    values = context.get_current_parameters()
    return capture_category_profile(values.get('category'), values.get('subcategory'))


def profile_after_specification_change(record, category, subcategory, characteristics) -> dict | None:
    previous = (record.category, record.subcategory, record.characteristics)
    if previous == (category, subcategory, characteristics):
        return deepcopy(getattr(record, 'category_profile', None))
    return capture_category_profile(category, subcategory)
