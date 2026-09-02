"""stage 7 inference metrics

Revision ID: 0002
Revises: 0001
Create Date: 2026-09-02
"""
from typing import Sequence, Union

from alembic import op

revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TABLE agents.agent_runs ADD COLUMN IF NOT EXISTS duration_ms INTEGER")
    op.execute("ALTER TABLE agents.agent_runs ADD COLUMN IF NOT EXISTS input_chars INTEGER")
    op.execute("ALTER TABLE agents.agent_runs ADD COLUMN IF NOT EXISTS output_chars INTEGER")
    op.execute("ALTER TABLE agents.agent_runs ADD COLUMN IF NOT EXISTS estimated_cost_rub DOUBLE PRECISION")
    op.execute("ALTER TABLE agents.agent_runs ADD COLUMN IF NOT EXISTS cost_basis VARCHAR(160)")


def downgrade() -> None:
    op.execute("ALTER TABLE agents.agent_runs DROP COLUMN IF EXISTS cost_basis")
    op.execute("ALTER TABLE agents.agent_runs DROP COLUMN IF EXISTS estimated_cost_rub")
    op.execute("ALTER TABLE agents.agent_runs DROP COLUMN IF EXISTS output_chars")
    op.execute("ALTER TABLE agents.agent_runs DROP COLUMN IF EXISTS input_chars")
    op.execute("ALTER TABLE agents.agent_runs DROP COLUMN IF EXISTS duration_ms")
