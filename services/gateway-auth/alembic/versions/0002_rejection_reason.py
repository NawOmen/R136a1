"""add rejection_reason to companies

Revision ID: 0002
Revises: 0001
Create Date: 2026-08-27

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("companies", sa.Column("rejection_reason", sa.String(length=500), nullable=True), schema="auth")


def downgrade() -> None:
    op.drop_column("companies", "rejection_reason", schema="auth")
