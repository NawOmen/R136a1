import uuid
from .money import Amount, Money
from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, PrivateAttr, JsonValue, field_validator, model_validator

from .commercial import CommercialTerms
from .category_characteristics import (
    count_user_characteristics,
    required_characteristic_keys,
    validate_profile_values,
)

def check_user_characteristics_limit(value: dict[str, Any] | None, category: str | None,
                                     subcategory: str | None) -> str | None:
    if value is not None and count_user_characteristics(value, category, subcategory) > 25:
        return "Можно добавить не более 25 пользовательских характеристик сверх системных и обязательных"
    return None


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
    model_config = ConfigDict(allow_inf_nan=False)
    min_units: int = Field(gt=0, le=2147483647)
    unit_price_rub: Money = Field(gt=0)


class ProductSource(BaseModel):
    label: str = Field(min_length=1, max_length=120)
    reference: str = Field(min_length=1, max_length=300)


def validate_order_unit(characteristics: dict[str, Any] | None) -> None:
    if not characteristics:
        return
    for key in ("unit", "единица измерения"):
        if key in characteristics:
            value = characteristics[key]
            if not isinstance(value, str) or not value.strip() or len(value.strip()) > 32:
                raise ValueError("Единица заказа должна быть строкой длиной от 1 до 32 символов")


class ProductRules(BaseModel):
    model_config = ConfigDict(allow_inf_nan=False)
    @field_validator("characteristics", check_fields=False)
    @classmethod
    def validate_characteristics(cls, value: dict[str, Any] | None):
        # Лимит 25 применяется в model-валидаторах с учётом категории:
        # системные и обязательные свойства не входят в счёт.
        validate_order_unit(value)
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
    quantity_conversion: dict | None = None
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    company_id: uuid.UUID
    revision: int = 1
    external_id: str | None = None
    sources: list[ProductSource] = Field(default_factory=list)
    name: str
    category: str
    subcategory: str | None
    category_profile: dict[str, Any] | None = None
    characteristics: dict[str, Any]
    price_rub: Money
    price_tiers: list[ProductPriceTier]
    moq_units: int
    lead_time_days: int
    stock_units: int | None = None
    stock_updated_at: datetime | None = None
    is_published: bool
    images: list[ProductImageOut] = Field(default_factory=list)


class ProductIn(ProductRules):
    name: str = Field(min_length=2, max_length=255)
    category: str = Field(min_length=2, max_length=120)
    subcategory: str | None = Field(default=None, max_length=120)
    characteristics: dict[str, Any] = Field(default_factory=dict)
    sources: list[ProductSource] = Field(default_factory=list, max_length=10)
    external_id: str | None = Field(default=None, min_length=1, max_length=64)
    price_rub: Money = Field(gt=0)
    price_tiers: list[ProductPriceTier] = Field(default_factory=list)
    moq_units: int = Field(gt=0, le=2147483647)
    lead_time_days: int = Field(gt=0)
    stock_units: int | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def validate_category_values(self):
        errors = validate_profile_values(self.category, self.subcategory, self.characteristics)
        if errors:
            raise ValueError("; ".join(errors))
        limit = check_user_characteristics_limit(self.characteristics, self.category, self.subcategory)
        if limit:
            raise ValueError(limit)
        return self

    @model_validator(mode="after")
    def validate_tiers_against_moq(self):
        if self.price_tiers and self.price_tiers[0].min_units < self.moq_units:
            raise ValueError("Первая ценовая ступень не может быть меньше минимального заказа")
        if any(tier.unit_price_rub > self.price_rub for tier in self.price_tiers):
            raise ValueError("Цена в ступени не может быть выше базовой цены")
        return self


class ProductPatch(ProductRules):
    expected_revision: int | None = Field(default=None, gt=0)
    sources: list[ProductSource] | None = Field(default=None, max_length=10)
    external_id: str | None = Field(default=None, min_length=1, max_length=64)
    name: str | None = Field(default=None, min_length=2, max_length=255)
    category: str | None = Field(default=None, min_length=2, max_length=120)
    subcategory: str | None = Field(default=None, max_length=120)
    characteristics: dict[str, Any] | None = None
    price_rub: Money | None = Field(default=None, gt=0)
    price_tiers: list[ProductPriceTier] | None = None
    moq_units: int | None = Field(default=None, gt=0)
    lead_time_days: int | None = Field(default=None, gt=0)
    stock_units: int | None = Field(default=None, ge=0)


class PublishIn(BaseModel):
    published: bool


