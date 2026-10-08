from decimal import Decimal, ROUND_FLOOR
from fastapi import HTTPException
from .money import EXACT_WIRE, MAX_AMOUNT, decimal, amount
import hashlib
import json
from datetime import date
from itertools import combinations

from ortools.sat.python import cp_model

from .schemas import (
    Allocation,
    AllocationRequest,
    CoalitionMemberResult,
    CoalitionRequest,
    CoalitionResponse,
    OptimizationResponse,
    OptimizationVariant,
    OpportunityScoreIn,
    OpportunityScoreOut,
    ReplacementAllocation,
    ReserveOptionIn,
    ResilienceRequest,
    ResilienceResponse,
    FailureScenarioOut,
)


VARIANT_TITLES = {
    "cheapest": "Дешевле",
    "balanced": "Сбалансированный",
    "reliable": "Надёжнее",
}


def _input_hash(value) -> str:
    token = EXACT_WIRE.set(True)
    try:payload = value.model_dump(mode='json')
    finally:EXACT_WIRE.reset(token)
    payload = {'money_contract_version':2,'request':payload}
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode()).hexdigest()


def _validate_integer_budget(producers,demand):
    # Bound every tier domain, not just a feasible allocation. CP-SAT validates
    # inactive domains too. Integer arithmetic avoids intermediate rounding.
    bound = 0
    for producer in producers:
        upper = min(producer.capacity_units,demand)
        prices = [producer.unit_price_rub,*[tier.unit_price_rub for tier in producer.price_tiers]]
        for price in prices:
            numerator, denominator = decimal(price).as_integer_ratio()
            cents = (numerator*upper*100 + denominator//2)//denominator
            bound += cents + 10_000_000*upper
        bound += int(producer.delivery_cost_rub*100)+int(producer.additional_cost_rub*100)
    if bound>2**61:raise HTTPException(422,'Суммарные коэффициенты выходят за целочисленные границы расчётчика')


def _line_kopecks(model, price, units, upper, name):
    """Exact CP-SAT amount: HALF_UP only after multiplying the whole line.

    Dynamic decimal scale <=10^12; numerator and total objectives <=2^61.
    Reject out-of-range requests instead of truncating a sub-kopeck price.
    """
    price = decimal(price).normalize()
    scale = 10 ** max(0, -price.as_tuple().exponent)
    coefficient = int(price * scale) * 100
    bound = coefficient * upper + scale // 2
    if scale > 10**12 or bound > 2**61:
        raise HTTPException(422, 'Цена и объём выходят за точные целочисленные границы расчётчика')
    cents = model.new_int_var(0, int(amount(price * upper) * 100), name)
    model.add_division_equality(cents, coefficient * units + scale // 2, scale)
    return cents


def _solve_variant(request: AllocationRequest, kind: str) -> OptimizationVariant:
    producers = sorted(request.producers, key=lambda item: str(item.company_id))
    eligible = [
        item
        for item in producers
        if item.country == "RU" and item.serves_region and item.lead_time_days <= request.deadline_days
    ]
    if not eligible:
        return OptimizationVariant(
            kind=kind,
            title=VARIANT_TITLES[kind],
            feasible=False,
            reasons=["Нет российского производителя, соблюдающего регион и срок"],
        )

    reliability_known = all(item.reliability is not None for item in eligible)
    _validate_integer_budget(eligible,request.demand_units)
    model = cp_model.CpModel()
    allocations = []
    producer_tiers = []
    total_cost_terms = []
    objective_terms = []
    for index, producer in enumerate(eligible):
        tier_prices = {producer.moq_units: producer.unit_price_rub}
        for tier in producer.price_tiers:
            if tier.min_units <= producer.capacity_units:
                tier_prices[max(producer.moq_units, tier.min_units)] = tier.unit_price_rub
        tiers = sorted(tier_prices.items())
        tier_variables = []
        tier_used = []
        for tier_index, (minimum, price) in enumerate(tiers):
            upper = min(producer.capacity_units, request.demand_units)
            if tier_index + 1 < len(tiers):
                upper = min(upper, tiers[tier_index + 1][0] - 1)
            if upper < minimum:
                continue
            tier_units = model.new_int_var(0, upper, f"units_{index}_{tier_index}")
            selected = model.new_bool_var(f"selected_{index}_{tier_index}")
            model.add(tier_units >= minimum * selected)
            model.add(tier_units <= upper * selected)
            tier_variables.append((tier_units, price))
            tier_used.append(selected)
            line_kopecks = _line_kopecks(model, price, tier_units, upper, f"cost_{index}_{tier_index}")
            reliability_penalty = round((1 - producer.reliability) * 1000) if reliability_known else 0
            total_cost_terms.append(line_kopecks)
            if kind == "cheapest":
                objective_terms.append(line_kopecks)
            elif kind == "balanced":
                objective_terms.append(line_kopecks + reliability_penalty * 2 * tier_units)
            else:
                objective_terms.append(
                    reliability_penalty * 10_000 * tier_units + line_kopecks
                )
        model.add(sum(tier_used) <= 1)
        units = model.new_int_var(0, producer.capacity_units, f"units_{index}")
        model.add(units == sum(variable for variable, _ in tier_variables))
        allocations.append(units)
        producer_tiers.append((tier_variables, tier_used))
        delivery_kopecks = int(amount(producer.delivery_cost_rub + producer.additional_cost_rub) * 100)
        total_cost_terms.append(delivery_kopecks * sum(tier_used))
        objective_terms.append(delivery_kopecks * sum(tier_used))

    model.add(sum(allocations) == request.demand_units)
    model.add(sum(total_cost_terms) <= int(MAX_AMOUNT*100))
    if request.budget_rub is not None:
        model.add(sum(total_cost_terms) <= int(amount(request.budget_rub) * 100))
    model.minimize(sum(objective_terms))

    solver = cp_model.CpSolver()
    solver.parameters.num_search_workers = 1
    solver.parameters.random_seed = 0
    solver.parameters.max_time_in_seconds = 10
    status = solver.solve(model)
    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        return OptimizationVariant(
            kind=kind,
            title=VARIANT_TITLES[kind],
            feasible=False,
            reasons=["Не найдено распределение, соблюдающее MOQ, мощность, бюджет и срок"],
        )

    result = []
    for producer, variable, tier_data in zip(eligible, allocations, producer_tiers, strict=True):
        units = solver.value(variable)
        if units <= 0:
            continue
        tier_variables, tier_used = tier_data
        selected_prices = [
            price
            for (_, price), selected in zip(tier_variables, tier_used, strict=True)
            if solver.value(selected)
        ]
        unit_price = selected_prices[0]
        production = amount(units * unit_price)
        total = amount(production + producer.delivery_cost_rub + producer.additional_cost_rub)
        result.append(
            Allocation(
                company_id=producer.company_id,
                units=units,
                unit_price_rub=unit_price,
                production_cost_rub=production,
                delivery_cost_rub=producer.delivery_cost_rub,
                additional_cost_rub=producer.additional_cost_rub,
                total_cost_rub=total,
                lead_time_days=producer.lead_time_days,
                reliability=producer.reliability,
            )
        )
    total_cost = amount(sum(item.total_cost_rub for item in result))
    weighted_reliability = (sum(item.units * item.reliability for item in result) / request.demand_units
                            if all(item.reliability is not None for item in result) else None)
    return OptimizationVariant(
        kind=kind,
        title=VARIANT_TITLES[kind] if reliability_known or kind == "cheapest" else "По цене: надёжность не подтверждена",
        feasible=True,
        allocations=result,
        total_units=sum(item.units for item in result),
        total_cost_rub=total_cost,
        max_lead_time_days=max(item.lead_time_days for item in result),
        reliability_score=round(weighted_reliability, 4) if weighted_reliability is not None else None,
        reasons=["Все обязательные ограничения соблюдены детерминированным решателем"]
        + ([] if reliability_known else ["Для сравнения надёжности недостаточно подтверждённых данных. Варианты рассчитаны по цене без рейтингового преимущества"]),
    )


def optimize_allocations(request: AllocationRequest) -> OptimizationResponse:
    variants = []
    seen = set()
    for kind in ('cheapest', 'balanced', 'reliable'):
        variant = _solve_variant(request, kind)
        signature = (variant.feasible,tuple((str(item.company_id), item.units, item.unit_price_rub) for item in variant.allocations),
                     tuple(variant.reasons) if not variant.feasible else ())
        if signature in seen:
            continue
        seen.add(signature)
        variants.append(variant)
    return OptimizationResponse(variants=variants, input_hash=_input_hash(request))


def evaluate_coalition(request: CoalitionRequest) -> CoalitionResponse:
    digest = _input_hash(request)
    reasons: list[str] = []
    total_units = sum(item.volume_units for item in request.members)
    if request.producer_country != "RU":
        reasons.append("Производство должно находиться на территории России")
    first = request.members[0]
    for member in request.members[1:]:
        if member.common_base != first.common_base:
            reasons.append("Не совпадает общая производственная основа")
        if member.hard_constraints != first.hard_constraints:
            reasons.append("Не совпадают жёсткие обязательные ограничения")
    compatible = not any("совпад" in reason for reason in reasons)
    if total_units < request.min_total_units:
        reasons.append("Общий объём не достигает MOQ группового предложения")
    if total_units > request.max_total_units:
        reasons.append("Общий объём превышает максимум группового предложения")
    if total_units > request.available_capacity_units:
        reasons.append("Недостаточно подтверждённой производственной мощности")

    tiers = sorted(request.price_tiers, key=lambda item: item.min_units)
    applicable = [item for item in tiers if total_units >= item.min_units]
    if not applicable:
        reasons.append("Нет ценовой ступени для общего объёма")
        unit_price = None
    else:
        unit_price = applicable[-1].unit_price_rub

    member_results = []
    if unit_price is not None:
        cents = int(amount(total_units * unit_price) * 100)
        shares = {member.need_id: Decimal(cents)*member.volume_units/total_units for member in request.members}
        allocated = {key:int(value.to_integral_value(rounding=ROUND_FLOOR)) for key,value in shares.items()}
        ordered = sorted(shares, key=lambda key: (-(shares[key]-allocated[key]),str(key)))
        for key in ordered[:cents-sum(allocated.values())]: allocated[key] += 1
        for member in request.members:
            common_cost = Decimal(allocated[member.need_id])/100
            total_cost = amount(common_cost
                + member.individual_operations_cost_rub
                + member.delivery_cost_rub)
            if total_cost>MAX_AMOUNT:raise HTTPException(422,'Смета участника выходит за денежный диапазон платформы')
            within_budget = member.budget_rub is None or total_cost <= member.budget_rub
            deadline_met = request.production_days + member.delivery_days <= member.deadline_days
            benefit = (
                None
                if member.individual_baseline_cost_rub is None
                else amount(member.individual_baseline_cost_rub - total_cost)
            )
            member_results.append(
                CoalitionMemberResult(
                    need_id=member.need_id,
                    buyer_company_id=member.buyer_company_id,
                    units=member.volume_units,
                    common_production_cost_rub=common_cost,
                    individual_operations_cost_rub=member.individual_operations_cost_rub,
                    delivery_cost_rub=member.delivery_cost_rub,
                    total_cost_rub=total_cost,
                    baseline_cost_rub=member.individual_baseline_cost_rub,
                    benefit_rub=benefit,
                    within_budget=within_budget,
                    deadline_met=deadline_met,
                )
            )
            if not within_budget:
                reasons.append(f"Бюджет участника {member.need_id} превышен")
            if not deadline_met:
                reasons.append(f"Срок участника {member.need_id} не соблюдён")


    feasible = compatible and unit_price is not None and not reasons
    if feasible:
        reasons.append("MOQ, мощность, совместимость и сроки подтверждены")
        if all(member.individual_baseline_cost_rub is not None for member in request.members):
            reasons.append("Сравнение каждого участника выполнено относительно подтверждённого сопоставимого КП; отрицательная разница означает отсутствие экономии")
        else:
            reasons.append("Выгода не подтверждена для участников без индивидуальной альтернативы; сравните одинаковые условия до принятия решения")
    return CoalitionResponse(
        compatible=compatible,
        feasible=feasible,
        combined_volume_units=total_units,
        unit_price_rub=unit_price,
        members=member_results,
        reasons=reasons,
        input_hash=digest,
    )


def calculate_opportunity_score(data: OpportunityScoreIn) -> OpportunityScoreOut:
    weights = {
        "confirmed_unmet_volume": 0.25,
        "share_without_feasible_offer": 0.20,
        "passport_match": 0.20,
        "moq_and_capacity": 0.15,
        "logistics": 0.10,
        "competition_and_saturation": 0.05,
        "data_quality": 0.05,
    }
    factors = data.model_dump()
    score = round(100 * sum(factors[key] * weight for key, weight in weights.items()))
    return OpportunityScoreOut(score=score, factors=factors)


def _partial_replacement(
    demand_units: int, reserves: list[ReserveOptionIn]
) -> tuple[list[ReplacementAllocation], int, Decimal, int]:
    eligible = sorted(
        (
            item
            for item in reserves
            if item.country == "RU" and item.serves_region
        ),
        key=lambda item: str(item.company_id),
    )
    if demand_units <= 0 or not eligible:
        return [], 0, 0, 0

    _validate_integer_budget(eligible,demand_units)
    model = cp_model.CpModel()
    total_units_terms = []
    total_cost_terms = []
    producer_data = []
    for index, producer in enumerate(eligible):
        tier_prices = {producer.moq_units: producer.unit_price_rub}
        for tier in producer.price_tiers:
            if tier.min_units <= producer.capacity_units:
                tier_prices[max(producer.moq_units, tier.min_units)] = tier.unit_price_rub
        tiers = sorted(tier_prices.items())
        tier_variables = []
        tier_selected = []
        for tier_index, (minimum, price) in enumerate(tiers):
            upper = min(producer.capacity_units, demand_units)
            if tier_index + 1 < len(tiers):
                upper = min(upper, tiers[tier_index + 1][0] - 1)
            if upper < minimum:
                continue
            units = model.new_int_var(0, upper, f"reserve_units_{index}_{tier_index}")
            selected = model.new_bool_var(f"reserve_selected_{index}_{tier_index}")
            model.add(units >= minimum * selected)
            model.add(units <= upper * selected)
            tier_variables.append((units, price))
            tier_selected.append(selected)
            total_cost_terms.append(_line_kopecks(model, price, units, upper, f"reserve_cost_{index}_{tier_index}"))
        if not tier_variables:
            continue
        model.add(sum(tier_selected) <= 1)
        producer_units = model.new_int_var(
            0, min(producer.capacity_units, demand_units), f"reserve_total_{index}"
        )
        model.add(producer_units == sum(item[0] for item in tier_variables))
        total_units_terms.append(producer_units)
        delivery_kopecks = int(amount(producer.delivery_cost_rub + producer.additional_cost_rub) * 100)
        total_cost_terms.append(delivery_kopecks * sum(tier_selected))
        producer_data.append(
            (producer, producer_units, tier_variables, tier_selected)
        )

    if not total_units_terms:
        return [], 0, 0, 0
    covered = sum(total_units_terms)
    cost = sum(total_cost_terms)
    model.add(covered <= demand_units)
    model.add(cost <= int(MAX_AMOUNT*100))
    model.maximize(covered)

    solver = cp_model.CpSolver()
    solver.parameters.num_search_workers = 1
    solver.parameters.random_seed = 0
    solver.parameters.max_time_in_seconds = 10
    status = solver.solve(model)
    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        return [], 0, 0, 0
    max_covered = solver.value(covered)
    if max_covered <= 0:
        return [], 0, 0, 0

    model.add(covered == max_covered)
    model.minimize(cost)
    status = solver.solve(model)
    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        return [], 0, 0, 0

    allocations = []
    today = date.today()
    for producer, units_variable, tiers, selected_variables in producer_data:
        units = solver.value(units_variable)
        if units <= 0:
            continue
        unit_price = next(
            price
            for (_, price), selected in zip(
                tiers, selected_variables, strict=True
            )
            if solver.value(selected)
        )
        confirmed = (
            producer.reserve_tier == "hot"
            and producer.confirmation_status == "approved"
            and producer.held_until is not None
            and producer.held_until >= today
        )
        allocations.append(
            ReplacementAllocation(
                company_id=producer.company_id,
                units=units,
                unit_price_rub=unit_price,
                delivery_cost_rub=producer.delivery_cost_rub,
                additional_cost_rub=producer.additional_cost_rub,
                total_cost_rub=amount(units * unit_price + producer.delivery_cost_rub + producer.additional_cost_rub),
                lead_time_days=producer.lead_time_days,
                reserve_tier=producer.reserve_tier,
                confirmed=confirmed,
            )
        )
    return (
        allocations,
        sum(item.units for item in allocations),
        amount(sum(item.total_cost_rub for item in allocations)),
        max((item.lead_time_days for item in allocations), default=0),
    )


def calculate_resilience(request: ResilienceRequest) -> ResilienceResponse:
    baseline_cost = amount(sum(item.total_cost_rub for item in request.primary_allocations) + request.reserve_holding_total_rub)
    if baseline_cost>MAX_AMOUNT:raise HTTPException(422,'Смета основного распределения выходит за денежный диапазон платформы')
    baseline_lead = max(
        item.lead_time_days for item in request.primary_allocations
    )
    today = date.today()
    confirmed_reserves = [
        item
        for item in request.reserve_options
        if item.reserve_tier == "hot"
        and item.confirmation_status == "approved"
        and item.held_until is not None
        and item.held_until >= today
    ]
    failure_sets = [
        ("n1", group)
        for group in combinations(request.primary_allocations, 1)
    ]
    failure_sets.extend(
        ("n2", group)
        for group in combinations(request.primary_allocations, 2)
    )

    scenarios = []
    coverage_ratios = []
    for scenario_type, failed in failure_sets:
        failed_ids = [item.company_id for item in failed]
        failed_units = sum(item.units for item in failed)
        failed_cost = sum(item.total_cost_rub for item in failed)
        confirmed_replacements, confirmed_covered, confirmed_cost, confirmed_lead = _partial_replacement(
            failed_units, confirmed_reserves
        )
        unconfirmed_reserves = [
            item for item in request.reserve_options if item not in confirmed_reserves
        ]
        probable_replacements, probable_covered, probable_cost, probable_lead = _partial_replacement(
            failed_units - confirmed_covered, unconfirmed_reserves
        )
        replacements = [*confirmed_replacements, *probable_replacements]
        covered = confirmed_covered + probable_covered
        replacement_cost = confirmed_cost + probable_cost
        replacement_lead = max(confirmed_lead, probable_lead)
        uncovered = max(0, failed_units - covered)
        unconfirmed = probable_covered
        candidate_cost = amount(baseline_cost - failed_cost + replacement_cost)
        if candidate_cost>MAX_AMOUNT:raise HTTPException(422,'Смета замены выходит за денежный диапазон платформы')
        candidate_price_delta = amount(candidate_cost - baseline_cost)
        candidate_price_delta_pct = (
            amount(candidate_price_delta / baseline_cost * 100)
            if baseline_cost
            else 0
        )
        cost_comparison_applicable = uncovered == 0
        new_cost = candidate_cost if cost_comparison_applicable else None
        price_delta = candidate_price_delta if cost_comparison_applicable else None
        price_delta_pct = (
            candidate_price_delta_pct if cost_comparison_applicable else None
        )
        surviving_leads = [
            item.lead_time_days
            for item in request.primary_allocations
            if item.company_id not in failed_ids
        ]
        new_lead = max([*surviving_leads, replacement_lead], default=0)
        delay = max(0, new_lead - baseline_lead)
        auto_eligible = (
            uncovered == 0
            and unconfirmed == 0
            and candidate_price_delta_pct <= decimal(request.max_price_increase_pct)
            and delay <= request.max_delay_days
        )
        explanations = [
            f"Заблокирован только объём выпавших производителей: {failed_units} шт.",
            f"Подтверждённым горячим резервом покрывается {confirmed_covered} шт.",
        ]
        if uncovered:
            explanations.append(
                f"Для {uncovered} шт. не найдено даже вероятной альтернативы"
            )
            explanations.append(
                "Изменение полной стоимости неприменимо, пока часть объёма не покрыта"
            )
        elif unconfirmed:
            explanations.append(
                f"Для {unconfirmed} шт. требуется подтверждение резервного производителя"
            )
        elif auto_eligible:
            explanations.append(
                "Замена укладывается в заранее заданные пороги цены и срока"
            )
        else:
            explanations.append(
                "Замена превышает порог цены или срока и требует решения покупателя"
            )
        coverage_ratios.append(
            confirmed_covered / failed_units if failed_units else 1
        )
        scenarios.append(
            FailureScenarioOut(
                scenario_type=scenario_type,
                failed_company_ids=failed_ids,
                failed_units=failed_units,
                replacement_allocations=replacements,
                baseline_total_cost_rub=baseline_cost,
                new_total_cost_rub=new_cost,
                price_delta_rub=price_delta,
                price_delta_pct=price_delta_pct,
                cost_comparison_applicable=cost_comparison_applicable,
                baseline_lead_time_days=baseline_lead,
                new_lead_time_days=new_lead,
                delay_days=delay,
                uncovered_units=uncovered,
                confirmed_covered_units=confirmed_covered,
                unconfirmed_units=unconfirmed,
                auto_eligible=auto_eligible,
                requires_human_approval=not auto_eligible,
                explanations=explanations,
            )
        )

    n1 = [item for item in scenarios if item.scenario_type == "n1"]
    n2 = [item for item in scenarios if item.scenario_type == "n2"]
    return ResilienceResponse(
        scenarios=scenarios,
        n1_fully_covered=bool(n1) and all(
            item.unconfirmed_units == 0 and item.uncovered_units == 0
            for item in n1
        ),
        n2_fully_covered=bool(n2) and all(
            item.unconfirmed_units == 0 and item.uncovered_units == 0
            for item in n2
        ),
        confirmed_coverage_pct=amount(100 * min(coverage_ratios)) if coverage_ratios else 0,
        input_hash=_input_hash(request),
    )
