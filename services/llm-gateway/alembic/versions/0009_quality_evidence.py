"""Immutable first model result and measured human corrections; legacy stays unknown."""
from alembic import op
revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None

def upgrade():
    op.execute("ALTER TABLE agents.agent_runs ADD COLUMN IF NOT EXISTS initial_result JSONB, ADD COLUMN IF NOT EXISTS human_corrections INTEGER NOT NULL DEFAULT 0")

def downgrade():
    op.execute("ALTER TABLE agents.agent_runs DROP COLUMN IF EXISTS initial_result, DROP COLUMN IF EXISTS human_corrections")