class OfferDraftFieldOut(BaseModel):
    name: str
    label: str
    value: Money | int | None
    source: str
    confirmed: bool
    note: str | None = None


class OfferDraftOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    need_id: uuid.UUID
    company_id: uuid.UUID
    status: str
    payload: dict[str, Any]
    fields: list[OfferDraftFieldOut]
    missing: list[str]
    warnings: list[str]
    explanation: str
    created_at: datetime | None = None


class AgentScorecardOut(BaseModel):
    """Оценка работы агентов: конверсия сценариев и участие человека."""

    scope: str
    window_days: int
    offer_drafts_total: int
    offer_drafts_used: int
    offer_draft_conversion_pct: float | None
    average_changed_fields: float
    offers_total: int
    offers_from_drafts: int
    offer_rejections: int = 0
    deals_total: int
    deals_from_drafts: int
    recommendations_total: int
    recommendations_converted: int
    recommendation_conversion_pct: float | None
    human_approvals: int
    blocked_actions: int
    admission_checks: int
    admission_blocked: int
    agent_runs_total: int
    agent_runs_failed: int
    agent_runs_local_route: int
    agent_runs_external_route: int
    agent_runs_mixed_route: int = 0
    agent_runs_rules_route: int = 0
    agent_runs_unknown_route: int = 0
    agent_costed_runs: int = 0
    agent_average_duration_ms: float
    agent_estimated_cost_rub: Amount
    agent_model_versions: list[str] = Field(default_factory=list)
    agent_prompt_versions: list[str] = Field(default_factory=list)
    llm_metrics_available: bool
    notes: list[str]


class RoleQualityBenchmarkOut(BaseModel):
    """Эталон методики: что сравнивается и где лежит."""

    bank: str = "packages/test-fixtures/agent-task-bank/ru_tasks.json"
    tasks: int = 0
    compares: list[str] = Field(default_factory=list)
    available: bool = False


class RoleQualityRoleOut(BaseModel):
    """Качество одной сопоставимой роли. Итогового балла нет осознанно:
    аспекты не компенсируют друг друга, нарушение прав не покрывается скоростью."""

    role: str
    passport: str
    sample: int
    status: str = Field(pattern="^(evaluated|not_evaluated)$")
    completed_runs: int = 0
    completed_share_pct: float | None = None
    critical_fields_total: int = 0
    critical_fields_confirmed: int = 0
    critical_completeness_pct: float | None = None
    conflicts_found: int = 0
    clarification_runs: int = 0
    human_corrections: int = 0
    blocked_actions: int = 0
    average_duration_ms: float | None = None
    known_cost_rub: float | None = None
    costed_share_pct: float | None = None
    model_versions: list[str] = Field(default_factory=list)
    prompt_versions: list[str] = Field(default_factory=list)


class RoleQualityOut(BaseModel):
    """Обоснованная оценка агентных ролей по методике с версией и минимумом наблюдений."""

    scope: str
    window_days: int
    method_version: str
    min_observations: int
    benchmark: RoleQualityBenchmarkOut
    roles: list[RoleQualityRoleOut] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


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
    revenue_rub: Amount | None
    available_capacity_units: int
    capacity_utilization_pct: float | None


# ---------- Мощности ----------

class CapacityConversion(BaseModel):
    category_id: str = Field(min_length=1, max_length=120)
    order_unit: str = Field(min_length=1, max_length=32)
    resource_units_per_order_unit: int = Field(gt=0, le=2147483647, strict=True)
    profile_version: int = Field(default=0, ge=0)


class CapacityEntryIn(BaseModel):
    category_conversions: list[CapacityConversion] = Field(default_factory=list,max_length=47)
    conversions_approved: bool = False
    date: date
    category: str = Field(default="", max_length=120)
    unit: str = Field(default="шт", min_length=1, max_length=32)
    available_units: int = Field(ge=0, le=2147483647)

    @field_validator("category")
    @classmethod
    def clean_category(cls, value: str) -> str:
        return value.strip()

    @field_validator("unit")
    @classmethod
    def clean_unit(cls, value: str) -> str:
        value = value.strip().lower().rstrip(".")
        if not value:
            raise ValueError("Укажите единицу измерения")
        from .category_units import canonical_unit
        return canonical_unit(value)


class CapacityEntryOut(CapacityEntryIn):
    reserved_units: int
    free_units: int


class CapacityPutIn(BaseModel):
    entries: list[CapacityEntryIn] = Field(max_length=366)

    @model_validator(mode="after")
    def distinct_dates(self):
        if len({(entry.date, entry.category, entry.unit) for entry in self.entries}) != len(self.entries):
            raise ValueError("Дата, категория и единица измерения мощности не должны повторяться")
        return self


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


