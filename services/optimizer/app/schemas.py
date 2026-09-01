import uuid
from datetime import date
from typing import Literal

from pydantic import BaseModel, Field, model_validator


class VolumePriceTier(BaseModel):
    min_units: int = Field(gt=0)
    unit_price_rub: float = Field(gt=0)


class ProducerOption(BaseModel):
    company_id: uuid.UUID
    unit_price_rub: float = Field(gt=0)
    moq_units: int = Field(gt=0)
    capacity_units: int = Field(gt=0)
    lead_time_days: int = Field(gt=0)
    delivery_cost_rub: float = Field(default=0, ge=0)
    reliability: float = Field(default=0.8, ge=0, le=1)
    price_tiers: list[VolumePriceTier] = Field(default_factory=list)
    serves_region: bool = True
    country: str = "RU"

    @model_validator(mode="after")
    def validate_capacity(self):
        if self.moq_units > self.capacity_units:
            raise ValueError("MOQ не может превышать доступную мощность")
        return self


class AllocationRequest(BaseModel):
    demand_units: int = Field(gt=0)
    budget_rub: float | None = Field(default=None, gt=0)
    deadline_days: int = Field(gt=0)
    producers: list[ProducerOption] = Field(min_length=1)


class Allocation(BaseModel):
    company_id: uuid.UUID
    units: int
    unit_price_rub: float
    production_cost_rub: float
    delivery_cost_rub: float
    total_cost_rub: float
    lead_time_days: int
    reliability: float


class OptimizationVariant(BaseModel):
    kind: Literal["cheapest", "balanced", "reliable"]
    title: str
    feasible: bool
    allocations: list[Allocation] = Field(default_factory=list)
    total_units: int = 0
    total_cost_rub: float = 0
    max_lead_time_days: int = 0
    reliability_score: float = 0
    reasons: list[str] = Field(default_factory=list)


class OptimizationResponse(BaseModel):
    variants: list[OptimizationVariant]
    input_hash: str


class CoalitionMemberIn(BaseModel):
    need_id: uuid.UUID
    buyer_company_id: uuid.UUID
    volume_units: int = Field(gt=0)
    common_base: dict[str, str | int | float | bool]
    individual_operations: dict[str, str | int | float | bool] = Field(default_factory=dict)
    hard_constraints: dict[str, str | int | float | bool] = Field(default_factory=dict)
    flexible_parameters: dict[str, str | int | float | bool] = Field(default_factory=dict)
    individual_operations_cost_rub: float = Field(default=0, ge=0)
    delivery_cost_rub: float = Field(default=0, ge=0)
    budget_rub: float | None = Field(default=None, gt=0)
    individual_baseline_cost_rub: float | None = Field(default=None, gt=0)
    deadline_days: int = Field(gt=0)
    delivery_days: int = Field(default=1, ge=0)


class PriceTier(BaseModel):
    min_units: int = Field(gt=0)
    unit_price_rub: float = Field(gt=0)


class CoalitionRequest(BaseModel):
    producer_company_id: uuid.UUID
    producer_country: str = "RU"
    min_total_units: int = Field(gt=0)
    max_total_units: int = Field(gt=0)
    available_capacity_units: int = Field(gt=0)
    production_days: int = Field(gt=0)
    price_tiers: list[PriceTier] = Field(min_length=1)
    members: list[CoalitionMemberIn] = Field(min_length=2)

    @model_validator(mode="after")
    def validate_bounds(self):
        if self.min_total_units > self.max_total_units:
            raise ValueError("Минимальный объём больше максимального")
        return self


class CoalitionMemberResult(BaseModel):
    need_id: uuid.UUID
    buyer_company_id: uuid.UUID
    units: int
    common_production_cost_rub: float
    individual_operations_cost_rub: float
    delivery_cost_rub: float
    total_cost_rub: float
    baseline_cost_rub: float | None
    benefit_rub: float | None
    within_budget: bool
    deadline_met: bool


class CoalitionResponse(BaseModel):
    compatible: bool
    feasible: bool
    combined_volume_units: int
    unit_price_rub: float | None = None
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
    company_id: uuid.UUID
    units: int = Field(gt=0)
    unit_price_rub: float = Field(gt=0)
    delivery_cost_rub: float = Field(default=0, ge=0)
    lead_time_days: int = Field(gt=0)

    @property
    def total_cost_rub(self) -> float:
        return round(self.units * self.unit_price_rub + self.delivery_cost_rub, 2)


class ReserveOptionIn(ProducerOption):
    reserve_tier: Literal["hot", "warm"]
    confirmation_status: Literal[
        "approved", "pending", "reconfirmation_requested"
    ] = "pending"
    held_until: date | None = None


class ResilienceRequest(BaseModel):
    primary_allocations: list[PrimaryAllocationIn] = Field(min_length=1, max_length=6)
    reserve_options: list[ReserveOptionIn] = Field(default_factory=list, max_length=20)
    max_price_increase_pct: float = Field(default=5, ge=0, le=100)
    max_delay_days: int = Field(default=0, ge=0, le=365)

    @model_validator(mode="after")
    def validate_companies(self):
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
    company_id: uuid.UUID
    units: int
    unit_price_rub: float
    delivery_cost_rub: float
    total_cost_rub: float
    lead_time_days: int
    reserve_tier: Literal["hot", "warm"]
    confirmed: bool


class FailureScenarioOut(BaseModel):
    scenario_type: Literal["n1", "n2"]
    failed_company_ids: list[uuid.UUID]
    failed_units: int
    replacement_allocations: list[ReplacementAllocation]
    baseline_total_cost_rub: float
    new_total_cost_rub: float | None
    price_delta_rub: float | None
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


class ResilienceResponse(BaseModel):
    scenarios: list[FailureScenarioOut]
    n1_fully_covered: bool
    n2_fully_covered: bool
    confirmed_coverage_pct: float
    input_hash: str
