import uuid
from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


# ---------- Адреса доставки ----------

class DeliveryAddressOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    company_id: uuid.UUID
    address: str
    city: str
    region: str
    is_default: bool


class DeliveryAddressIn(BaseModel):
    address: str = Field(min_length=5, max_length=500)
    city: str = Field(min_length=2, max_length=120)
    region: str = Field(min_length=2, max_length=120)
    is_default: bool = False


class DeliveryAddressPatch(BaseModel):
    address: str | None = Field(default=None, min_length=5, max_length=500)
    city: str | None = Field(default=None, min_length=2, max_length=120)
    region: str | None = Field(default=None, min_length=2, max_length=120)
    is_default: bool | None = None


# ---------- Производственный профиль ----------

class ProductionProfileOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    company_id: uuid.UUID
    production_site_address: str | None
    region: str | None
    about: str | None


class ProductionProfileIn(BaseModel):
    production_site_address: str | None = Field(default=None, max_length=500)
    region: str | None = Field(default=None, max_length=120)
    about: str | None = Field(default=None, max_length=2000)


# ---------- Товары ----------

class ProductImageOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    file_name: str
    content_type: str
    position: int


class ProductPriceTier(BaseModel):
    min_units: int = Field(gt=0)
    unit_price_rub: float = Field(gt=0)


class ProductRules(BaseModel):
    @field_validator("characteristics", check_fields=False)
    @classmethod
    def validate_characteristics(cls, value: dict[str, Any] | None):
        if value is not None and len(value) > 25:
            raise ValueError("Можно добавить не более 25 характеристик")
        return value

    @field_validator("price_tiers", check_fields=False)
    @classmethod
    def validate_price_tiers(cls, value: list[ProductPriceTier] | None):
        if value is None:
            return value
        if len(value) > 10:
            raise ValueError("Можно добавить не более 10 ценовых ступеней")
        units = [tier.min_units for tier in value]
        if units != sorted(set(units)):
            raise ValueError("Объёмы ценовых ступеней должны возрастать и не повторяться")
        prices = [tier.unit_price_rub for tier in value]
        if any(current > previous for previous, current in zip(prices, prices[1:])):
            raise ValueError("Цена за единицу не должна расти при увеличении объёма")
        return value


class ProductOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    company_id: uuid.UUID
    name: str
    category: str
    subcategory: str | None
    characteristics: dict[str, Any]
    price_rub: float
    price_tiers: list[ProductPriceTier]
    moq_units: int
    lead_time_days: int
    is_published: bool
    images: list[ProductImageOut] = Field(default_factory=list)


class ProductIn(ProductRules):
    name: str = Field(min_length=2, max_length=255)
    category: str = Field(min_length=2, max_length=120)
    subcategory: str | None = Field(default=None, max_length=120)
    characteristics: dict[str, Any] = Field(default_factory=dict)
    price_rub: float = Field(gt=0)
    price_tiers: list[ProductPriceTier] = Field(default_factory=list)
    moq_units: int = Field(gt=0)
    lead_time_days: int = Field(gt=0)

    @model_validator(mode="after")
    def validate_tiers_against_moq(self):
        if self.price_tiers and self.price_tiers[0].min_units < self.moq_units:
            raise ValueError("Первая ценовая ступень не может быть меньше минимального заказа")
        if any(tier.unit_price_rub > self.price_rub for tier in self.price_tiers):
            raise ValueError("Цена в ступени не может быть выше базовой цены")
        return self


class ProductPatch(ProductRules):
    name: str | None = Field(default=None, min_length=2, max_length=255)
    category: str | None = Field(default=None, min_length=2, max_length=120)
    subcategory: str | None = Field(default=None, max_length=120)
    characteristics: dict[str, Any] | None = None
    price_rub: float | None = Field(default=None, gt=0)
    price_tiers: list[ProductPriceTier] | None = None
    moq_units: int | None = Field(default=None, gt=0)
    lead_time_days: int | None = Field(default=None, gt=0)


