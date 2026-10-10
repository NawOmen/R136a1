import uuid
from decimal import Decimal
from .money import Amount, Money, amount
from datetime import date
from typing import Literal

from pydantic import BaseModel, Field, model_validator


class VolumePriceTier(BaseModel):
    min_units: int = Field(gt=0, le=2147483647)
    unit_price_rub: Money = Field(gt=0)


class ProducerOption(BaseModel):
    additional_cost_rub: Amount = Field(default=0,ge=0)

    company_id: uuid.UUID
    unit_price_rub: Money = Field(gt=0)
    moq_units: int = Field(gt=0, le=2147483647)
    capacity_units: int = Field(gt=0, le=2147483647)
    lead_time_days: int = Field(gt=0)
    delivery_cost_rub: Amount = Field(default=0, ge=0)
    reliability: float | None = Field(default=None, ge=0, le=1)
    price_tiers: list[VolumePriceTier] = Field(default_factory=list, max_length=25)
    serves_region: bool = True
    country: str = "RU"

    @model_validator(mode="after")
    def validate_capacity(self):
        if self.moq_units > self.capacity_units:
            raise ValueError("MOQ не может превышать доступную мощность")
        return self


class AllocationRequest(BaseModel):
    comparison_context: dict = Field(default_factory=dict)
    demand_units: int = Field(gt=0, le=2147483647)
    budget_rub: Amount | None = Field(default=None, gt=0)
    deadline_days: int = Field(gt=0)
    producers: list[ProducerOption] = Field(min_length=1, max_length=25)


class Allocation(BaseModel):
    additional_cost_rub: Amount = 0

    company_id: uuid.UUID
    units: int
    unit_price_rub: Money
    production_cost_rub: Amount
    delivery_cost_rub: Amount
    total_cost_rub: Amount
    lead_time_days: int
    reliability: float | None


class OptimizationVariant(BaseModel):
    kind: Literal["cheapest", "balanced", "reliable"]
    title: str
    feasible: bool
    allocations: list[Allocation] = Field(default_factory=list)
    total_units: int = 0
    total_cost_rub: Amount = 0
    max_lead_time_days: int = 0
    reliability_score: float | None = None
    reasons: list[str] = Field(default_factory=list)


class OptimizationResponse(BaseModel):
    variants: list[OptimizationVariant]
    input_hash: str


class CoalitionMemberIn(BaseModel):
    need_id: uuid.UUID
    buyer_company_id: uuid.UUID
    volume_units: int = Field(gt=0, le=2147483647)
    common_base: dict[str, str | int | float | bool]
    individual_operations: dict[str, str | int | float | bool] = Field(default_factory=dict)
    hard_constraints: dict[str, str | int | float | bool] = Field(default_factory=dict)
    flexible_parameters: dict[str, str | int | float | bool] = Field(default_factory=dict)
    individual_operations_cost_rub: Amount = Field(default=0, ge=0)
    delivery_cost_rub: Amount = Field(default=0, ge=0)
    budget_rub: Amount | None = Field(default=None, gt=0)
    individual_baseline_cost_rub: Amount | None = Field(default=None, gt=0)
    deadline_days: int = Field(gt=0)
    delivery_days: int = Field(default=1, ge=0)


class PriceTier(BaseModel):
    min_units: int = Field(gt=0, le=2147483647)
    unit_price_rub: Money = Field(gt=0)


class CoalitionRequest(BaseModel):
    producer_company_id: uuid.UUID
    producer_country: str = "RU"
    min_total_units: int = Field(gt=0, le=2147483647)
    max_total_units: int = Field(gt=0, le=2147483647)
    available_capacity_units: int = Field(gt=0, le=2147483647)
    production_days: int = Field(gt=0)
    price_tiers: list[PriceTier] = Field(min_length=1, max_length=25)
    members: list[CoalitionMemberIn] = Field(min_length=2, max_length=100)

    @model_validator(mode="after")
    def validate_bounds(self):
        if self.min_total_units > self.max_total_units:
            raise ValueError("Минимальный объём больше максимального")
        return self


class CoalitionMemberResult(BaseModel):
    need_id: uuid.UUID
    buyer_company_id: uuid.UUID
    units: int
    common_production_cost_rub: Amount
    individual_operations_cost_rub: Amount
    delivery_cost_rub: Amount
    total_cost_rub: Amount
    baseline_cost_rub: Amount | None
    benefit_rub: Amount | None
    within_budget: bool
    deadline_met: bool


