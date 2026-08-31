from datetime import date, timedelta

from sqlalchemy import select

from app.models import (
    Coalition,
    CoalitionMember,
    CompatibilityProfile,
    GroupOffer,
    Need,
    ParticipantOrder,
)
from conftest import make_company, make_token, make_user


def auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def passport(client, token, company_id, *, moq=50_000):
    response = await client.put(
        f"/api/v1/companies/{company_id}/capability-passport",
        json={
            "technologies": ["производство бумажных стаканов"],
            "equipment": ["линия формовки"],
            "materials": ["крафт-картон", "PE"],
            "size_ranges": {"volume_ml": [350, 450]},
            "certifications": ["ТР ТС 005/2011"],
            "min_order_units": moq,
            "max_order_units": 60_000,
            "delivery_regions": ["Москва", "Казань"],
            "completed_order_types": ["бумажные стаканы"],
        },
        headers=auth(token),
    )
    assert response.status_code == 200


async def create_published_need(client, db_session, volume, print_value):
    user = await make_user(db_session)
    company = await make_company(db_session, user, can_buy=True, can_sell=False)
    token = make_token(user)
    created = await client.post(
        "/api/v1/needs",
        json={
            "company_id": str(company),
            "category": "бумажные стаканы",
            "characteristics": {
                "volume_ml": 400,
                "body_material": "крафт-картон",
                "inner_coating": "PE",
                "food_contact": True,
                "print": print_value,
            },
            "volume_units": volume,
            "budget_rub": 90_000 if volume == 5_000 else 620_000,
            "deadline_date": str(date.today() + timedelta(days=30)),
            "valid_until": str(date.today() + timedelta(days=20)),
            "visibility": "open_anonymized",
        },
        headers=auth(token),
    )
    published = await client.post(
        f"/api/v1/needs/{created.json()['id']}/publish", headers=auth(token)
    )
    assert published.status_code == 200
    return user, company, token, published.json()


async def test_5000_and_45000_create_explainable_coalition_and_private_orders(
    client, db_session, monkeypatch
):
    seller_user = await make_user(db_session)
    seller_company = await make_company(
        db_session, seller_user, can_buy=False, can_sell=True
    )
    seller_token = make_token(seller_user)
    await passport(client, seller_token, seller_company)

    _, buyer_one, token_one, need_one = await create_published_need(
        client, db_session, 5_000, "2+0"
    )
    assert need_one["status"] == "waiting_for_match"
    assert "MOQ" in need_one["no_match_reason"]

    _, buyer_two, token_two, need_two = await create_published_need(
        client, db_session, 45_000, "4+0"
    )
    assert need_two["status"] == "coalition_candidate"

    opportunities = await client.get(
        f"/api/v1/companies/{seller_company}/market-opportunities",
        headers=auth(seller_token),
    )
    assert opportunities.status_code == 200
    opportunity = opportunities.json()[0]
    assert opportunity["unmet_volume_units"] == 50_000
    assert opportunity["buyers_count"] == 2
    assert opportunity["score"] > 0

    draft = await client.post(
        f"/api/v1/opportunities/{opportunity['id']}/prepare-offer",
        headers=auth(seller_token),
    )
    assert draft.status_code == 201
    assert draft.json()["status"] == "draft"
    assert draft.json()["price_tiers"] == []

    async def fake_evaluate(payload):
        members = []
        for item in payload["members"]:
            common = round(item["volume_units"] * 10.9, 2)
            total = round(
                common
                + item["individual_operations_cost_rub"]
                + item["delivery_cost_rub"],
                2,
            )
            members.append(
                {
                    "need_id": item["need_id"],
                    "buyer_company_id": item["buyer_company_id"],
                    "units": item["volume_units"],
                    "common_production_cost_rub": common,
                    "individual_operations_cost_rub": item["individual_operations_cost_rub"],
                    "delivery_cost_rub": item["delivery_cost_rub"],
                    "total_cost_rub": total,
                    "baseline_cost_rub": item["individual_baseline_cost_rub"],
                    "benefit_rub": round(item["individual_baseline_cost_rub"] - total, 2),
                    "within_budget": True,
                    "deadline_met": True,
                }
            )
        return {
            "compatible": True,
            "feasible": True,
            "combined_volume_units": 50_000,
            "unit_price_rub": 10.9,
            "members": members,
            "reasons": ["Все обязательные ограничения соблюдены"],
            "input_hash": "synthetic-stage-5",
        }

    monkeypatch.setattr("app.api.market.evaluate_coalition", fake_evaluate)
    production_start = date.today() + timedelta(days=10)
    published = await client.post(
        f"/api/v1/group-offers/{draft.json()['id']}/publish",
        json={
            "min_total_units": 50_000,
            "max_total_units": 60_000,
            "available_capacity_units": 60_000,
            "price_tiers": [{"min_units": 50_000, "unit_price_rub": 10.9}],
            "production_start": str(production_start),
            "production_end": str(production_start + timedelta(days=5)),
            "fill_deadline": str(production_start - timedelta(days=1)),
            "non_fill_rule": "close_without_obligations",
            "participant_terms": [
                {
                    "need_id": need_one["id"],
                    "individual_operations_cost_rub": 8_000,
                    "delivery_cost_rub": 3_000,
                    "individual_baseline_cost_rub": 75_000,
                    "delivery_days": 1,
                },
                {
                    "need_id": need_two["id"],
                    "individual_operations_cost_rub": 15_000,
                    "delivery_cost_rub": 12_000,
                    "individual_baseline_cost_rub": 540_000,
                    "delivery_days": 1,
                },
            ],
        },
        headers=auth(seller_token),
    )
    assert published.status_code == 200
    coalition_id = published.json()["id"]
    assert published.json()["status"] == "awaiting_approvals"

    # Достаточное групповое предложение снимает дефицитную рекомендацию.
    refreshed = await client.get(
        f"/api/v1/companies/{seller_company}/market-opportunities",
        headers=auth(seller_token),
    )
    assert refreshed.json() == []

    first = await client.post(
        f"/api/v1/coalitions/{coalition_id}/decision",
        json={"company_id": str(buyer_one), "decision": "approved"},
        headers=auth(token_one),
    )
    assert first.status_code == 200
    assert first.json()["status"] == "awaiting_approvals"
    orders_before_unanimous_approval = (
        await db_session.execute(select(ParticipantOrder))
    ).scalars().all()
    assert orders_before_unanimous_approval == []

    second = await client.post(
        f"/api/v1/coalitions/{coalition_id}/decision",
        json={"company_id": str(buyer_two), "decision": "approved"},
        headers=auth(token_two),
    )
    assert second.status_code == 200
    assert second.json()["status"] == "confirmed"
    orders = (await db_session.execute(select(ParticipantOrder))).scalars().all()
    assert len(orders) == 2
    assert {item.buyer_company_id for item in orders} == {buyer_one, buyer_two}

    own_view = await client.get("/api/v1/coalitions/mine", headers=auth(token_one))
    foreign_member = next(
        item for item in own_view.json()[0]["members"] if item["buyer_company_id"] is None
    )
    assert foreign_member["total_cost_rub"] is None
    assert foreign_member["individual_operations"] == {}