class PublishIn(BaseModel):
    published: bool


class DealMessageIn(BaseModel):
    company_id: uuid.UUID
    message: str = Field(min_length=1, max_length=2000)

    @field_validator("message")
    @classmethod
    def message_not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Сообщение не может быть пустым")
        return value.strip()


class DealMessageOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    deal_id: uuid.UUID
    author_user_id: uuid.UUID
    author_company_id: uuid.UUID
    message: str
    created_at: datetime


class SellerAnalyticsOut(BaseModel):
    company_id: uuid.UUID
    products_total: int
    products_published: int
    deals_total: int
    sold_units: int
    revenue_rub: float
    available_capacity_units: int
    capacity_utilization_pct: float


# ---------- Мощности ----------

class CapacityEntryIn(BaseModel):
    date: date
    available_units: int = Field(ge=0)


class CapacityPutIn(BaseModel):
    entries: list[CapacityEntryIn]


# ---------- Документы ----------

class DocumentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    company_id: uuid.UUID
    name: str
    document_type: str
    file_key: str
    content_type: str
    verification_status: str
    scope_category: str | None = None
    scope_subcategory: str | None = None
    valid_until: date | None = None
    confirms: dict[str, list[str]] = Field(default_factory=dict)
    verified_by_user_id: uuid.UUID | None = None
    verified_at: datetime | None = None
    verification_note: str | None = None
    created_at: datetime | None = None


class PendingDocumentOut(DocumentOut):
    """Документ в очереди проверки площадки: имя компании нужно проверяющему."""

    company_display_name: str | None = None


class DocumentVerificationIn(BaseModel):
    """Решение проверяющего. Допуск выдаёт человек, а не загрузка файла."""

    decision: Literal["verified", "rejected", "unverified"]
    scope_category: str | None = Field(default=None, max_length=120)
    scope_subcategory: str | None = Field(default=None, max_length=120)
    valid_until: date | None = None
    # Значения характеристик, которые проверяющий подтвердил именно этим документом.
    confirms: dict[str, list[str]] | None = None
    note: str | None = Field(default=None, max_length=500)

    @model_validator(mode="after")
    def validate_decision(self):
        if self.decision == "verified" and not self.scope_category:
            raise ValueError("Для подтверждения укажите область действия документа")
        if self.decision == "rejected" and not (self.note or "").strip():
            raise ValueError("Для отклонения укажите причину")
        if self.confirms:
            cleaned: dict[str, list[str]] = {}
            for key, values in self.confirms.items():
                if not key.strip():
                    raise ValueError("Название подтверждаемой характеристики не может быть пустым")
                items = [str(value).strip() for value in values if str(value).strip()]
                if not items:
                    raise ValueError("Для подтверждаемой характеристики укажите хотя бы одно значение")
                cleaned[key.strip().lower()] = items
            self.confirms = cleaned
        return self


# ---------- Категорийный допуск ----------

class RequirementStatusOut(BaseModel):
    """Состояние одного обязательного доказательства."""

    code: str
    title: str
    legal_reference: str
    blocking: bool
    state: str
    state_label: str
    seller_hint: str
    buyer_note: str
    document_ids: list[uuid.UUID] = Field(default_factory=list)
    # Пояснение по применимости: например, документ подтверждён для другой подкатегории.
    scope_note: str | None = None


class CategoryAdmissionOut(BaseModel):
    category: str
    subcategory: str | None
    state: str
    state_label: str
    supported: bool
    profile_title: str | None
    summary: str
    requirements: list[RequirementStatusOut]
    advisories: list[str]
    blocking_open: int
    blocking_message: str = ""
    # Перечень причин без контекста: публикация, сделка или резерв добавляют свой префикс.
    blocking_reasons: str = ""
    checked_at: datetime
    profile_key: str | None = None
    rules_version: str = ""


class CategoryRequirementsOut(BaseModel):
    """Публичный чек-лист покупателя: что проверить до сделки."""

    category: str
    subcategory: str | None
    profile_title: str | None
    supported: bool
    summary: str
    checklist: list[RequirementStatusOut]
    advisories: list[str]
    note: str