class CoalitionResponse(BaseModel):
    compatible: bool
    feasible: bool
    combined_volume_units: int
    unit_price_rub: Money | None = None
    members: list[CoalitionMemberResult] = Field(default_factory=list)
    reasons: list[str] = Field(default_factory=list)
    input_hash: str


class OpportunityScoreIn(BaseModel):
    confirmed_unmet_volume: float = Field(ge=0, le=1)
    share_without_feasible_offer: float = Field(ge=0, le=1)
    passport_match: float = Field(ge=0, le=1)
    moq_and_capacity: float = Field(ge=0, le=1)
    logistics: float = Field(ge=0, le=1)
    competition_and_saturation: float = Field(ge=0, le=1)
    data_quality: float = Field(ge=0, le=1)


class OpportunityScoreOut(BaseModel):
    score: int = Field(ge=0, le=100)
    factors: dict[str, float]


class PrimaryAllocationIn(BaseModel):
    protected_units: int = Field(default=0, ge=0)
    additional_cost_rub: Amount = Field(default=0,ge=0)

    company_id: uuid.UUID
    units: int = Field(gt=0, le=2147483647)
    unit_price_rub: Money = Field(gt=0)
    delivery_cost_rub: Amount = Field(default=0, ge=0)
    lead_time_days: int = Field(gt=0)

    @property
    def total_cost_rub(self) -> Decimal:
        return amount(self.units * self.unit_price_rub + self.delivery_cost_rub + self.additional_cost_rub)


class ReserveOptionIn(ProducerOption):
    reserve_tier: Literal["hot", "warm"]
    confirmation_status: Literal[
        "approved", "pending", "reconfirmation_requested"
    ] = "pending"
    held_until: date | None = None
    switchover_days: int | None = Field(default=None, ge=0, le=365)


class ResilienceRequest(BaseModel):
    reserve_holding_total_rub: Amount = Field(default=0,ge=0)

    primary_allocations: list[PrimaryAllocationIn] = Field(min_length=1, max_length=6)
    reserve_options: list[ReserveOptionIn] = Field(default_factory=list, max_length=20)
    max_price_increase_pct: float = Field(default=5, ge=0, le=100)
    max_delay_days: int = Field(default=0, ge=0, le=365)
    time_limit_seconds: float = Field(default=10, gt=0, le=60)

    @model_validator(mode="after")
    def validate_companies(self):
        if any(item.protected_units > item.units for item in self.primary_allocations):
            raise ValueError("Исполненный объём превышает назначение")
        primary_ids = [item.company_id for item in self.primary_allocations]
        reserve_ids = [item.company_id for item in self.reserve_options]
        if len(set(primary_ids)) != len(primary_ids):
            raise ValueError("Основной производитель не может повторяться")
        if len(set(reserve_ids)) != len(reserve_ids):
            raise ValueError("Резервный производитель не может повторяться")
        if set(primary_ids) & set(reserve_ids):
            raise ValueError("Основной производитель не может одновременно быть резервом")
        return self


class ReplacementAllocation(BaseModel):
    additional_cost_rub: Amount = 0

    company_id: uuid.UUID
    units: int
    unit_price_rub: Money
    delivery_cost_rub: Amount
    total_cost_rub: Amount
    lead_time_days: int
    reserve_tier: Literal["hot", "warm"]
    confirmed: bool
    lead_time_known: bool = True


class FailureScenarioOut(BaseModel):
    scenario_type: Literal["n1", "n2"]
    failed_company_ids: list[uuid.UUID]
    failed_units: int
    replacement_allocations: list[ReplacementAllocation]
    baseline_total_cost_rub: Amount
    new_total_cost_rub: Amount | None
    price_delta_rub: Amount | None
    price_delta_pct: float | None
    cost_comparison_applicable: bool
    baseline_lead_time_days: int
    new_lead_time_days: int
    delay_days: int
    uncovered_units: int
    confirmed_covered_units: int
    unconfirmed_units: int
    auto_eligible: bool
    requires_human_approval: bool
    explanations: list[str]
    solver_status: str = "optimal"


class ResilienceResponse(BaseModel):
    scenarios: list[FailureScenarioOut]
    n1_fully_covered: bool
    n2_fully_covered: bool
    confirmed_coverage_pct: float
    input_hash: str
