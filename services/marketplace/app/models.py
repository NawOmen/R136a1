import uuid
from decimal import Decimal
from datetime import date, datetime

from sqlalchemy import Boolean, CheckConstraint, Date, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint, Index, func, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from .database import Base
from .category_profile_snapshot import profile_for_insert
from .money_storage import ExactJSONB, ExactNumeric

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
    photo_file_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    photo_file_key: Mapped[str | None] = mapped_column(String(500), nullable=True)
    photo_content_type: Mapped[str | None] = mapped_column(String(80), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class Product(Base):
    __tablename__ = "products"
    __table_args__ = (
        UniqueConstraint("company_id", "external_id", name="uq_product_company_external"),
        {"schema": SCHEMA},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    company_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    external_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    sources: Mapped[list] = mapped_column(ExactJSONB, nullable=False, default=list, server_default="[]")
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    category: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    subcategory: Mapped[str | None] = mapped_column(String(120), nullable=True)
    characteristics: Mapped[dict] = mapped_column(ExactJSONB, nullable=False, default=dict)
    quantity_conversion: Mapped[dict | None] = mapped_column(ExactJSONB(none_as_null=True), nullable=True)
    category_profile: Mapped[dict | None] = mapped_column(ExactJSONB(none_as_null=True), nullable=True, default=profile_for_insert)
    price_rub: Mapped[Decimal] = mapped_column(ExactNumeric(), nullable=False)
    price_tiers: Mapped[list] = mapped_column(ExactJSONB, nullable=False, default=list, server_default="[]")
    moq_units: Mapped[int] = mapped_column(Integer, nullable=False)
    lead_time_days: Mapped[int] = mapped_column(Integer, nullable=False)
    # Остаток на складе нужен для роли «поставка со склада»; производственная
    # мощность по датам хранится отдельно, в capacity_entries.
    stock_units: Mapped[int | None] = mapped_column(Integer, nullable=True)
    stock_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    is_published: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=text("false"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class ProductImage(Base):
    __tablename__ = "product_images"
    __table_args__ = (UniqueConstraint("product_id", "position", name="uq_product_image_position"), {"schema": SCHEMA})

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    product_id: Mapped[uuid.UUID] = mapped_column(ForeignKey(f"{SCHEMA}.products.id", ondelete="CASCADE"), nullable=False)
    file_name: Mapped[str] = mapped_column(String(255), nullable=False)
    file_key: Mapped[str] = mapped_column(String(500), nullable=False)
    content_type: Mapped[str] = mapped_column(String(80), nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class CapacityEntry(Base):
    __tablename__ = "capacity_entries"
    __table_args__ = (UniqueConstraint("company_id", "date", "category", "unit", name="uq_capacity_company_date_scope"), {"schema": SCHEMA})

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    company_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    date: Mapped[date] = mapped_column(Date, nullable=False)
    category: Mapped[str] = mapped_column(String(120), nullable=False, default="", server_default="")
    unit: Mapped[str] = mapped_column(String(32), nullable=False, default="шт", server_default="шт")
    available_units: Mapped[int] = mapped_column(Integer, nullable=False)
    category_conversions: Mapped[list] = mapped_column(ExactJSONB, nullable=False, default=list, server_default="[]")
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
    verification_status: Mapped[str] = mapped_column(
        String(24), nullable=False, default="unverified", server_default="unverified"
    )
    # Область действия и решение проверяющего: без них документ не считается
    # доказательством допуска, даже если файл загружен.
    scope_category: Mapped[str | None] = mapped_column(String(120), nullable=True)
    scope_subcategory: Mapped[str | None] = mapped_column(String(120), nullable=True)
    valid_until: Mapped[date | None] = mapped_column(Date, nullable=True)
    # Подтверждённые проверяющим значения характеристик изделия: например,
    # {"material": ["крафт-картон"], "coating": ["PE"]}.
    confirms: Mapped[dict] = mapped_column(ExactJSONB, nullable=False, default=dict, server_default="{}")
    verified_by_user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    verification_note: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class CapabilityPassport(Base):
    __tablename__ = "capability_passports"
    __table_args__ = {"schema": SCHEMA}

    company_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    details: Mapped[dict] = mapped_column(ExactJSONB, nullable=False, default=dict, server_default="{}")
    technologies: Mapped[list] = mapped_column(ExactJSONB, nullable=False, default=list)
    equipment: Mapped[list] = mapped_column(ExactJSONB, nullable=False, default=list)
    materials: Mapped[list] = mapped_column(ExactJSONB, nullable=False, default=list)
    size_ranges: Mapped[dict] = mapped_column(ExactJSONB, nullable=False, default=dict)
    tolerances: Mapped[str | None] = mapped_column(String(500), nullable=True)
    certifications: Mapped[list] = mapped_column(ExactJSONB, nullable=False, default=list)
    min_order_units: Mapped[int | None] = mapped_column(Integer, nullable=True)
    max_order_units: Mapped[int | None] = mapped_column(Integer, nullable=True)
    delivery_regions: Mapped[list] = mapped_column(ExactJSONB, nullable=False, default=list)
    completed_order_types: Mapped[list] = mapped_column(ExactJSONB, nullable=False, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class Need(Base):
    __tablename__ = "needs"
    __table_args__ = (UniqueConstraint("company_id", "request_key", name="uq_need_request"), {"schema": SCHEMA})

    request_key: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    request_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    revision: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    requirements_evidence: Mapped[dict | None] = mapped_column(ExactJSONB(none_as_null=True), nullable=True)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    company_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    category: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    subcategory: Mapped[str | None] = mapped_column(String(120), nullable=True)
    characteristics: Mapped[dict] = mapped_column(ExactJSONB, nullable=False, default=dict)
    category_profile: Mapped[dict | None] = mapped_column(ExactJSONB(none_as_null=True), nullable=True, default=profile_for_insert)
    volume_units: Mapped[int] = mapped_column(Integer, nullable=False)
    budget_rub: Mapped[Decimal | None] = mapped_column(ExactNumeric(), nullable=True)
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


class NeedRevision(Base):
    __tablename__ = "need_revisions"
    __table_args__ = (UniqueConstraint("need_id", "revision", name="uq_need_revision"), {"schema": SCHEMA})
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    need_id: Mapped[uuid.UUID] = mapped_column(ForeignKey(f"{SCHEMA}.needs.id", ondelete="CASCADE"), nullable=False)
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    snapshot: Mapped[dict] = mapped_column(ExactJSONB, nullable=False)
    impact: Mapped[dict] = mapped_column(ExactJSONB, nullable=False)
    actor_user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class NeedFile(Base):
    __tablename__ = "need_files"
    __table_args__ = {"schema": SCHEMA}

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    need_id: Mapped[uuid.UUID] = mapped_column(ForeignKey(f"{SCHEMA}.needs.id", ondelete="CASCADE"), nullable=False)
    file_name: Mapped[str] = mapped_column(String(255), nullable=False)
    content_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    file_key: Mapped[str] = mapped_column(String(500), nullable=False)
    content_type: Mapped[str] = mapped_column(String(120), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class Offer(Base):
    commercial_terms: Mapped[dict | None] = mapped_column(ExactJSONB(none_as_null=True), nullable=True)
    commercial_quote: Mapped[dict | None] = mapped_column(ExactJSONB(none_as_null=True), nullable=True)
    __tablename__ = "offers"
    __table_args__ = {"schema": SCHEMA}

    resource_kind: Mapped[str] = mapped_column(String(16), default="capacity", server_default="capacity")
    product_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey(f"{SCHEMA}.products.id", ondelete="RESTRICT"), nullable=True)
    revision: Mapped[int] = mapped_column(Integer, default=1, server_default="1")

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    need_id: Mapped[uuid.UUID] = mapped_column(ForeignKey(f"{SCHEMA}.needs.id", ondelete="CASCADE"), nullable=False)
    company_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    request_key: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    price_rub: Mapped[Decimal] = mapped_column(ExactNumeric(), nullable=False)
    available_units: Mapped[int] = mapped_column(Integer, nullable=False)
    lead_time_days: Mapped[int] = mapped_column(Integer, nullable=False)
    delivery_cost_rub: Mapped[Decimal | None] = mapped_column(
        ExactNumeric(), nullable=True, default=None
    )
    moq_units: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    price_tiers: Mapped[list] = mapped_column(ExactJSONB, nullable=False, default=list, server_default="[]")
    valid_until: Mapped[date | None] = mapped_column(Date, nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="sent")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class OfferDraft(Base):
    """Черновик коммерческого предложения, подготовленный агентом.

    Черновик не является обязательством: он показывает предложенные значения
    и источник каждого поля, а продавец подтверждает или исправляет их.
    """

    __tablename__ = "offer_drafts"
    __table_args__ = {"schema": SCHEMA}

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    need_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey(f"{SCHEMA}.needs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    company_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="draft", server_default="draft"
    )
    payload: Mapped[dict] = mapped_column(ExactJSONB, nullable=False, default=dict)
    fields: Mapped[list] = mapped_column(ExactJSONB, nullable=False, default=list)
    missing: Mapped[list] = mapped_column(ExactJSONB, nullable=False, default=list)
    warnings: Mapped[list] = mapped_column(ExactJSONB, nullable=False, default=list)
    explanation: Mapped[str] = mapped_column(Text, nullable=False, default="")
    used_offer_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    # Поля, которые человек изменил перед отправкой: нужны для оценки агента.
    changed_fields: Mapped[list] = mapped_column(ExactJSONB, nullable=False, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Deal(Base):
    resilience_plan_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey(f"{SCHEMA}.resilience_plans.id", ondelete="RESTRICT"), nullable=True)
    resilience_scenario_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey(f"{SCHEMA}.resilience_scenarios.id", ondelete="RESTRICT"), nullable=True)
    commercial_snapshot: Mapped[dict | None] = mapped_column(ExactJSONB(none_as_null=True), nullable=True)
    __tablename__ = "deals"
    __table_args__ = (
        Index("uq_resilience_baseline_deal", "resilience_plan_id", "seller_company_id", unique=True,
              postgresql_where=text("resilience_plan_id IS NOT NULL AND resilience_scenario_id IS NULL")),
        Index("uq_resilience_recovery_deal", "resilience_scenario_id", "seller_company_id", unique=True,
              postgresql_where=text("resilience_scenario_id IS NOT NULL")),
        {"schema": SCHEMA},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    offer_id: Mapped[uuid.UUID] = mapped_column(ForeignKey(f"{SCHEMA}.offers.id", ondelete="CASCADE"), nullable=False)
    need_id: Mapped[uuid.UUID] = mapped_column(ForeignKey(f"{SCHEMA}.needs.id", ondelete="CASCADE"), nullable=False)
    buyer_company_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    seller_company_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    performed_by_user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    units: Mapped[int] = mapped_column(Integer, nullable=False)
    unit_price_rub: Mapped[Decimal | None] = mapped_column(ExactNumeric(), nullable=True)
    delivery_price_rub: Mapped[Decimal | None] = mapped_column(ExactNumeric(), nullable=True)
    total_price_rub: Mapped[Decimal] = mapped_column(ExactNumeric(), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="created")
    request_key: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    request_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class DealExecutionEvent(Base):
    __tablename__ = "deal_execution_events"
    __table_args__ = (
        UniqueConstraint("deal_id", "actor_company_id", "idempotency_key", name="uq_execution_request"),
        CheckConstraint("units > 0", name="ck_execution_positive_units"),
        {"schema": SCHEMA},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    deal_id: Mapped[uuid.UUID] = mapped_column(ForeignKey(f"{SCHEMA}.deals.id", ondelete="CASCADE"), index=True)
    actor_company_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    actor_user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    idempotency_key: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    kind: Mapped[str] = mapped_column(String(24))
    units: Mapped[int] = mapped_column(Integer)
    note: Mapped[str] = mapped_column(String(1000))
    status: Mapped[str] = mapped_column(String(16))
    decided_by_user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class DealCostSnapshot(Base):
    __tablename__ = "deal_cost_snapshots"
    __table_args__ = {"schema": SCHEMA}

    deal_id: Mapped[uuid.UUID] = mapped_column(ForeignKey(f"{SCHEMA}.deals.id", ondelete="CASCADE"), primary_key=True)
    unit_cost_rub: Mapped[Decimal | None] = mapped_column(ExactNumeric(), nullable=True)
    attributable_expenses_rub: Mapped[Decimal | None] = mapped_column(ExactNumeric(), nullable=True)
    revision: Mapped[int] = mapped_column(Integer, default=1)
    note: Mapped[str] = mapped_column(String(1000))
    updated_by_user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class DealMessage(Base):
    __tablename__ = "deal_messages"
    __table_args__ = {"schema": SCHEMA}

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    deal_id: Mapped[uuid.UUID] = mapped_column(ForeignKey(f"{SCHEMA}.deals.id", ondelete="CASCADE"), nullable=False)
    author_user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    author_company_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    message: Mapped[str] = mapped_column(String(2000), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class DealCheckpoint(Base):
    __tablename__ = "deal_checkpoints"
    __table_args__ = (
        UniqueConstraint("deal_id", "kind", name="uq_deal_checkpoint_kind"),
        {"schema": SCHEMA},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    deal_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey(f"{SCHEMA}.deals.id", ondelete="CASCADE"), nullable=False
    )
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="pending", server_default="pending")
    note: Mapped[str | None] = mapped_column(String(500), nullable=True)
    confirmed_by_user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class DeliveryArrangement(Base):
    __tablename__ = "delivery_arrangements"
    __table_args__ = (UniqueConstraint("deal_id", name="uq_delivery_arrangement_deal"), {"schema": SCHEMA})

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    deal_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey(f"{SCHEMA}.deals.id", ondelete="CASCADE"), nullable=False
    )
    weight_kg: Mapped[float] = mapped_column(Float, nullable=False)
    volume_m3: Mapped[float] = mapped_column(Float, nullable=False)
    cargo_class: Mapped[str] = mapped_column(String(32), nullable=False)
    classification_note: Mapped[str] = mapped_column(String(500), nullable=False)
    method: Mapped[str] = mapped_column(String(32), nullable=False)
    carrier_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    tracking_number: Mapped[str | None] = mapped_column(String(255), nullable=True)
    hazard_class: Mapped[str | None] = mapped_column(String(32), nullable=True)
    buyer_responsible: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=text("true"))
    confirmed_by_user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())


class DealReview(Base):
    __tablename__ = "deal_reviews"
    __table_args__ = (
        UniqueConstraint("deal_id", "reviewer_company_id", name="uq_deal_review_reviewer"),
        {"schema": SCHEMA},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    deal_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey(f"{SCHEMA}.deals.id", ondelete="CASCADE"), nullable=False
    )
    reviewer_company_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    reviewed_company_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    rating: Mapped[int] = mapped_column(Integer, nullable=False)
    comment: Mapped[str] = mapped_column(String(2000), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class ProductPriceObservation(Base):
    specification_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    __tablename__ = "product_price_observations"
    __table_args__ = {"schema": SCHEMA}

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    product_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey(f"{SCHEMA}.products.id", ondelete="CASCADE"), nullable=False, index=True
    )
    category: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    unit_price_rub: Mapped[Decimal] = mapped_column(ExactNumeric(), nullable=False)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class MarketWatch(Base):
    __tablename__ = "market_watches"
    __table_args__ = (
        UniqueConstraint("user_id", "category", name="uq_market_watch_user_category"),
        {"schema": SCHEMA},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    category: Mapped[str] = mapped_column(String(120), nullable=False)
    demand_changes: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=text("true"))
    supply_changes: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=text("true"))
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
    payload: Mapped[dict] = mapped_column(ExactJSONB, nullable=False, default=dict)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="processed")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class MarketOpportunity(Base):
    __tablename__ = "market_opportunities"
    __table_args__ = (
        UniqueConstraint("company_id", "category", "unit", name="uq_opportunity_company_category_unit"),
        {"schema": SCHEMA},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    company_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    category: Mapped[str] = mapped_column(String(120), nullable=False)
    unit: Mapped[str] = mapped_column(String(32), nullable=False, default="шт", server_default="шт")
    score: Mapped[int] = mapped_column(Integer, nullable=False)
    competition_level: Mapped[str] = mapped_column(String(32), nullable=False)
    saturation_risk: Mapped[str] = mapped_column(String(32), nullable=False)
    unmet_volume_units: Mapped[int] = mapped_column(Integer, nullable=False)
    buyers_count: Mapped[int] = mapped_column(Integer, nullable=False)
    need_ids: Mapped[list] = mapped_column(ExactJSONB, nullable=False, default=list)
    reasons: Mapped[list] = mapped_column(ExactJSONB, nullable=False, default=list)
    missing_data: Mapped[list] = mapped_column(ExactJSONB, nullable=False, default=list)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="active")
    dismissal_reason: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class CompatibilityProfile(Base):
    __tablename__ = "compatibility_profiles"
    __table_args__ = {"schema": SCHEMA}

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    category: Mapped[str] = mapped_column(String(120), nullable=False)
    common_base: Mapped[dict] = mapped_column(ExactJSONB, nullable=False, default=dict)
    hard_constraints: Mapped[dict] = mapped_column(ExactJSONB, nullable=False, default=dict)
    flexible_parameters: Mapped[dict] = mapped_column(ExactJSONB, nullable=False, default=dict)
    individual_parts: Mapped[dict] = mapped_column(ExactJSONB, nullable=False, default=dict)
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
    explanation: Mapped[list] = mapped_column(ExactJSONB, nullable=False, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class CoalitionMember(Base):
    commercial_estimate: Mapped[dict | None] = mapped_column(ExactJSONB(none_as_null=True), nullable=True)
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
    individual_operations: Mapped[dict] = mapped_column(ExactJSONB, nullable=False, default=dict)
    common_cost_rub: Mapped[Decimal | None] = mapped_column(ExactNumeric(), nullable=True)
    individual_cost_rub: Mapped[Decimal | None] = mapped_column(ExactNumeric(), nullable=True)
    delivery_cost_rub: Mapped[Decimal | None] = mapped_column(ExactNumeric(), nullable=True)
    total_cost_rub: Mapped[Decimal | None] = mapped_column(ExactNumeric(), nullable=True)
    baseline_cost_rub: Mapped[Decimal | None] = mapped_column(ExactNumeric(), nullable=True)
    benefit_rub: Mapped[Decimal | None] = mapped_column(ExactNumeric(), nullable=True)
    approval_status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")
    decision_request_key: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    decision_request_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)


class CoalitionChangeRequest(Base):
    """S08.04: запрос изменения состава подтверждённой группы.

    Старая группа не удаляется; история и действующее обязательство сохраняются
    до допустимого перехода. Повтор по тому же ключу возвращает тот же запрос.
    """

    __tablename__ = "coalition_change_requests"
    __table_args__ = (
        UniqueConstraint("coalition_id", "idempotency_key", name="uq_coalition_change_request_key"),
        {"schema": SCHEMA},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    coalition_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey(f"{SCHEMA}.coalitions.id", ondelete="CASCADE"), nullable=False
    )
    requested_by_company_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    requested_by_user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    reason: Mapped[str] = mapped_column(String(1000), nullable=False)
    proposed_units: Mapped[dict] = mapped_column(ExactJSONB, nullable=False, default=dict)
    resource_policy: Mapped[str] = mapped_column(String(64), nullable=False, default="release_and_rereserve")
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")
    idempotency_key: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    version_from: Mapped[int] = mapped_column(Integer, nullable=False)
    version_to: Mapped[int | None] = mapped_column(Integer, nullable=True)
    decisions: Mapped[list] = mapped_column(ExactJSONB, nullable=False, default=list, server_default="[]")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


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
    lot_multiple: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    price_tiers: Mapped[list] = mapped_column(ExactJSONB, nullable=False, default=list)
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
    commercial_snapshot: Mapped[dict | None] = mapped_column(ExactJSONB(none_as_null=True), nullable=True)
    __tablename__ = "participant_orders"
    __table_args__ = (
        UniqueConstraint("coalition_id", "need_id", "coalition_version", name="uq_participant_order_need_version"),
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
    total_price_rub: Mapped[Decimal] = mapped_column(ExactNumeric(), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="created")
    coalition_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
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
    result: Mapped[dict] = mapped_column(ExactJSONB, nullable=False)
    input_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class ResiliencePlan(Base):
    failure_allocations: Mapped[list] = mapped_column(ExactJSONB, nullable=False, default=list, server_default="[]")
    commercial_snapshot: Mapped[dict | None] = mapped_column(ExactJSONB(none_as_null=True),nullable=True)
    __tablename__ = "resilience_plans"
    __table_args__ = (
        Index("uq_resilience_plan_current_need", "need_id", unique=True, postgresql_where=text("status != 'stale'")),
        {"schema": SCHEMA},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    need_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey(f"{SCHEMA}.needs.id", ondelete="CASCADE"), nullable=False
    )
    buyer_company_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    baseline_variant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey(f"{SCHEMA}.optimization_variants.id", ondelete="RESTRICT"),
        nullable=False,
    )
    baseline_allocations: Mapped[list] = mapped_column(ExactJSONB, nullable=False)
    baseline_total_cost_rub: Mapped[Decimal] = mapped_column(ExactNumeric(), nullable=False)
    baseline_lead_time_days: Mapped[int] = mapped_column(Integer, nullable=False)
    current_allocations: Mapped[list] = mapped_column(ExactJSONB, nullable=False, default=list)
    current_total_cost_rub: Mapped[Decimal] = mapped_column(ExactNumeric(), nullable=False)
    current_lead_time_days: Mapped[int] = mapped_column(Integer, nullable=False)
    max_price_increase_pct: Mapped[float] = mapped_column(Float, nullable=False, default=5)
    max_delay_days: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    auto_replace_within_thresholds: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false")
    )
    failed_company_ids: Mapped[list] = mapped_column(ExactJSONB, nullable=False, default=list)
    status: Mapped[str] = mapped_column(String(48), nullable=False, default="preparing_reserves")
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    confirmed_by_user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class ReserveCommitment(Base):
    commercial_terms: Mapped[dict | None] = mapped_column(ExactJSONB(none_as_null=True), nullable=True)
    commercial_snapshot: Mapped[dict | None] = mapped_column(ExactJSONB(none_as_null=True), nullable=True)
    __tablename__ = "reserve_commitments"
    __table_args__ = (
        UniqueConstraint("plan_id", "company_id", name="uq_reserve_plan_company"),
        {"schema": SCHEMA},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    plan_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey(f"{SCHEMA}.resilience_plans.id", ondelete="CASCADE"), nullable=False
    )
    company_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    offer_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey(f"{SCHEMA}.offers.id", ondelete="SET NULL"), nullable=True
    )
    reserve_tier: Mapped[str] = mapped_column(String(16), nullable=False)
    confirmation_status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")
    proposed_capacity_units: Mapped[int | None] = mapped_column(Integer, nullable=True)
    proposed_moq_units: Mapped[int | None] = mapped_column(Integer, nullable=True)
    proposed_unit_price_rub: Mapped[Decimal | None] = mapped_column(ExactNumeric(), nullable=True)
    proposed_delivery_cost_rub: Mapped[Decimal | None] = mapped_column(ExactNumeric(), nullable=True)
    proposed_lead_time_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    price_tiers: Mapped[list] = mapped_column(ExactJSONB, nullable=False, default=list)
    confirmed_capacity_units: Mapped[int | None] = mapped_column(Integer, nullable=True)
    confirmed_moq_units: Mapped[int | None] = mapped_column(Integer, nullable=True)
    confirmed_unit_price_rub: Mapped[Decimal | None] = mapped_column(ExactNumeric(), nullable=True)
    confirmed_delivery_cost_rub: Mapped[Decimal | None] = mapped_column(ExactNumeric(), nullable=True)
    confirmed_lead_time_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    held_until: Mapped[date | None] = mapped_column(Date, nullable=True)
    switchover_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    confirmed_by_user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class ResilienceScenario(Base):
    __tablename__ = "resilience_scenarios"
    __table_args__ = {"schema": SCHEMA}

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    plan_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey(f"{SCHEMA}.resilience_plans.id", ondelete="CASCADE"), nullable=False
    )
    scenario_type: Mapped[str] = mapped_column(String(24), nullable=False)
    failed_company_ids: Mapped[list] = mapped_column(ExactJSONB, nullable=False)
    result: Mapped[dict] = mapped_column(ExactJSONB, nullable=False)
    input_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="calculated")
    is_simulation: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false")
    )
    approved_by_user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class ResilienceEvent(Base):
    __tablename__ = "resilience_events"
    __table_args__ = {"schema": SCHEMA}

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    plan_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey(f"{SCHEMA}.resilience_plans.id", ondelete="CASCADE"), nullable=False
    )
    event_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    actor_company_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    payload: Mapped[dict] = mapped_column(ExactJSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class TrustAuditEvent(Base):
    __tablename__ = "trust_audit_events"
    __table_args__ = (UniqueConstraint("sequence", name="uq_trust_audit_sequence"), {"schema": SCHEMA})

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    previous_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    event_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    event_type: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    entity_type: Mapped[str] = mapped_column(String(80), nullable=False)
    entity_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    actor_company_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    source_refs: Mapped[list] = mapped_column(ExactJSONB, nullable=False, default=list)
    explanation: Mapped[str] = mapped_column(Text, nullable=False)
    payload: Mapped[dict] = mapped_column(ExactJSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class HumanApprovalRecord(Base):
    __tablename__ = "human_approval_records"
    __table_args__ = (
        CheckConstraint("decision IN ('approved', 'rejected')", name="ck_human_approval_decision"),
        {"schema": SCHEMA},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    action: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    entity_type: Mapped[str] = mapped_column(String(80), nullable=False)
    entity_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    actor_user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    actor_company_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    permission: Mapped[str] = mapped_column(String(80), nullable=False)
    decision: Mapped[str] = mapped_column(String(24), nullable=False)
    reason: Mapped[str | None] = mapped_column(String(500), nullable=True)
    payload_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class SupportTicket(Base):
    __tablename__ = "support_tickets"
    __table_args__ = {"schema": SCHEMA}

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    company_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    subject: Mapped[str] = mapped_column(String(200), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="new", server_default="new")
    admin_response: Mapped[str | None] = mapped_column(Text, nullable=True)
    assigned_admin_user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())


class ResourceReservation(Base):
    __tablename__ = "resource_reservations"
    __table_args__ = (
        CheckConstraint("units > 0", name="ck_reservation_positive"),
        CheckConstraint("(product_id IS NOT NULL) <> (capacity_entry_id IS NOT NULL)", name="ck_one_resource"),
        UniqueConstraint("anchor_type", "anchor_id", "product_id", name="uq_stock_anchor"),
        UniqueConstraint("anchor_type", "anchor_id", "capacity_entry_id", name="uq_capacity_anchor"),
        {"schema": SCHEMA},
    )
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    company_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), index=True)
    product_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey(f"{SCHEMA}.products.id", ondelete="RESTRICT"), nullable=True)
    capacity_entry_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey(f"{SCHEMA}.capacity_entries.id", ondelete="RESTRICT"), nullable=True)
    anchor_type: Mapped[str] = mapped_column(String(24))
    anchor_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), index=True)
    units: Mapped[int] = mapped_column(Integer)
    resource_units: Mapped[int | None] = mapped_column(Integer, nullable=True)
    resource_conversion: Mapped[dict | None] = mapped_column(ExactJSONB, nullable=True)
    status: Mapped[str] = mapped_column(String(16), default="committed")
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class CatalogImport(Base):
    __tablename__ = "catalog_imports"
    __table_args__ = (UniqueConstraint("company_id", "request_key", name="uq_catalog_import_request"), {"schema": SCHEMA})
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    company_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    request_key: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    content_hash: Mapped[str] = mapped_column(String(64))
    product_ids: Mapped[list] = mapped_column(ExactJSONB)
    updated_ids: Mapped[list] = mapped_column(ExactJSONB, nullable=False, default=list, server_default="[]")
    updated_snapshots: Mapped[list] = mapped_column(ExactJSONB, nullable=False, default=list, server_default="[]")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class CategoryRegistryRevision(Base):
    __tablename__ = "category_registry_revisions"
    __table_args__ = {"schema": SCHEMA}
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False, unique=True)
    parent_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    registry_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    registry: Mapped[dict] = mapped_column(ExactJSONB, nullable=False)
    published_by_user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
