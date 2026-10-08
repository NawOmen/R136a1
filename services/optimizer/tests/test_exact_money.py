from decimal import Decimal
import uuid
from fastapi import HTTPException
import pytest
from app.schemas import AllocationRequest
from app.solver import optimize_allocations
from fastapi.testclient import TestClient
from app.main import app
from app.security import settings


def request(price,units,budget=None):
    return AllocationRequest.model_validate({'demand_units':units,'deadline_days':3,'budget_rub':budget,
        'producers':[{'company_id':str(uuid.UUID(int=1)),'unit_price_rub':price,'moq_units':1,
                      'capacity_units':units,'lead_time_days':1,'delivery_cost_rub':'0'}]})


def test_cpsat_keeps_subkopeck_prices_and_rounds_complete_line_only():
    for price,units,total in [('0.00000000125',1_000_000_000,'1.25'),('0.005',1,'0.01'),('0.005',2,'0.01')]:
        result=optimize_allocations(request(price,units,total))
        assert len(result.variants)==1
        assert result.variants[0].feasible
        assert result.variants[0].total_cost_rub==Decimal(total)
        assert result.variants[0].allocations[0].unit_price_rub==Decimal(price)


def test_hash_preserves_precision_and_quote_context_and_integer_limits_fail_clearly():
    first=request('150.123456789011',1)
    second=request('150.123456789012',1)
    assert optimize_allocations(first).input_hash!=optimize_allocations(second).input_hash
    first.comparison_context={'quote_revision':2}
    assert optimize_allocations(first).input_hash!=optimize_allocations(second).input_hash
    with pytest.raises(HTTPException) as blocked:optimize_allocations(request('999999999999',2_000_000_000))
    assert blocked.value.status_code==422


def test_versioned_optimizer_wire_exact_strings_and_legacy_numbers():
    client=TestClient(app)
    headers={'X-Optimizer-Token':settings.optimizer_token}
    data=request('0.005',1).model_dump(mode='json')
    exact=client.post('/api/v2/optimize/allocations',headers=headers,json=data)
    legacy=client.post('/api/v1/optimize/allocations',headers=headers,json=data)
    assert exact.status_code==legacy.status_code==200
    assert exact.json()['variants'][0]['total_cost_rub']=='0.01'
    assert legacy.json()['variants'][0]['total_cost_rub']==.01


def test_coalition_distributes_one_kopeck_instead_of_rounding_each_participant_up():
    from app.schemas import CoalitionRequest
    from app.solver import evaluate_coalition
    data={'producer_company_id':str(uuid.UUID(int=10)), 'min_total_units':2,'max_total_units':2,
          'available_capacity_units':2,'production_days':1,'price_tiers':[{'min_units':1,'unit_price_rub':'0.005'}],
          'members':[{'need_id':str(uuid.UUID(int=i)),'buyer_company_id':str(uuid.UUID(int=10+i)),
                      'volume_units':1,'common_base':{},'hard_constraints':{},'deadline_days':2,'delivery_days':0} for i in (1,2)]}
    result=evaluate_coalition(CoalitionRequest.model_validate(data))
    assert result.feasible
    assert [member.common_production_cost_rub for member in result.members]==[Decimal('.01'),Decimal('0')]
    assert sum(member.total_cost_rub for member in result.members)==Decimal('.01')


def test_aggregate_cpsat_objective_bounds_are_rejected_before_model_validation():
    from app.solver import _validate_integer_budget
    model=request('999999999999',2_000_000_000)
    with pytest.raises(HTTPException) as failure:_validate_integer_budget(model.producers,model.demand_units)
    assert failure.value.status_code==422
