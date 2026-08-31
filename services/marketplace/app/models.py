import uuid
from datetime import date, datetime

from sqlalchemy import Boolean, Date, DateTime, Float, ForeignKey, Integer, String, UniqueConstraint, func, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from .database import Base

SCHEMA = "marketplace"


def _uuid() -> uuid.UUID:
    return uuid.uuid4()


# Примечание: колонки company_id / user_id ссылаются на таблицы схемы `auth`
# (gateway-auth) по соглашению о UUID. Кросс-схемные FK на уровне БД не
# создаются — целостность проверяется на уровне приложения (guard'ы).


class DeliveryAddress(Base):
    __tablename__ = "delivery_addresses"
    __table_args__ = {"schema": SCHEMA}

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    company_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    address: Mapped[str] = mapped_column(String(500), nullable=False)
    city: Mapped[str] = mapped_column(String(120), nullable=False)
    region: Mapped[str] = mapped_column(String(120), nullable=False)
    is_default: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=text("false"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class ProductionProfile(Base):
    __tablename__ = "production_profiles"
    __table_args__ = {"schema": SCHEMA}

    company_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    production_site_address: Mapped[str | None] = mapped_column(String(500), nullable=True)
    region: Mapped[str | None] = mapped_column(String(120), nullable=True)
    about: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class Product(Base):
    __tablename__ = "products"
    __table_args__ = {"schema": SCHEMA}

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    company_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    category: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    characteristics: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    price_rub: Mapped[float] = mapped_column(Float, nullable=False)
    moq_units: Mapped[int] = mapped_column(Integer, nullable=False)
    lead_time_days: Mapped[int] = mapped_column(Integer, nullable=False)
    is_published: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=text("false"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class CapacityEntry(Base):
    __tablename__ = "capacity_entries"
    __table_args__ = (UniqueConstraint("company_id", "date", name="uq_capacity_company_date"), {"schema": SCHEMA})

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    company_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    date: Mapped[date] = mapped_column(Date, nullable=False)
    available_units: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class Document(Base):
    __tablename__ = "documents"
    __table_args__ = {"schema": SCHEMA}

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    company_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    document_type: Mapped[str] = mapped_column(String(120), nullable=False)
    file_key: Mapped[str] = mapped_column(String(500), nullable=False)
    content_type: Mapped[str] = mapped_column(String(120), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class CapabilityPassport(Base):
    __tablename__ = "capability_passports"
    __table_args__ = {"schema": SCHEMA}

    company_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    technologies: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    equipment: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    materials: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    size_ranges: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    tolerances: Mapped[str | None] = mapped_column(String(500), nullable=True)
    certifications: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    min_order_units: Mapped[int | None] = mapped_column(Integer, nullable=True)
    max_order_units: Mapped[int | None] = mapped_column(Integer, nullable=True)
    delivery_regions: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    completed_order_types: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class Need(Base):
    __tablename__ = "needs"
    __table_args__ = {"schema": SCHEMA}

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    company_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    category: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    characteristics: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    volume_units: Mapped[int] = mapped_column(Integer, nullable=False)
    budget_rub: Mapped[float | None] = mapped_column(Float, nullable=True)
    deadline_date: Mapped[date] = mapped_column(Date, nullable=False)
    delivery_address_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey(f"{SCHEMA}.delivery_addresses.id", ondelete="SET NULL"), nullable=True
    )
    visibility: Mapped[str] = mapped_column(String(32), nullable=False, default="open_anonymized")
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="draft", server_default="draft"
    )
    valid_until: Mapped[date | None] = mapped_column(Date, nullable=True)
    no_match_reason: Mapped[str | None] = mapped_column(String(500), nullable=True)
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class NeedFile(Base):
    __tablename__ = "need_files"
    __table_args__ = {"schema": SCHEMA}

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    need_id: Mapped[uuid.UUID] = mapped_column(ForeignKey(f"{SCHEMA}.needs.id", ondelete="CASCADE"), nullable=False)
    file_name: Mapped[str] = mapped_column(String(255), nullable=False)
    file_key: Mapped[str] = mapped_column(String(500), nullable=False)
    content_type: Mapped[str] = mapped_column(String(120), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class Offer(Base):
    __tablename__ = "offers"
    __table_args__ = {"schema": SCHEMA}

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    need_id: Mapped[uuid.UUID] = mapped_column(ForeignKey(f"{SCHEMA}.needs.id", ondelete="CASCADE"), nullable=False)
    company_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    price_rub: Mapped[float] = mapped_column(Float, nullable=False)
    available_units: Mapped[int] = mapped_column(Integer, nullable=False)
    lead_time_days: Mapped[int] = mapped_column(Integer, nullable=False)
    delivery_cost_rub: Mapped[float] = mapped_column(
        Float, nullable=False, default=0, server_default="0"
    )
    moq_units: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    price_tiers: Mapped[list] = mapped_column(JSONB, nullable=False, default=list, server_default="[]")
    valid_until: Mapped[date | None] = mapped_column(Date, nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="sent")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class Deal(Base):
    __tablename__ = "deals"
    __table_args__ = {"schema": SCHEMA}

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    offer_id: Mapped[uuid.UUID] = mapped_column(ForeignKey(f"{SCHEMA}.offers.id", ondelete="CASCADE"), nullable=False)
    need_id: Mapped[uuid.UUID] = mapped_column(ForeignKey(f"{SCHEMA}.needs.id", ondelete="CASCADE"), nullable=False)
    buyer_company_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    seller_company_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    performed_by_user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    units: Mapped[int] = mapped_column(Integer, nullable=False)
    total_price_rub: Mapped[float] = mapped_column(Float, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="created")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class Notification(Base):
    __tablename__ = "notifications"
    __table_args__ = {"schema": SCHEMA}

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    message: Mapped[str] = mapped_column(String(1000), nullable=False)
    type: Mapped[str] = mapped_column(String(64), nullable=False, default="info")
    is_read: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=text("false"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class MatchEvent(Base):
    __tablename__ = "match_events"
    __table_args__ = {"schema": SCHEMA}

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    entity_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="processed")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class MarketOpportunity(Base):
    __tablename__ = "market_opportunities"
    __table_args__ = (
        UniqueConstraint("company_id", "category", name="uq_opportunity_company_category"),
        {"schema": SCHEMA},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    company_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    category: Mapped[str] = mapped_column(String(120), nullable=False)
    score: Mapped[int] = mapped_column(Integer, nullable=False)
    competition_level: Mapped[str] = mapped_column(String(32), nullable=False)
    saturation_risk: Mapped[str] = mapped_column(String(32), nullable=False)
    unmet_volume_units: Mapped[int] = mapped_column(Integer, nullable=False)
    buyers_count: Mapped[int] = mapped_column(Integer, nullable=False)
    need_ids: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    reasons: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    missing_data: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="active")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class CompatibilityProfile(Base):
    __tablename__ = "compatibility_profiles"
    __table_args__ = {"schema": SCHEMA}

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    category: Mapped[str] = mapped_column(String(120), nullable=False)
    common_base: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    hard_constraints: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    flexible_parameters: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    individual_parts: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    input_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class Coalition(Base):
    __tablename__ = "coalitions"
    __table_args__ = {"schema": SCHEMA}

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    compatibility_profile_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey(f"{SCHEMA}.compatibility_profiles.id", ondelete="CASCADE"), nullable=False
    )
    producer_company_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    category: Mapped[str] = mapped_column(String(120), nullable=False)
    combined_volume_units: Mapped[int] = mapped_column(Integer, nullable=False)
    target_moq_units: Mapped[int | None] = mapped_column(Integer, nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="candidate")
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    explanation: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class CoalitionMember(Base):
    __tablename__ = "coalition_members"
    __table_args__ = (
        UniqueConstraint("coalition_id", "need_id", name="uq_coalition_member_need"),
        {"schema": SCHEMA},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    coalition_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey(f"{SCHEMA}.coalitions.id", ondelete="CASCADE"), nullable=False
    )
    need_id: Mapped[uuid.UUID] = mapped_column(ForeignKey(f"{SCHEMA}.needs.id", ondelete="CASCADE"), nullable=False)
    buyer_company_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    units: Mapped[int] = mapped_column(Integer, nullable=False)
    individual_operations: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    common_cost_rub: Mapped[float | None] = mapped_column(Float, nullable=True)
    individual_cost_rub: Mapped[float | None] = mapped_column(Float, nullable=True)
    delivery_cost_rub: Mapped[float | None] = mapped_column(Float, nullable=True)
    total_cost_rub: Mapped[float | None] = mapped_column(Float, nullable=True)
    baseline_cost_rub: Mapped[float | None] = mapped_column(Float, nullable=True)
    benefit_rub: Mapped[float | None] = mapped_column(Float, nullable=True)
    approval_status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")


class GroupOffer(Base):
    __tablename__ = "group_offers"
    __table_args__ = {"schema": SCHEMA}

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    coalition_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey(f"{SCHEMA}.coalitions.id", ondelete="CASCADE"), nullable=False
    )
    company_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    opportunity_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey(f"{SCHEMA}.market_opportunities.id", ondelete="SET NULL"), nullable=True
    )
    min_total_units: Mapped[int | None] = mapped_column(Integer, nullable=True)
    max_total_units: Mapped[int | None] = mapped_column(Integer, nullable=True)
    price_tiers: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    production_start: Mapped[date | None] = mapped_column(Date, nullable=True)
    production_end: Mapped[date | None] = mapped_column(Date, nullable=True)
    fill_deadline: Mapped[date | None] = mapped_column(Date, nullable=True)
    non_fill_rule: Mapped[str | None] = mapped_column(String(64), nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="draft")
    seller_approval_status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class ParticipantOrder(Base):
    __tablename__ = "participant_orders"
    __table_args__ = (
        UniqueConstraint("coalition_id", "need_id", name="uq_participant_order_need"),
        {"schema": SCHEMA},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    coalition_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey(f"{SCHEMA}.coalitions.id", ondelete="CASCADE"), nullable=False
    )
    group_offer_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey(f"{SCHEMA}.group_offers.id", ondelete="CASCADE"), nullable=False
    )
    need_id: Mapped[uuid.UUID] = mapped_column(ForeignKey(f"{SCHEMA}.needs.id", ondelete="CASCADE"), nullable=False)
    buyer_company_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    seller_company_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    units: Mapped[int] = mapped_column(Integer, nullable=False)
    total_price_rub: Mapped[float] = mapped_column(Float, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="created")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class OptimizationVariantRecord(Base):
    __tablename__ = "optimization_variants"
    __table_args__ = (
        UniqueConstraint("need_id", "kind", "input_hash", name="uq_variant_need_kind_hash"),
        {"schema": SCHEMA},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    need_id: Mapped[uuid.UUID] = mapped_column(ForeignKey(f"{SCHEMA}.needs.id", ondelete="CASCADE"), nullable=False)
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    result: Mapped[dict] = mapped_column(JSONB, nullable=False)
    input_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
