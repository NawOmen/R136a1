import uuid
from datetime import date, timedelta

import pytest
from pydantic import ValidationError

from app.experience import classify_cargo, validate_characteristics
from app.schemas import DeliveryArrangementIn
from app.models import Need
from conftest import make_company, make_token, make_user


def test_cargo_classification_uses_both_weight_and_volume():
    assert classify_cargo(150, 1)[0] == "small"
    assert classify_cargo(151, 1)[0] == "medium"
    assert classify_cargo(100, 13)[0] == "manual_review"
    assert classify_cargo(2000, 13)[0] == "manual_review"
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


async def test_repeat_need_is_new_draft_and_retry_is_idempotent(client, db_session):
    user = await make_user(db_session)
    company = await make_company(db_session, user, can_buy=True, can_sell=False)
    original = Need(company_id=company, created_by_user_id=user, category="Электроника",
        characteristics={"model": "А-1"}, volume_units=10, budget_rub=25000,
        deadline_date=date.today() + timedelta(days=10), visibility="open_anonymized", status="matched")
    db_session.add(original)
    await db_session.commit()
    key = str(uuid.uuid4())
    deadline = str(date.today() + timedelta(days=35))
    url = f"/api/v1/needs/{original.id}/repeat"
    headers = {"Authorization": f"Bearer {make_token(user)}"}
    body = {"deadline_date": deadline, "request_key": key}
    created = await client.post(url, json=body, headers=headers)
    assert created.status_code == 201, created.text
    assert created.json()["status"] == "draft"
    assert created.json()["files"] == []
    assert created.json()["id"] != str(original.id)
    assert created.json()["characteristics"] == original.characteristics
    repeated = await client.post(url, json=body, headers=headers)
    assert repeated.status_code == 201
    assert repeated.json()["id"] == created.json()["id"]
    conflict = await client.post(url, json={**body, "deadline_date": str(date.today() + timedelta(days=36))}, headers=headers)
    assert conflict.status_code == 409