class DocumentDecisionIn(DocumentVerificationIn):
    note: str = Field(min_length=1, max_length=500)

    @model_validator(mode="after")
    def require_note(self):
        if not self.note.strip():
            raise ValueError("Укажите причину решения по документу")
        self.note = self.note.strip()
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

class CategoryCapability(BaseModel):
    category_id: str
    unit: str = "шт"
    characteristics: dict[str, list[JsonValue]] = Field(default_factory=dict)
    min_units: int = Field(default=1, gt=0)
    max_units: int | None = Field(default=None, gt=0)
    profile_version: int = 0

    @model_validator(mode="after")
    def validate_scope(self):
        from .category_units import canonical_unit
        self.unit = canonical_unit(self.unit)
        if self.max_units is not None and self.max_units < self.min_units: raise ValueError("Максимум не может быть меньше минимума")
        if len(self.characteristics) > 25 or any(not values or any(value is None or (isinstance(value,str) and not value.strip()) for value in values) for values in self.characteristics.values()):
            raise ValueError("Для каждого ограничения укажите непустые допустимые значения")
        return self


class CapabilityDetails(BaseModel):
    """Ограниченный структурированный контекст производителя или поставщика."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    business_kind: Literal["manufacturer", "stock_supplier", "both"] = "manufacturer"
    category_scopes: list[CategoryCapability] = Field(default_factory=list,max_length=100)
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
    revision: int = 1
    requirements_evidence: dict[str, Any] | None = None
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    company_id: uuid.UUID
    created_by_user_id: uuid.UUID | None
    category: str
    subcategory: str | None = None
    category_profile: dict[str, Any] | None = None
    characteristics: dict[str, Any]
    volume_units: int
    budget_rub: Amount | None
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
    revision: int = 1
    requirement_decisions: list[dict[str, Any]] = Field(default_factory=list)
    category: str
    subcategory: str | None = None
    category_profile: dict[str, Any] | None = None
    characteristics: dict[str, Any]
    volume_units: int
    deadline_date: date
    visibility: str
    status: str
    valid_until: date | None


class NeedIn(BaseModel):
    _physical_quantity_input: dict | None = PrivateAttr(default=None)
    model_config = ConfigDict(allow_inf_nan=False)
    request_key: uuid.UUID | None = None
    agent_run_id: uuid.UUID | None = None
    agent_run_revision: int | None = Field(default=None, gt=0)
    company_id: uuid.UUID
    category: str = Field(min_length=2, max_length=120)
    subcategory: str | None = Field(default=None, min_length=2, max_length=120)
    characteristics: dict[str, Any] = Field(default_factory=dict)
    volume_units: int = Field(gt=0, le=2147483647)
    budget_rub: Amount | None = Field(default=None, gt=0)
    deadline_date: date
    delivery_address_id: uuid.UUID | None = None
    visibility: str = Field(default="open_anonymized", pattern="^(open_anonymized|selected_producers|closed)$")
    valid_until: date | None = None

    @field_validator("characteristics")
    @classmethod
    def validate_unit(cls, value: dict[str, Any]):
        validate_order_unit(value)
        return value

    @model_validator(mode="after")
    def validate_category_values(self):
        errors = validate_profile_values(self.category, self.subcategory, self.characteristics)
        if errors:
            raise ValueError("; ".join(errors))
        limit = check_user_characteristics_limit(self.characteristics, self.category, self.subcategory)
        if limit:
            raise ValueError(limit)
        return self


class NeedEditIn(NeedIn):
    expected_revision: int = Field(gt=0)
    impact_hash: str | None = Field(default=None, min_length=64, max_length=64)


# ---------- Предложения ----------

class OfferOut(BaseModel):
    commercial_terms: CommercialTerms | None = None
    commercial_quote: dict | None = None
    resource_kind: str = "capacity"
    product_id: uuid.UUID | None = None
    revision: int = 1
    request_key: uuid.UUID | None = None
    sending_warnings: list[str] = Field(default_factory=list)
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    need_id: uuid.UUID
    company_id: uuid.UUID
    created_by_user_id: uuid.UUID | None
    price_rub: Money
    available_units: int
    lead_time_days: int
    delivery_cost_rub: Amount | None
    moq_units: int
    price_tiers: list[dict[str, Any]]
    valid_until: date | None
    status: str


class OfferPriceTierIn(BaseModel):
    model_config = ConfigDict(allow_inf_nan=False)
    min_units: int = Field(gt=0, le=2147483647)
    unit_price_rub: Money = Field(gt=0)


class OfferIn(ProductRules):
    commercial_terms: CommercialTerms | None = None
    resource_kind: Literal["stock", "capacity"] = "capacity"
    product_id: uuid.UUID | None = None
    model_config = ConfigDict(allow_inf_nan=False)
    company_id: uuid.UUID
    price_rub: Money = Field(gt=0)
    available_units: int = Field(gt=0, le=2147483647)
    lead_time_days: int = Field(gt=0)
    delivery_cost_rub: Amount | None = Field(default=None, ge=0)
    moq_units: int = Field(default=1, gt=0)
    price_tiers: list[OfferPriceTierIn] = Field(default_factory=list)
    valid_until: date | None = None
    # Черновик агента, из которого подготовлено предложение: нужен для оценки
    # конверсии сценария и числа правок человека.
    draft_id: uuid.UUID | None = None
    # Ключ идемпотентности повторной отправки: тот же ключ возвращает то же КП.
    request_key: uuid.UUID | None = None


class OfferDraftIn(BaseModel):
    company_id: uuid.UUID


class OfferSendPreviewOut(BaseModel):
    blockers: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    missing: list[str] = Field(default_factory=list)
    can_send: bool = False
    existing_offer_id: uuid.UUID | None = None


class OfferPatch(ProductRules):
    commercial_terms: CommercialTerms | None = None
    model_config = ConfigDict(allow_inf_nan=False)
    expected_revision: int = Field(gt=0)
    price_rub: Money | None = Field(default=None, gt=0)
    available_units: int | None = Field(default=None, gt=0)
    lead_time_days: int | None = Field(default=None, gt=0)
    delivery_cost_rub: Amount | None = Field(default=None, ge=0)
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
    unit: str
    score: int
    competition_level: str
    saturation_risk: str
    unmet_volume_units: int | None
    buyers_count: int
    reasons: list[str]
    missing_data: list[str]
    status: str
    dismissal_reason: str | None = None


class OpportunityDismissIn(BaseModel):
    reason: str = Field(min_length=3, max_length=500)


class PriceTierIn(BaseModel):
    min_units: int = Field(gt=0, le=2147483647)
    unit_price_rub: Money = Field(gt=0)


class ParticipantTermsIn(BaseModel):
    commercial_terms: CommercialTerms | None = None
    baseline_offer_id: uuid.UUID | None = None
    need_id: uuid.UUID
    individual_operations_cost_rub: Amount = Field(default=0, ge=0)
    delivery_cost_rub: Amount | None = Field(default=None, ge=0)
    individual_baseline_cost_rub: Amount | None = Field(default=None, gt=0)
    delivery_days: int = Field(default=1, ge=0)


class GroupOfferPublishIn(BaseModel):
    shared_cost_rub: Amount = Field(default=0, ge=0)
    min_total_units: int = Field(gt=0, le=2147483647)
    max_total_units: int = Field(gt=0, le=2147483647)
    lot_multiple: int = Field(default=1, ge=1, le=2147483647)
    available_capacity_units: int = Field(gt=0, le=2147483647)
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
    lot_multiple: int = 1
    price_tiers: list[dict[str, Any]]
    production_start: date | None
    production_end: date | None
    fill_deadline: date | None
    non_fill_rule: str | None
    status: str
    seller_approval_status: str


class CoalitionMemberOut(BaseModel):
    commercial_estimate: dict | None = None
    model_config = ConfigDict(from_attributes=True)

    need_id: uuid.UUID
    buyer_company_id: uuid.UUID | None
    units: int
    individual_operations: dict[str, Any]
    common_cost_rub: Amount | None
    individual_cost_rub: Amount | None
    delivery_cost_rub: Amount | None
    total_cost_rub: Amount | None
    baseline_cost_rub: Amount | None
    benefit_rub: Amount | None
    approval_status: str


class CoalitionOut(BaseModel):
    id: uuid.UUID
    producer_company_id: uuid.UUID | None
    category: str
    unit: str
    combined_volume_units: int
    confirmed_volume_units: int = 0
    target_moq_units: int | None
    status: str
    version: int
    explanation: list[str]
    members: list[CoalitionMemberOut]
    group_offer: GroupOfferOut | None = None


class CoalitionDecisionIn(BaseModel):
    company_id: uuid.UUID
    decision: Literal["approved", "rejected"]
    expected_revision: int = Field(ge=1)
    request_key: uuid.UUID | None = None


# ---------- Устойчивость, N-1 / N-2 и резерв ----------

class ResiliencePlanCreateIn(BaseModel):
    variant_id: uuid.UUID
    max_price_increase_pct: float = Field(default=5, ge=0, le=100)
    max_delay_days: int = Field(default=0, ge=0, le=365)
    auto_replace_within_thresholds: bool = False


class ResiliencePlanConfirmIn(BaseModel):
    approved: Literal[True]
    expected_revision: int | None = Field(default=None, gt=0)


class ReserveDecisionIn(BaseModel):
    commercial_terms: CommercialTerms | None = None
    company_id: uuid.UUID
    decision: Literal["approved", "rejected"]
    capacity_units: int | None = Field(default=None, gt=0)
    moq_units: int | None = Field(default=None, gt=0)
    unit_price_rub: Money | None = Field(default=None, gt=0)
    delivery_cost_rub: Amount | None = Field(default=None, ge=0)
    lead_time_days: int | None = Field(default=None, gt=0)
    price_tiers: list[PriceTierIn] = Field(default_factory=list)
    held_until: date | None = None
    switchover_days: int | None = Field(default=None, ge=0, le=365)


class FailureSimulationIn(BaseModel):
    failed_company_ids: list[uuid.UUID] = Field(min_length=1, max_length=2)


class ProducerFailureIn(BaseModel):
    company_id: uuid.UUID
    reason: str = Field(min_length=3, max_length=500)


class ReserveCommitmentOut(BaseModel):
    effective_tier: str = "cold"
    available_units: int = 0
    availability_reason: str | None = None
    commercial_snapshot: dict | None = None
    commercial_terms: dict | None = None
    commercial_terms: CommercialTerms | None = None
    commercial_snapshot: dict | None = None
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    plan_id: uuid.UUID
    company_id: uuid.UUID
    offer_id: uuid.UUID | None
    reserve_tier: str
    confirmation_status: str
    proposed_capacity_units: int | None
    proposed_moq_units: int | None
    proposed_unit_price_rub: Money | None
    proposed_delivery_cost_rub: Amount | None
    proposed_lead_time_days: int | None
    price_tiers: list[dict[str, Any]]
    confirmed_capacity_units: int | None
    confirmed_moq_units: int | None
    confirmed_unit_price_rub: Money | None
    confirmed_delivery_cost_rub: Amount | None
    confirmed_lead_time_days: int | None
    held_until: date | None
    switchover_days: int | None = None

class PrimaryObligationOut(BaseModel):
    plan_id: uuid.UUID
    need_id: uuid.UUID
    company_id: uuid.UUID
    allocation: dict[str, Any]
    plan_status: str
    confirmed_at: datetime | None


class ResilienceScenarioOut(BaseModel):
    is_current: bool = True
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
    commercial_snapshot: dict | None = None
    id: uuid.UUID
    need_id: uuid.UUID
    buyer_company_id: uuid.UUID
    baseline_variant_id: uuid.UUID
    baseline_allocations: list[dict[str, Any]]
    baseline_total_cost_rub: Amount
    baseline_lead_time_days: int
    current_allocations: list[dict[str, Any]]
    current_total_cost_rub: Amount
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
    execution_contract: str = "legacy"
    resilience_plan_id: uuid.UUID | None = None
    resilience_scenario_id: uuid.UUID | None = None
    commercial_snapshot: dict | None = None
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    offer_id: uuid.UUID
    need_id: uuid.UUID
    buyer_company_id: uuid.UUID
    seller_company_id: uuid.UUID
    performed_by_user_id: uuid.UUID | None
    units: int
    total_price_rub: Amount
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
    request_key: uuid.UUID | None = None
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
    request_key: uuid.UUID | None = None


class RepeatChangeOut(BaseModel):
    field: str
    was: str | None = None
    now: str | None = None


class RepeatPreviewOut(BaseModel):
    """Сравнение прошлой потребности с текущими условиями до повтора.

    Только чтение: повтор выполняется отдельным запросом с новыми датами.
    """

    changes: list[RepeatChangeOut] = Field(default_factory=list)
    not_carried: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class NextStepOut(BaseModel):
    """Персональный следующий шаг: первое невыполненное действие."""

    title: str
    description: str
    href: str


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
    hazard_class: str | None = Field(default=None, max_length=32)
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
    hazard_class: str | None = None
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
    average_unit_price_rub: Amount
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
    confirmed_savings_rub: Amount
    calculated_variants_rub: Amount
    coalitions_count: int
    explanation: str


class OfferSelectIn(BaseModel):
    expected_revision: int = Field(gt=0)
    human_approved: Literal[True]
    request_key: uuid.UUID | None = None
