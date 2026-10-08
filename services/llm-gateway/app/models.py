import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import DateTime, Numeric, ForeignKey, Integer, String, Text, LargeBinary, Boolean, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from .database import Base

SCHEMA = "agents"


def _uuid() -> uuid.UUID:
    return uuid.uuid4()


class AgentRun(Base):
    __tablename__ = "agent_runs"
    __table_args__ = {"schema": SCHEMA}

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    company_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True, index=True)
    agent_type: Mapped[str] = mapped_column(String(64), nullable=False)
    state: Mapped[str] = mapped_column(String(64), nullable=False, default="received")
    requested_route: Mapped[str] = mapped_column(String(32), nullable=False, default="local")
    used_route: Mapped[str | None] = mapped_column(String(32), nullable=True)
    model_version: Mapped[str | None] = mapped_column(String(120), nullable=True)
    prompt_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    provider_kind: Mapped[str | None] = mapped_column(String(16), nullable=True)
    input_summary: Mapped[str] = mapped_column(Text, nullable=False, default="")
    result: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    input_chars: Mapped[int | None] = mapped_column(Integer, nullable=True)
    output_chars: Mapped[int | None] = mapped_column(Integer, nullable=True)
    estimated_cost_rub: Mapped[Decimal | None] = mapped_column(Numeric(24,12), nullable=True)
    cost_basis: Mapped[str | None] = mapped_column(String(160), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class AgentSource(Base):
    """Local original and extracted representation; never sent to external review."""
    __tablename__ = "agent_sources"
    __table_args__ = {"schema": SCHEMA}
    run_id: Mapped[uuid.UUID] = mapped_column(ForeignKey(f"{SCHEMA}.agent_runs.id", ondelete="CASCADE"), primary_key=True)
    source_id: Mapped[str] = mapped_column(String(120), primary_key=True)
    name: Mapped[str] = mapped_column(String(255))
    kind: Mapped[str] = mapped_column(String(32))
    content_type: Mapped[str] = mapped_column(String(120))
    content_hash: Mapped[str] = mapped_column(String(64))
    original: Mapped[bytes] = mapped_column(LargeBinary)
    extracted_text: Mapped[str] = mapped_column(Text, default="")
    active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")


class ToolCall(Base):
    __tablename__ = "tool_calls"
    __table_args__ = {"schema": SCHEMA}

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    run_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey(f"{SCHEMA}.agent_runs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    tool_name: Mapped[str] = mapped_column(String(120), nullable=False)
    executor: Mapped[str | None] = mapped_column(String(16), nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    input_summary: Mapped[str] = mapped_column(Text, nullable=False, default="")
    output_summary: Mapped[str] = mapped_column(Text, nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class AgentTask(Base):
    """Сохраняемый task-contract: сквозная задача связывает покупателя, расчётчик,
    поставщика и согласование; остановка и продолжение не теряют состояние."""

    __tablename__ = "agent_tasks"
    __table_args__ = (
        UniqueConstraint("company_id", "idempotency_key", name="uq_agent_tasks_company_key"),
        {"schema": SCHEMA},
    )

    task_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    parent_task_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey(f"{SCHEMA}.agent_tasks.task_id", ondelete="SET NULL"), nullable=True, index=True
    )
    company_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    actor_user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    scenario_type: Mapped[str] = mapped_column(String(64), nullable=False)
    input_revision: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    idempotency_key: Mapped[str] = mapped_column(String(160), nullable=False)
    model_version: Mapped[str | None] = mapped_column(String(120), nullable=True)
    prompt_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    schema_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    source_refs: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    state: Mapped[str] = mapped_column(String(32), nullable=False, default="queued", server_default="queued")
    current_step: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    required_response: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    result_artifact: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    approval: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    linked_run_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey(f"{SCHEMA}.agent_runs.id", ondelete="SET NULL"), nullable=True
    )
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=3, server_default="3")
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class AgentTaskCache(Base):
    """Кеш повторных одинаковых входов. Привязан к компании, входной ревизии
    и версиям источников; инвалидация источника очищает связанные записи."""

    __tablename__ = "agent_task_cache"
    __table_args__ = (
        UniqueConstraint(
            "company_id", "cache_key", "input_hash", "source_versions_hash",
            name="uq_agent_task_cache_binding",
        ),
        {"schema": SCHEMA},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    company_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    cache_key: Mapped[str] = mapped_column(String(200), nullable=False)
    input_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    source_versions_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    run_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey(f"{SCHEMA}.agent_runs.id", ondelete="CASCADE"), nullable=True, index=True
    )
    source_ids: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
