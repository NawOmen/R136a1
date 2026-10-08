import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import DateTime, Numeric, ForeignKey, Integer, String, Text, LargeBinary, Boolean, func
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
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    input_summary: Mapped[str] = mapped_column(Text, nullable=False, default="")
    output_summary: Mapped[str] = mapped_column(Text, nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
