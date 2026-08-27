"""initial auth schema

Revision ID: 0001
Revises:
Create Date: 2026-08-26

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS auth")

    op.create_table(
        "users",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("last_name", sa.String(length=120), nullable=False),
        sa.Column("first_name", sa.String(length=120), nullable=False),
        sa.Column("middle_name", sa.String(length=120), nullable=True),
        sa.Column("email", sa.String(length=255), nullable=False),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        sa.Column("phone", sa.String(length=40), nullable=True),
        sa.Column("account_status", sa.String(length=16), server_default="active", nullable=False),
        sa.Column("is_marketplace_admin", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        schema="auth",
    )
    op.create_index("ix_users_email", "users", ["email"], unique=True, schema="auth")

    op.create_table(
        "companies",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("full_name", sa.String(length=255), nullable=False),
        sa.Column("display_name", sa.String(length=255), nullable=False),
        sa.Column("legal_form", sa.String(length=8), nullable=False),
        sa.Column("inn", sa.String(length=12), nullable=False),
        sa.Column("ogrn", sa.String(length=15), nullable=True),
        sa.Column("ogrnip", sa.String(length=15), nullable=True),
        sa.Column("kpp", sa.String(length=9), nullable=True),
        sa.Column("legal_address", sa.String(length=500), nullable=False),
        sa.Column("country", sa.String(length=2), server_default="RU", nullable=False),
        sa.Column("verification_status", sa.String(length=16), server_default="draft", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        schema="auth",
    )

    op.create_table(
        "company_members",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("company_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("can_buy", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("can_sell", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("is_admin", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "company_id", name="uq_company_members_user_company"),
        sa.ForeignKeyConstraint(["user_id"], ["auth.users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["company_id"], ["auth.companies.id"], ondelete="CASCADE"),
        schema="auth",
    )

    op.create_table(
        "company_verification_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("company_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("from_status", sa.String(length=16), nullable=False),
        sa.Column("to_status", sa.String(length=16), nullable=False),
        sa.Column("performed_by_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("reason", sa.String(length=500), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["company_id"], ["auth.companies.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["performed_by_user_id"], ["auth.users.id"], ondelete="SET NULL"),
        schema="auth",
    )


def downgrade() -> None:
    op.drop_table("company_verification_events", schema="auth")
    op.drop_table("company_members", schema="auth")
    op.drop_table("companies", schema="auth")
    op.drop_index("ix_users_email", table_name="users", schema="auth")
    op.drop_table("users", schema="auth")
    op.execute("DROP SCHEMA IF EXISTS auth")
