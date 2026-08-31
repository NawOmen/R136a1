import uuid

from app.main import app
from app.schemas import AllocationRequest, CoalitionRequest, OpportunityScoreIn
from app.solver import calculate_opportunity_score, evaluate_coalition, optimize_allocations


def producer(price, moq, capacity, lead=8, reliability=0.8, delivery=1000, tiers=None):
    return {
        "company_id": str(uuid.uuid4()),
        "unit_price_rub": price,
        "moq_units": moq,
        "capacity_units": capacity,
        "lead_time_days": lead,
        "delivery_cost_rub": delivery,
        "reliability": reliability,
        "price_tiers": tiers or [],
        "serves_region": True,
        "country": "RU",
    }


def coalition_payload(*, second_material="крафт", second_budget=620_000):
    members = [
        {
            "need_id": str(uuid.uuid4()),
            "buyer_company_id": str(uuid.uuid4()),
            "volume_units": 5_000,
            "common_base": {"volume_ml": 400, "material": "крафт", "coating": "PE"},
            "individual_operations": {"logo": "Зёрнышко", "print": "2+0"},
            "hard_constraints": {"food_contact": True},
            "individual_operations_cost_rub": 8_000,
            "delivery_cost_rub": 3_000,
            "budget_rub": 90_000,
            "individual_baseline_cost_rub": 75_000,
            "deadline_days": 14,
        },
        {
            "need_id": str(uuid.uuid4()),
            "buyer_company_id": str(uuid.uuid4()),
            "volume_units": 45_000,
            "common_base": {"volume_ml": 400, "material": second_material, "coating": "PE"},
            "individual_operations": {"logo": "Быстрый кофе", "print": "4+0"},
            "hard_constraints": {"food_contact": True},
            "individual_operations_cost_rub": 15_000,
            "delivery_cost_rub": 12_000,
            "budget_rub": second_budget,
            "individual_baseline_cost_rub": 540_000,
            "deadline_days": 12,
        },
    ]
    return {
        "producer_company_id": str(uuid.uuid4()),
        "min_total_units": 50_000,
        "max_total_units": 60_000,
        "available_capacity_units": 60_000,
        "production_days": 6,
        "price_tiers": [{"min_units": 50_000, "unit_price_rub": 10.9}],
        "members": members,
    }


def test_allocates_between_producers_and_respects_moq():
    data = AllocationRequest.model_validate(
        {
            "demand_units": 120_000,
            "budget_rub": 1_900_000,
            "deadline_days": 10,
            "producers": [
                producer(10.4, 20_000, 70_000, reliability=0.72),
                producer(11.0, 30_000, 60_000, reliability=0.92),
                producer(12.0, 10_000, 40_000, lead=14),
            ],
        }
    )
    result = optimize_allocations(data)
    assert len(result.variants) == 3
    assert all(item.feasible for item in result.variants)
    assert all(item.total_units == 120_000 for item in result.variants)
    assert result.variants[0].total_cost_rub <= result.variants[2].total_cost_rub
    assert result.variants[2].reliability_score >= result.variants[0].reliability_score


def test_infeasible_budget_is_explained():
    result = optimize_allocations(
        AllocationRequest.model_validate(
            {
                "demand_units": 50_000,
                "budget_rub": 100_000,
                "deadline_days": 10,
                "producers": [producer(10, 50_000, 50_000)],
            }
        )
    )
    assert all(not item.feasible for item in result.variants)
    assert "бюджет" in result.variants[0].reasons[0]


def test_volume_discount_is_applied_only_after_tier_threshold():
    result = optimize_allocations(
        AllocationRequest.model_validate(
            {
                "demand_units": 50_000,
                "deadline_days": 10,
                "producers": [
                    producer(
                        12,
                        5_000,
                        60_000,
                        delivery=0,
                        tiers=[{"min_units": 50_000, "unit_price_rub": 10.9}],
                    )
                ],
            }
        )
    )
    cheapest = result.variants[0]
    assert cheapest.feasible is True
    assert cheapest.allocations[0].unit_price_rub == 10.9
    assert cheapest.total_cost_rub == 545_000


def test_compatible_5000_and_45000_form_coalition():
    result = evaluate_coalition(CoalitionRequest.model_validate(coalition_payload()))
    assert result.compatible is True
    assert result.feasible is True
    assert result.combined_volume_units == 50_000
    assert len(result.members) == 2
    assert all(item.total_cost_rub <= 620_000 for item in result.members)


def test_incompatible_or_unprofitable_demand_is_rejected():
    incompatible = evaluate_coalition(
        CoalitionRequest.model_validate(coalition_payload(second_material="пластик"))
    )
    assert incompatible.compatible is False
    assert incompatible.feasible is False

    unprofitable = evaluate_coalition(
        CoalitionRequest.model_validate(coalition_payload(second_budget=100_000))
    )
    assert unprofitable.feasible is False
    assert any("Бюджет" in reason for reason in unprofitable.reasons)


def test_api_health_and_score():
    assert "/health" in app.openapi()["paths"]
    assert "/api/v1/score/opportunity" in app.openapi()["paths"]
    result = calculate_opportunity_score(
        OpportunityScoreIn.model_validate(
            {
            "confirmed_unmet_volume": 1,
            "share_without_feasible_offer": 1,
            "passport_match": 1,
            "moq_and_capacity": 1,
            "logistics": 1,
            "competition_and_saturation": 0,
            "data_quality": 1,
            }
        )
    )
    assert result.score == 95


def test_optimizer_is_reproducible_for_the_same_input():
    request = AllocationRequest.model_validate(
        {
            "demand_units": 80_000,
            "deadline_days": 10,
            "producers": [
                producer(10.4, 20_000, 50_000, reliability=0.75),
                producer(10.8, 20_000, 60_000, reliability=0.9),
            ],
        }
    )
    first = optimize_allocations(request)
    second = optimize_allocations(request)
    assert first.input_hash == second.input_hash
    assert first.variants == second.variants