class AdmissionChecklistOut(BaseModel):
    """Состояние допуска опубликованного товара глазами покупателя."""

    product_id: uuid.UUID
    category: str
    subcategory: str | None
    state: str
    state_label: str
    supported: bool
    summary: str
    checklist: list[RequirementStatusOut]
    advisories: list[str]
    note: str
    checked_at: datetime


# ---------- Capability Passport ----------

class CapabilityDetails(BaseModel):
    """Ограниченный структурированный контекст производителя или поставщика."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    business_kind: Literal["manufacturer", "stock_supplier", "both"] = "manufacturer"
    product_types: str = Field(default="", max_length=1200)
    complexity: str = Field(default="", max_length=1200)
    material_grades: str = Field(default="", max_length=800)
    limitations: str = Field(default="", max_length=1200)
    packaging: str = Field(default="", max_length=800)
    delivery: str = Field(default="", max_length=800)
    quality_control: str = Field(default="", max_length=800)
    trial_batch: str = Field(default="", max_length=800)


class CapabilityPassportOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    company_id: uuid.UUID
    technologies: list[Any]
    equipment: list[Any]
    materials: list[Any]
    size_ranges: dict[str, Any]
    tolerances: str | None
    certifications: list[Any]
    min_order_units: int | None
    max_order_units: int | None
    delivery_regions: list[Any]
    completed_order_types: list[Any]
    details: CapabilityDetails = Field(default_factory=CapabilityDetails)


class CapabilityPassportIn(BaseModel):
    details: CapabilityDetails = Field(default_factory=CapabilityDetails)
    technologies: list[str] = Field(default_factory=list)
    equipment: list[str] = Field(default_factory=list)
    materials: list[str] = Field(default_factory=list)
    size_ranges: dict[str, Any] = Field(default_factory=dict)
    tolerances: str | None = Field(default=None, max_length=500)
    certifications: list[str] = Field(default_factory=list)
    min_order_units: int | None = Field(default=None, ge=0)
    max_order_units: int | None = Field(default=None, ge=0)
    delivery_regions: list[str] = Field(default_factory=list)
    completed_order_types: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_order_limits(self):
        if self.min_order_units and self.max_order_units and self.min_order_units > self.max_order_units:
            raise ValueError("Минимальный заказ не может быть больше максимального")
        return self


# ---------- Потребности ----------

class NeedFileOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    file_name: str
    content_type: str


class NeedOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    company_id: uuid.UUID
    created_by_user_id: uuid.UUID | None
    category: str
    characteristics: dict[str, Any]
    volume_units: int
    budget_rub: float | None
    deadline_date: date
    delivery_address_id: uuid.UUID | None
    visibility: str
    status: str
    valid_until: date | None
    no_match_reason: str | None
    confirmed_at: datetime | None
    files: list[NeedFileOut] = Field(default_factory=list)


class NeedFeedOut(BaseModel):
    """Обезличенная карточка для открытой ленты производителей."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    category: str
    characteristics: dict[str, Any]
    volume_units: int
    deadline_date: date
    visibility: str
    status: str
    valid_until: date | None


class NeedIn(BaseModel):
    company_id: uuid.UUID
    category: str = Field(min_length=2, max_length=120)
    characteristics: dict[str, Any] = Field(default_factory=dict)
    volume_units: int = Field(gt=0)
    budget_rub: float | None = Field(default=None, gt=0)
    deadline_date: date
    delivery_address_id: uuid.UUID | None = None
    visibility: str = Field(default="open_anonymized", pattern="^(open_anonymized|selected_producers|closed)$")
    valid_until: date | None = None


# ---------- Предложения ----------

class OfferOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    need_id: uuid.UUID
    company_id: uuid.UUID
    created_by_user_id: uuid.UUID | None
    price_rub: float
    available_units: int
    lead_time_days: int
    delivery_cost_rub: float
    moq_units: int
    price_tiers: list[dict[str, Any]]
    valid_until: date | None
    status: str


