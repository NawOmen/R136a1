from decimal import Decimal
import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import field_serializer, BaseModel, ConfigDict, Field

FactValue = str | int | float | bool | list[str]


class SourceDescriptor(BaseModel):
    id: str
    kind: Literal["text", "document", "image", "audio"]
    name: str
    text: str = Field(exclude=True)
    content_hash: str = ""


class RawFact(BaseModel):
    key: str = Field(min_length=1, max_length=120)
    value: FactValue
    source_id: str = Field(min_length=1, max_length=120)
    confidence: float = Field(ge=0, le=1)
    evidence: str = Field(default="", max_length=500)
    original_unit: str | None = Field(default=None, max_length=40)


class RawExtraction(BaseModel):
    category: str = Field(min_length=2, max_length=200)
    facts: list[RawFact] = Field(default_factory=list)


class EvidenceItem(BaseModel):
    source_id: str
    source_name: str
    source_kind: str
    value: FactValue
    confidence: float = Field(ge=0, le=1)
    excerpt: str = ""
    original_value: FactValue | None = None
    normalization: Literal["model_city_name"] | None = None
    original_unit: str | None = None
    normalized_unit: str | None = None
    locator: dict[str, Any] = Field(default_factory=dict)
    content_hash: str = ""
    extraction_version: str = "buyer-evidence-1"
    active: bool = True


class RequirementProperty(BaseModel):
    key: str
    label: str
    value: FactValue | None = None
    confidence: float = Field(ge=0, le=1)
    status: Literal["confirmed", "assumed", "needs_clarification"]
    sources: list[EvidenceItem] = Field(default_factory=list)
    confirmed_by_user_id: uuid.UUID | None = None
    confirmed_at: datetime | None = None


class RequirementConflict(BaseModel):
    key: str
    label: str
    values: list[FactValue]
    source_ids: list[str]
    impact: str = "Влияет на соответствие предложения требованиям покупателя"


class ClarificationQuestion(BaseModel):
    key: str
    question: str
    options: list[FactValue] = Field(default_factory=list)


class CatalogReference(BaseModel):
    product_id: uuid.UUID
    name: str
    unit_price_rub: str
    total_rub: str | None = None
    moq_units: int
    lead_time_days: int
    comparable: bool = False
    note: str


class CapabilityMatch(BaseModel):
    company_id: uuid.UUID
    company_name: str
    score: int = Field(ge=0, le=100)
    reasons: list[str]
    details: dict[str, str] = Field(default_factory=dict)
    cautions: list[str] = Field(default_factory=list)
    catalog: list[CatalogReference] = Field(default_factory=list)


class BuyerAgentResult(BaseModel):
    unreadable_sources: list[dict[str, str]] = Field(default_factory=list)
    omitted_source_hashes: list[str] = Field(default_factory=list)
    buyer_company_id: uuid.UUID | None = None
    category: str
    properties: list[RequirementProperty]
    conflicts: list[RequirementConflict]
    questions: list[ClarificationQuestion]
    matches: list[CapabilityMatch] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    summary: str
    can_confirm: bool
    resolved_conflicts: list[dict[str, Any]] = Field(default_factory=list)


class ClarificationIn(BaseModel):
    answers: dict[str, FactValue] = Field(min_length=1)
    expected_revision: int | None = Field(default=None, gt=0)


class RunRevisionIn(BaseModel):
    expected_revision: int = Field(gt=0)


class ToolCallOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    tool_name: str
    executor: str | None = None
    status: str
    input_summary: str
    output_summary: str
    created_at: datetime


class AgentRunOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    revision: int = 1
    agent_type: str
    state: str
    requested_route: str
    used_route: str | None
    model_version: str | None = None
    prompt_version: str | None = None
    provider_kind: str | None = None
    result: dict[str, Any]
    error: str | None
    duration_ms: int | None
    input_chars: int | None
    output_chars: int | None
    estimated_cost_rub: Decimal | None
    @field_serializer('estimated_cost_rub')
    def legacy_cost_number(self, value):
        return float(value) if value is not None else None

    cost_basis: str | None
    created_at: datetime
    updated_at: datetime
    tool_calls: list[ToolCallOut] = Field(default_factory=list)


class SellerExplainIn(BaseModel):
    company_id: uuid.UUID
    category: str = Field(min_length=2, max_length=200)
    requirements: dict[str, FactValue] = Field(default_factory=dict)


class SellerExplainOut(BaseModel):
    run_id: uuid.UUID
    revision: int = 1
    eligible: bool
    reasons: list[str]
    explanation: str
    used_route: str


class HealthOut(BaseModel):
    status: str
    local_backend: Literal["mlx", "ollama"] = "ollama"
    local_model: str
    # Разговорные задачи (справка, объяснения, черновики) обслуживает общая модель.
    assistant_backend: Literal["mlx", "ollama"] = "ollama"
    vision_model: str = ""
    external_enabled: bool


class TranscriptionOut(BaseModel):
    text: str


class PlatformAssistantIn(BaseModel):
    question: str = Field(min_length=3, max_length=1000)


class PlatformAssistantOut(BaseModel):
    answer: str = Field(min_length=1, max_length=2000)
    links: list[str] = Field(default_factory=list, max_length=3)


class RolePassportOut(BaseModel):
    id: str
    title: str
    purpose: str
    inputs: str
    outputs: str
    sources: str
    tools: list[str]
    company_scope: str
    prompt_version: str
    model: str
    schema_version: str
    implemented_by: str
    time_limits: str
    resource_limits: str
    stop_conditions: str
    result: str
    decision_by: str


class TaskCreateIn(BaseModel):
    company_id: uuid.UUID
    scenario_type: str = Field(min_length=1, max_length=64)
    input: dict[str, Any] = Field(default_factory=dict)
    source_refs: list[dict[str, Any]] = Field(default_factory=list)
    idempotency_key: str = Field(min_length=1, max_length=160)
    parent_task_id: uuid.UUID | None = None


class TaskRevisionIn(BaseModel):
    expected_revision: int = Field(gt=0)


class TaskInputIn(BaseModel):
    expected_revision: int = Field(gt=0)
    input: dict[str, Any] = Field(default_factory=dict)
    source_refs: list[dict[str, Any]] = Field(default_factory=list)


class TaskApproveIn(BaseModel):
    expected_revision: int = Field(gt=0)
    approval: dict[str, Any]
    result_artifact: dict[str, Any]


class TaskAttachIn(BaseModel):
    run_id: uuid.UUID


class TaskFailIn(BaseModel):
    expected_revision: int = Field(gt=0)
    error: str = Field(min_length=1, max_length=2000)


class TaskCancelIn(BaseModel):
    expected_revision: int = Field(gt=0)
    reason: str = Field(default="Отменена пользователем", max_length=2000)


class TaskOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    task_id: uuid.UUID
    parent_task_id: uuid.UUID | None
    company_id: uuid.UUID
    actor_user_id: uuid.UUID
    scenario_type: str
    input_revision: int
    idempotency_key: str
    model_version: str | None
    prompt_version: str | None
    schema_version: str | None
    source_refs: list[Any]
    state: str
    current_step: str
    required_response: dict[str, Any] | None
    result_artifact: dict[str, Any] | None
    approval: dict[str, Any] | None
    error: str | None
    linked_run_id: uuid.UUID | None
    attempts: int
    max_attempts: int
    heartbeat_at: datetime | None
    approval_requested_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class TaskCreateOut(TaskOut):
    created: bool = True
