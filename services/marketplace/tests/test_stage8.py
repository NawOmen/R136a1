import pytest
from pydantic import ValidationError

from app.schemas import ProductIn


def product(**overrides):
    data = {"name": "Стакан 400 мл", "category": "Упаковка и тара", "subcategory": "Бумажные стаканы", "characteristics": {"объём": "400 мл"}, "price_rub": 12, "price_tiers": [], "moq_units": 100, "lead_time_days": 7}
    data.update(overrides)
    return ProductIn(**data)


def test_product_accepts_25_characteristics():
    assert len(product(characteristics={f"поле-{i}": i for i in range(25)}).characteristics) == 25


def test_product_rejects_26_characteristics():
    with pytest.raises(ValidationError, match="не более 25"):
        product(characteristics={f"поле-{i}": i for i in range(26)})


def test_product_rejects_price_increase_with_volume():
    with pytest.raises(ValidationError, match="не должна расти"):
        product(price_tiers=[{"min_units": 100, "unit_price_rub": 10}, {"min_units": 200, "unit_price_rub": 11}])


def test_product_accepts_volume_discount():
    value = product(price_tiers=[{"min_units": 100, "unit_price_rub": 10}, {"min_units": 200, "unit_price_rub": 8.75}])
    assert value.price_tiers[1].unit_price_rub == 8.75


def test_product_rejects_tier_above_base_price():
    with pytest.raises(ValidationError, match="выше базовой"):
        product(price_tiers=[{"min_units": 100, "unit_price_rub": 13}])