class OfferPriceTierIn(BaseModel):
    min_units: int = Field(gt=0)
    unit_price_rub: float = Field(gt=0)


class OfferIn(BaseModel):
    company_id: uuid.UUID
    price_rub: float = Field(gt=0)
    available_units: int = Field(gt=0)
    lead_time_days: int = Field(gt=0)
    delivery_cost_rub: float = Field(default=0, ge=0)
    moq_units: int = Field(default=1, gt=0)
    price_tiers: list[OfferPriceTierIn] = Field(default_factory=list)
    valid_until: date | None = None


class OfferPatch(BaseModel):
    price_rub: float | None = Field(default=None, gt=0)
    available_units: int | None = Field(default=None, gt=0)
    lead_time_days: int | None = Field(default=None, gt=0)
    delivery_cost_rub: float | None = Field(default=None, ge=0)
    moq_units: int | None = Field(default=None, gt=0)
    price_tiers: list[OfferPriceTierIn] | None = None
    valid_until: date | None = None


# ---------- Оптимизатор и рыночные возможности ----------

class OptimizationVariantOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    need_id: uuid.UUID
    kind: str
    result: dict[str, Any]
    input_hash: str


class MarketOpportunityOut(BaseModel):
    id: uuid.UUID
    company_id: uuid.UUID
    category: str
    score: int
    competition_level: str
    saturation_risk: str
    unmet_volume_units: int | None
    buyers_count: int
    reasons: list[str]
    missing_data: list[str]
    status: str


class PriceTierIn(BaseModel):
    min_units: int = Field(gt=0)
    unit_price_rub: float = Field(gt=0)


class ParticipantTermsIn(BaseModel):
    need_id: uuid.UUID
    individual_operations_cost_rub: float = Field(default=0, ge=0)
    delivery_cost_rub: float = Field(default=0, ge=0)
    individual_baseline_cost_rub: float | None = Field(default=None, gt=0)
    delivery_days: int = Field(default=1, ge=0)


class GroupOfferPublishIn(BaseModel):
    min_total_units: int = Field(gt=0)
    max_total_units: int = Field(gt=0)
    available_capacity_units: int = Field(gt=0)
    price_tiers: list[PriceTierIn] = Field(min_length=1)
    production_start: date
    production_end: date
    fill_deadline: date
    non_fill_rule: Literal["extend_with_approval", "recalculate", "close_without_obligations"]
    participant_terms: list[ParticipantTermsIn] = Field(min_length=2)


class GroupOfferOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    coalition_id: uuid.UUID
    company_id: uuid.UUID
    opportunity_id: uuid.UUID | None
    min_total_units: int | None
    max_total_units: int | None
    price_tiers: list[dict[str, Any]]
    production_start: date | None
    production_end: date | None
    fill_deadline: date | None
    non_fill_rule: str | None
    status: str
    seller_approval_status: str


class CoalitionMemberOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    need_id: uuid.UUID
    buyer_company_id: uuid.UUID | None
    units: int
    individual_operations: dict[str, Any]
    common_cost_rub: float | None
    individual_cost_rub: float | None
    delivery_cost_rub: float | None
    total_cost_rub: float | None
    baseline_cost_rub: float | None
    benefit_rub: float | None
    approval_status: str


class CoalitionOut(BaseModel):
    id: uuid.UUID
    producer_company_id: uuid.UUID | None
    category: str
    combined_volume_units: int
    target_moq_units: int | None
    status: str
    version: int
    explanation: list[str]
    members: list[CoalitionMemberOut]
    group_offer: GroupOfferOut | None = None


class CoalitionDecisionIn(BaseModel):
    company_id: uuid.UUID
    decision: Literal["approved", "rejected"]


# ---------- Устойчивость, N-1 / N-2 и резерв ----------

class ResiliencePlanCreateIn(BaseModel):
    variant_id: uuid.UUID
    max_price_increase_pct: float = Field(default=5, ge=0, le=100)
    max_delay_days: int = Field(default=0, ge=0, le=365)
    auto_replace_within_thresholds: bool = False


