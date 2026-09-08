import uuid

import pytest
from pydantic import ValidationError

from app.experience import classify_cargo, validate_characteristics
from app.schemas import DeliveryArrangementIn


def test_cargo_classification_uses_both_weight_and_volume():
    assert classify_cargo(150, 1)[0] == "small"
    assert classify_cargo(151, 1)[0] == "medium"
    assert classify_cargo(100, 13)[0] == "manual_review"
    assert classify_cargo(100, 15)[0] == "large"
    assert classify_cargo(1501, 1)[0] == "large"


def test_packaging_validator_requires_material_and_cup_volume():
    errors, warnings = validate_characteristics(
        "Упаковка и тара", "Бумажные стаканы", {"цвет": "крафт"}, 5000
    )
    assert "Для упаковки укажите материал" in errors
    assert "Для бумажных стаканов укажите объём" in errors
    assert warnings


def test_packaging_validator_accepts_complete_cup():
    errors, warnings = validate_characteristics(
        "Упаковка и тара", "Бумажные стаканы",
        {"material": "картон", "volume_ml": 400, "coating": "водное"}, 5000,
    )
    assert errors == []
    assert warnings == []


def test_buyer_carrier_requires_carrier_name():
    with pytest.raises(ValidationError, match="перевозчика"):
        DeliveryArrangementIn(
            company_id=uuid.uuid4(), weight_kg=100, volume_m3=0.5,
            method="buyer_carrier", human_approved=True,
        )