async def test_rejection_returns_every_need_to_matching_without_orders(client, db_session):
    first_user = await make_user(db_session)
    first_company = await make_company(db_session, first_user, can_buy=True, can_sell=False)
    second_user = await make_user(db_session)
    second_company = await make_company(db_session, second_user, can_buy=True, can_sell=False)

    first_need = Need(
        company_id=first_company,
        category="бумажные стаканы",
        characteristics={"volume_ml": 400},
        volume_units=5_000,
        budget_rub=90_000,
        deadline_date=date.today() + timedelta(days=30),
        valid_until=date.today() + timedelta(days=20),
        status="awaiting_approvals",
    )
    second_need = Need(
        company_id=second_company,
        category="бумажные стаканы",
        characteristics={"volume_ml": 400},
        volume_units=45_000,
        budget_rub=620_000,
        deadline_date=date.today() + timedelta(days=30),
        valid_until=date.today() + timedelta(days=20),
        status="awaiting_approvals",
    )
    profile = CompatibilityProfile(
        category="бумажные стаканы",
        common_base={"volume_ml": 400},
        hard_constraints={},
        flexible_parameters={},
        individual_parts={},
        input_hash="rejection-test-profile",
    )
    db_session.add_all([first_need, second_need, profile])
    await db_session.flush()
    coalition = Coalition(
        compatibility_profile_id=profile.id,
        producer_company_id=None,
        category="бумажные стаканы",
        combined_volume_units=50_000,
        target_moq_units=50_000,
        status="awaiting_approvals",
    )
    db_session.add(coalition)
    await db_session.flush()
    db_session.add_all(
        [
            CoalitionMember(
                coalition_id=coalition.id,
                need_id=first_need.id,
                buyer_company_id=first_company,
                units=5_000,
                total_cost_rub=65_500,
                approval_status="pending",
            ),
            CoalitionMember(
                coalition_id=coalition.id,
                need_id=second_need.id,
                buyer_company_id=second_company,
                units=45_000,
                total_cost_rub=517_500,
                approval_status="approved",
            ),
            GroupOffer(
                coalition_id=coalition.id,
                company_id=second_company,
                min_total_units=50_000,
                max_total_units=50_000,
                price_tiers=[{"min_units": 50_000, "unit_price_rub": 10.9}],
                fill_deadline=date.today() + timedelta(days=5),
                status="preliminary",
                seller_approval_status="approved",
            ),
        ]
    )
    await db_session.commit()

    rejected = await client.post(
        f"/api/v1/coalitions/{coalition.id}/decision",
        json={"company_id": str(first_company), "decision": "rejected"},
        headers=auth(make_token(first_user)),
    )
    assert rejected.status_code == 200
    assert rejected.json()["status"] == "recalculation_required"
    orders = (await db_session.execute(select(ParticipantOrder))).scalars().all()
    assert orders == []
    await db_session.refresh(first_need)
    await db_session.refresh(second_need)
    assert first_need.status == second_need.status == "waiting_for_match"
