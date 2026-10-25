"""History fixture backfill never rewrites commercial data or refreshes old dates."""
from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace
import uuid

import pytest

from app.assortment import ASSORTMENT
from app.commerce import product_specification_hash
from app.models import Product
from seed_assortment import NAMESPACE, seed_synthetic_price_history, storefront_product_id


def product_and_observation(**changes):
    row = ASSORTMENT[0]
    company_id = uuid.uuid4()
    product = SimpleNamespace(id=storefront_product_id(company_id, row[0]), company_id=company_id,
        name=row[4], category=row[2], subcategory=row[3], characteristics=dict(row[5]), moq_units=row[7],
        price_rub=Decimal(str(row[6])), **changes)
    observation = SimpleNamespace(product_id=product.id, unit_price_rub=product.price_rub,
        specification_hash=product_specification_hash(product), observed_at=datetime(2026, 10, 25, tzinfo=timezone.utc))
    return product, observation


class Store:
    def __init__(self, product, observations):
        self.product, self.observations, self.pending = product, observations, []
    async def scalars(self, statement):
        values = [self.product] if statement.column_descriptions[0]["entity"] is Product else self.observations
        return SimpleNamespace(all=lambda: values)
    def add(self, item): self.pending.append(item)
    async def flush(self):
        self.observations.extend(self.pending); self.pending = []


@pytest.mark.asyncio
async def test_backfill_is_idempotent_and_preserves_anchor_and_original_price():
    product, original = product_and_observation()
    store = Store(product, [original])
    await seed_synthetic_price_history(store)
    assert len(store.observations) == 7
    assert len({o.id for o in store.observations[1:]}) == 6
    assert min(o.observed_at for o in store.observations).isoformat() == "2026-09-13T00:00:00+00:00"
    assert all(o.specification_hash == original.specification_hash for o in store.observations)
    assert product.price_rub == original.unit_price_rub
    await seed_synthetic_price_history(store)
    assert len(store.observations) == 7


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["identity", "price", "specification", "history"])
async def test_nonfixture_and_seller_changes_never_get_fabricated_history(change):
    product, original = product_and_observation()
    observations = [original]
    if change == "identity": product.id = uuid.uuid4()
    elif change == "price": product.price_rub += 1
    elif change == "specification": product.characteristics["material"] = "Изменено продавцом"
    else: observations.append(original)
    store = Store(product, observations)
    await seed_synthetic_price_history(store)
    assert len(store.observations) == (2 if change == "history" else 1)
