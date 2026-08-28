"""stage 3 publication guards and audit

Revision ID: 0002
Revises: 0001
Create Date: 2026-08-28

"""
from typing import Sequence, Union

from alembic import op

revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Revision 0001 historically creates tables from current metadata, so IF NOT EXISTS
    # keeps both a fresh install and an upgrade of an existing stage-3 database valid.
    op.execute(
        "ALTER TABLE marketplace.deals "
        "ADD COLUMN IF NOT EXISTS performed_by_user_id UUID"
    )
    op.execute(
        "ALTER TABLE marketplace.needs ALTER COLUMN status SET DEFAULT 'draft'"
    )


def downgrade() -> None:
    op.execute(
        "ALTER TABLE marketplace.needs ALTER COLUMN status SET DEFAULT 'open_for_offers'"
    )
    op.execute(
        "ALTER TABLE marketplace.deals DROP COLUMN IF EXISTS performed_by_user_id"
    )
