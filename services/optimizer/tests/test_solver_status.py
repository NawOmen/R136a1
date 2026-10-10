"""S09.02: решатель различает infeasible и timeout; статусы честно объяснены."""
from datetime import date, timedelta
import uuid

from ortools.sat.python import cp_model

from app.schemas import ResilienceRequest
from app.solver import _solver_status, calculate_resilience


def test_solver_status_mapping_is_explicit():
    assert _solver_status(cp_model.OPTIMAL, 0.1, 10) == "optimal"
    assert _solver_status(cp_model.FEASIBLE, 0.1, 10) == "feasible"
    assert _solver_status(cp_model.INFEASIBLE, 0.1, 10) == "infeasible"
    assert _solver_status(cp_model.UNKNOWN, 10.0, 10) == "timeout"
    assert _solver_status(cp_model.UNKNOWN, 0.01, 10) == "infeasible"


def _hot_reserve(units, price=11):
    return {"company_id": str(uuid.uuid4()), "unit_price_rub": price, "moq_units": 1,
            "capacity_units": units, "lead_time_days": 5, "delivery_cost_rub": 0,
            "additional_cost_rub": 0, "price_tiers": [], "country": "RU", "serves_region": True,
            "reserve_tier": "hot", "confirmation_status": "approved",
            "held_until": str(date.today() + timedelta(days=14))}


def _request(**override):
    company = str(uuid.uuid4())
    payload = {"primary_allocations": [{"company_id": company, "units": 100,
                                        "unit_price_rub": 10, "delivery_cost_rub": 0,
                                        "lead_time_days": 5, "total_cost_rub": 1000}],
               "reserve_options": [], "max_price_increase_pct": 50, "max_delay_days": 30}
    payload.update(override)
    return ResilienceRequest.model_validate(payload)


def test_empty_reserves_are_infeasible_not_timeout():
    result = calculate_resilience(_request())
    scenario = result.scenarios[0]
    assert scenario.solver_status == "infeasible"
    assert scenario.uncovered_units == 100
    assert scenario.new_total_cost_rub is None


def test_covered_scenarios_report_optimal_status():
    result = calculate_resilience(_request(reserve_options=[_hot_reserve(100)]))
    scenario = result.scenarios[0]
    assert scenario.solver_status in ("optimal", "feasible")
    assert scenario.uncovered_units == 0
    assert scenario.cost_comparison_applicable is True