class ResiliencePlanConfirmIn(BaseModel):
    approved: Literal[True]


class ReserveDecisionIn(BaseModel):
    company_id: uuid.UUID
    decision: Literal["approved", "rejected"]
    capacity_units: int | None = Field(default=None, gt=0)
    moq_units: int | None = Field(default=None, gt=0)
    unit_price_rub: float | None = Field(default=None, gt=0)
    delivery_cost_rub: float | None = Field(default=None, ge=0)
    lead_time_days: int | None = Field(default=None, gt=0)
    price_tiers: list[PriceTierIn] = Field(default_factory=list)
    held_until: date | None = None


class FailureSimulationIn(BaseModel):
    failed_company_ids: list[uuid.UUID] = Field(min_length=1, max_length=2)


class ProducerFailureIn(BaseModel):
    company_id: uuid.UUID
    reason: str = Field(min_length=3, max_length=500)


class ReserveCommitmentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    plan_id: uuid.UUID
    company_id: uuid.UUID
    offer_id: uuid.UUID | None
    reserve_tier: str
    confirmation_status: str
    proposed_capacity_units: int | None
    proposed_moq_units: int | None
    proposed_unit_price_rub: float | None
    proposed_delivery_cost_rub: float | None
    proposed_lead_time_days: int | None
    price_tiers: list[dict[str, Any]]
    confirmed_capacity_units: int | None
    confirmed_moq_units: int | None
    confirmed_unit_price_rub: float | None
    confirmed_delivery_cost_rub: float | None
    confirmed_lead_time_days: int | None
    held_until: date | None


class PrimaryObligationOut(BaseModel):
    plan_id: uuid.UUID
    need_id: uuid.UUID
    company_id: uuid.UUID
    allocation: dict[str, Any]
    plan_status: str
    confirmed_at: datetime | None


class ResilienceScenarioOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    plan_id: uuid.UUID
    scenario_type: str
    failed_company_ids: list[str]
    result: dict[str, Any]
    input_hash: str
    status: str
    is_simulation: bool


class ResilienceEventOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    event_type: str
    actor_company_id: uuid.UUID | None
    payload: dict[str, Any]
    created_at: datetime


class ResiliencePlanOut(BaseModel):
    id: uuid.UUID
    need_id: uuid.UUID
    buyer_company_id: uuid.UUID
    baseline_variant_id: uuid.UUID
    baseline_allocations: list[dict[str, Any]]
    baseline_total_cost_rub: float
    baseline_lead_time_days: int
    current_allocations: list[dict[str, Any]]
    current_total_cost_rub: float
    current_lead_time_days: int
    max_price_increase_pct: float
    max_delay_days: int
    auto_replace_within_thresholds: bool
    failed_company_ids: list[str]
    status: str
    version: int
    confirmed_at: datetime | None
    reserves: list[ReserveCommitmentOut]
    scenarios: list[ResilienceScenarioOut]
    events: list[ResilienceEventOut]


# ---------- Сделки ----------

class DealOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    offer_id: uuid.UUID
    need_id: uuid.UUID
    buyer_company_id: uuid.UUID
    seller_company_id: uuid.UUID
    performed_by_user_id: uuid.UUID | None
    units: int
    total_price_rub: float
    status: str


# ---------- Уведомления ----------

class NotificationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    user_id: uuid.UUID
    message: str
    type: str
    is_read: bool


# ---------- Доверие, KPI и поддержка ----------

class SupportTicketIn(BaseModel):
    company_id: uuid.UUID | None = None
    subject: str = Field(min_length=3, max_length=200)
    message: str = Field(min_length=10, max_length=5000)


class SupportTicketUpdateIn(BaseModel):
    status: Literal["new", "in_progress", "resolved", "closed"]
    admin_response: str | None = Field(default=None, max_length=5000)


class SupportTicketOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    user_id: uuid.UUID
    company_id: uuid.UUID | None
    subject: str
    message: str
    status: str
    admin_response: str | None
    assigned_admin_user_id: uuid.UUID | None
    created_at: datetime
    updated_at: datetime


class TrustAuditEventOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    sequence: int
    event_hash: str
    event_type: str
    entity_type: str
    entity_id: uuid.UUID | None
    source_refs: list[dict[str, Any]]
    explanation: str
    payload: dict[str, Any]
    created_at: datetime


class AuditVerificationOut(BaseModel):
    valid: bool
    checked_events: int
    broken_sequence: int | None = None


class KpiOut(BaseModel):
    scope: Literal["company", "marketplace"]
    company_id: uuid.UUID | None = None
    generated_from_events: int
    buyer: dict[str, int | float]
    seller: dict[str, int | float]
    marketplace: dict[str, int | float]
    baseline_note: str


# ---------- Этап 9: пользовательский опыт и сопровождение сделки ----------

class PublicProducerOut(BaseModel):
    capability_details: CapabilityDetails | None = None
    company_id: uuid.UUID
    display_name: str
    legal_form: str
    region: str | None
    about: str | None
    production_site_address: str | None
    has_photo: bool
    rating: float | None
    reviews_count: int


class PublicProductDetailOut(ProductOut):
    producer: PublicProducerOut


class NeedRepeatIn(BaseModel):
    deadline_date: date
    valid_until: date | None = None


class CharacteristicValidationIn(BaseModel):
    category: str = Field(min_length=2, max_length=120)
    subcategory: str | None = Field(default=None, max_length=120)
    characteristics: dict[str, Any] = Field(default_factory=dict)
    moq_units: int = Field(ge=1)


class CharacteristicValidationOut(BaseModel):
    valid: bool
    errors: list[str]
    warnings: list[str]


class DealCheckpointOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    deal_id: uuid.UUID
    kind: str
    status: str
    note: str | None
    completed_at: datetime | None


class CheckpointUpdateIn(BaseModel):
    company_id: uuid.UUID
    completed: bool
    note: str | None = Field(default=None, max_length=500)
    human_approved: Literal[True]


class DeliveryArrangementIn(BaseModel):
    company_id: uuid.UUID
    weight_kg: float = Field(gt=0, le=100_000)
    volume_m3: float = Field(gt=0, le=10_000)
    method: Literal["buyer_carrier", "self_pickup", "seller_delivery"]
    carrier_name: str | None = Field(default=None, max_length=255)
    tracking_number: str | None = Field(default=None, max_length=255)
    human_approved: Literal[True]

    @model_validator(mode="after")
    def require_carrier_for_buyer_delivery(self) -> "DeliveryArrangementIn":
        if self.method == "buyer_carrier" and not (self.carrier_name or "").strip():
            raise ValueError("Укажите выбранного перевозчика")
        return self


class DeliveryArrangementOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    deal_id: uuid.UUID
    weight_kg: float
    volume_m3: float
    cargo_class: str
    classification_note: str
    method: str
    carrier_name: str | None
    tracking_number: str | None
    buyer_responsible: bool


class DealReviewIn(BaseModel):
    company_id: uuid.UUID
    rating: int = Field(ge=1, le=5)
    comment: str = Field(min_length=10, max_length=2000)


class DealReviewOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    deal_id: uuid.UUID
    reviewer_company_id: uuid.UUID
    reviewed_company_id: uuid.UUID
    rating: int
    comment: str
    created_at: datetime


class PriceIndexPoint(BaseModel):
    date: date
    average_unit_price_rub: float
    offers_count: int


class MarketWatchIn(BaseModel):
    category: str = Field(min_length=2, max_length=120)
    demand_changes: bool = True
    supply_changes: bool = True


class MarketWatchOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    category: str
    demand_changes: bool
    supply_changes: bool


class BuyerSavingsOut(BaseModel):
    company_id: uuid.UUID
    confirmed_savings_rub: float
    calculated_variants_rub: float
    coalitions_count: int
    explanation: str
