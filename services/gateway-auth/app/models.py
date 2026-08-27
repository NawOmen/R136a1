import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, String, UniqueConstraint, func, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from .database import Base

SCHEMA = "auth"


def _uuid() -> uuid.UUID:
    return uuid.uuid4()


class User(Base):
    __tablename__ = "users"
    __table_args__ = {"schema": SCHEMA}

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    last_name: Mapped[str] = mapped_column(String(120), nullable=False)
    first_name: Mapped[str] = mapped_column(String(120), nullable=False)
    middle_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    email: Mapped[str] = mapped_column(String(255), nullable=False, unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    phone: Mapped[str | None] = mapped_column(String(40), nullable=True)
    account_status: Mapped[str] = mapped_column(String(16), nullable=False, default="active", server_default="active")
    is_marketplace_admin: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=text("false"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class Company(Base):
    __tablename__ = "companies"
    __table_args__ = {"schema": SCHEMA}

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    full_name: Mapped[str] = mapped_column(String(255), nullable=False)
    display_name: Mapped[str] = mapped_column(String(255), nullable=False)
    legal_form: Mapped[str] = mapped_column(String(8), nullable=False)
    inn: Mapped[str] = mapped_column(String(12), nullable=False)
    ogrn: Mapped[str | None] = mapped_column(String(15), nullable=True)
    ogrnip: Mapped[str | None] = mapped_column(String(15), nullable=True)
    kpp: Mapped[str | None] = mapped_column(String(9), nullable=True)
    legal_address: Mapped[str] = mapped_column(String(500), nullable=False)
    country: Mapped[str] = mapped_column(String(2), nullable=False, default="RU", server_default="RU")
    verification_status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="draft", server_default="draft"
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class CompanyMember(Base):
    __tablename__ = "company_members"
    __table_args__ = (
        UniqueConstraint("user_id", "company_id", name="uq_company_members_user_company"),
        {"schema": SCHEMA},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey(f"{SCHEMA}.users.id", ondelete="CASCADE"), nullable=False)
    company_id: Mapped[uuid.UUID] = mapped_column(ForeignKey(f"{SCHEMA}.companies.id", ondelete="CASCADE"), nullable=False)
    can_buy: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=text("false"))
    can_sell: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=text("false"))
    is_admin: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=text("false"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class CompanyVerificationEvent(Base):
    __tablename__ = "company_verification_events"
    __table_args__ = {"schema": SCHEMA}

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    company_id: Mapped[uuid.UUID] = mapped_column(ForeignKey(f"{SCHEMA}.companies.id", ondelete="CASCADE"), nullable=False)
    from_status: Mapped[str] = mapped_column(String(16), nullable=False)
    to_status: Mapped[str] = mapped_column(String(16), nullable=False)
    performed_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey(f"{SCHEMA}.users.id", ondelete="SET NULL"), nullable=True
    )
    reason: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
