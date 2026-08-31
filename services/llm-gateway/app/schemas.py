import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

FactValue = str | int | float | bool | list[str]


class SourceDescriptor(BaseModel):
    id: str
    kind: Literal["text", "document", "image", "audio"]
    name: str
    text: str = Field(exclude=True)


class RawFact(BaseModel):
    key: str = Field(min_length=1, max_length=120)
    value: FactValue
    source_id: str = Field(min_length=1, max_length=120)
    confidence: float = Field(ge=0, le=1)
    evidence: str = Field(default="", max_length=500)


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


class RequirementProperty(BaseModel):
    key: str
    label: str
    value: FactValue | None = None
    confidence: float = Field(ge=0, le=1)
    status: Literal["confirmed", "assumed", "needs_clarification"]
    sources: list[EvidenceItem] = Field(default_factory=list)


class RequirementConflict(BaseModel):
    key: str
    label: str
    values: list[FactValue]
    source_ids: list[str]


class ClarificationQuestion(BaseModel):
    key: str
    question: str
    options: list[FactValue] = Field(default_factory=list)


class CapabilityMatch(BaseModel):
    company_id: uuid.UUID
    company_name: str
    score: int = Field(ge=0, le=100)
    reasons: list[str]


class BuyerAgentResult(BaseModel):
    category: str
    properties: list[RequirementProperty]
    conflicts: list[RequirementConflict]
    questions: list[ClarificationQuestion]
    matches: list[CapabilityMatch] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    summary: str
    can_confirm: bool


class ClarificationIn(BaseModel):
    answers: dict[str, FactValue] = Field(min_length=1)


class ToolCallOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    tool_name: str
    status: str
    input_summary: str
    output_summary: str
    created_at: datetime


class AgentRunOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    agent_type: str
    state: str
    requested_route: str
    used_route: str | None
    result: dict[str, Any]
    error: str | None
    created_at: datetime
    updated_at: datetime
    tool_calls: list[ToolCallOut] = Field(default_factory=list)


class SellerExplainIn(BaseModel):
    company_id: uuid.UUID
    category: str = Field(min_length=2, max_length=200)
    requirements: dict[str, FactValue] = Field(default_factory=dict)


class SellerExplainOut(BaseModel):
    eligible: bool
    reasons: list[str]
    explanation: str
    used_route: str


class HealthOut(BaseModel):
    status: str
    local_model: str
    external_enabled: bool
