"""Approval request timestamp is independent of worker heartbeats (stage S04)."""
from alembic import op

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("ALTER TABLE agents.agent_tasks ADD COLUMN IF NOT EXISTS approval_requested_at TIMESTAMPTZ")
    op.execute(
        "UPDATE agents.agent_tasks SET approval_requested_at = updated_at "
        "WHERE state = 'awaiting_approval' AND approval_requested_at IS NULL"
    )


def downgrade():
    op.drop_column("agent_tasks", "approval_requested_at", schema="agents")
