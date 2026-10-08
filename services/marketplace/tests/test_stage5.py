from app.money import decimal, amount, money_values
from conftest import confirmed_quote_terms
from conftest import grant_capacity
from datetime import date, timedelta
import uuid

from sqlalchemy import select

from app.models import (
    CapabilityPassport,
    CapacityEntry,
    Coalition,
    CoalitionMember,
    CompatibilityProfile,
    GroupOffer,
    Need,
    ParticipantOrder,
    TrustAuditEvent,
    MarketOpportunity,
)
from app.matching import run_market_rematch
from app.resources import reserve
from conftest import grant_packaging_documents, make_company, make_token, make_user


def auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def passport(client, token, company_id, *, moq=50_000):
    response = await client.put(
        f"/api/v1/companies/{company_id}/capability-passport",
        json={
            "details":{"category_scopes":[{"category_id":"packaging.paper-cups","unit":"шт","min_units":moq,"max_units":60000,"characteristics":{"material":["крафт-картон"],"coating":["PE"],"volume_ml":[400],"food_contact":[True]}}]},
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
    # Групповое обязательство требует подтверждённых документов по категории.
    await grant_packaging_documents(
        db_session, seller_company, decision_user_id=seller_user, confirms={"material": ["крафт-картон"], "coating": ["PE"]}
    )

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
        payload = money_values(payload)
        members = []
        for item in payload["members"]:
            common = amount(item["volume_units"] * decimal("10.9"))
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
                    "benefit_rub": None if item["individual_baseline_cost_rub"] is None else round(decimal(item["individual_baseline_cost_rub"]) - total, 2),
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
    await grant_capacity(db_session, seller_company, 60_000, production_start)
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
                {'commercial_terms': confirmed_quote_terms(),
                    "need_id": need_one["id"],
                    "individual_operations_cost_rub": 8_000,
                    "delivery_cost_rub": 3_000,
                    "individual_baseline_cost_rub": 75_000,
                    "delivery_days": 1,
                },
                {'commercial_terms': confirmed_quote_terms(),
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
    revision = published.json()["version"]

    # Достаточное групповое предложение снимает дефицитную рекомендацию.
    refreshed = await client.get(
        f"/api/v1/companies/{seller_company}/market-opportunities",
        headers=auth(seller_token),
    )
    assert refreshed.json() == []

    first = await client.post(
        f"/api/v1/coalitions/{coalition_id}/decision",
        json={"company_id": str(buyer_one), "decision": "approved", "expected_revision": revision},
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
        json={"company_id": str(buyer_two), "decision": "approved", "expected_revision": revision},
        headers=auth(token_two),
    )
    assert second.status_code == 200
    assert second.json()["status"] == "confirmed"
    orders = (await db_session.execute(select(ParticipantOrder))).scalars().all()
    assert len(orders) == 2
    assert {item.buyer_company_id for item in orders} == {buyer_one, buyer_two}
    event = (await db_session.execute(select(TrustAuditEvent).where(
        TrustAuditEvent.entity_id == uuid.UUID(coalition_id),
        TrustAuditEvent.event_type == "coalition_obligations_checked",
    ))).scalar_one()
    snapshots = {item["need_id"]: item for item in event.payload["participants"]}
    assert set(snapshots) == {need_one["id"], need_two["id"]}
    for original in (need_one, need_two):
        snapshot = snapshots[original["id"]]
        assert snapshot["need_revision"] == original["revision"]
        assert snapshot["admission"]["blocking_open"] == 0
        assert snapshot["admission"]["rules_version"]
        assert snapshot["admission"]["requirements"]
        assert snapshot["admission"]["specification"]["characteristics"] == original["characteristics"]
        assert snapshot["admission"]["specification"]["category_profile"] == original["category_profile"]
    buyer_report = await client.get(f"/api/v1/companies/{buyer_one}/commercial-analytics?role=buyer", headers=auth(token_one))
    assert buyer_report.status_code == 200
    assert buyer_report.json()["group_orders_count"] == 1
    assert buyer_report.json()["orders_count"] == 0
    assert buyer_report.json()["group_orders"][0]["units"] == 5_000
    assert buyer_report.json()["group_orders"][0]["unit"] == "шт"
    assert buyer_report.json()["group_orders"][0]["payments_rub"] is None

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
        json={"company_id": str(first_company), "decision": "rejected", "expected_revision": coalition.version},
        headers=auth(make_token(first_user)),
    )
    assert rejected.status_code == 200
    assert rejected.json()["status"] == "recalculation_required"
    orders = (await db_session.execute(select(ParticipantOrder))).scalars().all()
    assert orders == []
    await db_session.refresh(first_need)
    await db_session.refresh(second_need)
    assert first_need.status == second_need.status == "waiting_for_match"


def test_unknown_specifications_are_not_silently_individual_operations():
    from types import SimpleNamespace
    from app.matching import _need_parts
    need = SimpleNamespace(characteristics={"thread": "M8", "strength_class": "8.8", "color": "чёрный", "logo": "А"})
    common, hard, flexible, individual = _need_parts(need)
    assert common == {"thread": "m8", "strength_class": "8.8", "color": "черный", "unit": "шт"}
    assert individual == {"logo": "а"}


async def test_market_opportunities_do_not_add_rolls_to_pieces(db_session):
    seller = await make_user(db_session)
    company = await make_company(db_session, seller, can_buy=False, can_sell=True)
    db_session.add(CapabilityPassport(company_id=company, details={"category_scopes":[{"category_id":"materials.textile","unit":unit,"profile_version":2,"min_units":1,"characteristics":{}} for unit in ("шт","рулон")]}, technologies=["сырьё и материалы"],
        materials=[], equipment=[], certifications=[], size_ranges={}, delivery_regions=["Москва"],
        completed_order_types=[], min_order_units=1, max_order_units=1000))
    for unit, units in (("шт", 15), ("рулон", 8)):
        buyer = await make_user(db_session)
        buyer_company = await make_company(db_session, buyer, can_buy=True, can_sell=False)
        db_session.add(Need(company_id=buyer_company, created_by_user_id=buyer,
            category="Сырьё и материалы", subcategory="Текстиль", characteristics={"unit": unit}, volume_units=units,
            deadline_date=date.today() + timedelta(days=20), visibility="open_anonymized", status="open_for_offers"))
    await db_session.flush()
    await run_market_rematch(db_session, "test_unit_separation", None)
    opportunities = (await db_session.scalars(select(MarketOpportunity).where(MarketOpportunity.company_id == company))).all()
    assert {(item.unit, item.unmet_volume_units) for item in opportunities} == {("шт", 15), ("рулон", 8)}
    before = {item.unit: item.score for item in opportunities}
    day = date.today() + timedelta(days=1)
    db_session.add(CapacityEntry(company_id=company, date=day, category="materials.textile", unit="шт", category_conversions=[{"category_id":"materials.textile","order_unit":"шт","resource_units_per_order_unit":1,"profile_version":2}], available_units=15))
    await db_session.flush()
    await reserve(db_session, company_id=company, anchor_type="deal", anchor_id=uuid.uuid4(),
                  units=15, deadline=day, category="Сырьё и материалы", subcategory="Текстиль", unit="шт")
    await run_market_rematch(db_session, "test_occupied_capacity", None)
    assert next(item.score for item in opportunities if item.unit == "шт") < before["шт"]
    assert next(item.score for item in opportunities if item.unit == "рулон") == before["рулон"]
