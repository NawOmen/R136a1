"""initial agents schema

Revision ID: 0001
Revises:
Create Date: 2026-08-31
"""
from typing import Sequence, Union

from alembic import op

revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS agents")
    from app import models  # noqa: F401
    from app.database import Base

    Base.metadata.create_all(bind=op.get_bind())


def downgrade() -> None:
    from app import models  # noqa: F401
    from app.database import Base

    Base.metadata.drop_all(bind=op.get_bind())
    op.execute("DROP SCHEMA IF EXISTS agents")
