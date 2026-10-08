"""Durable local buyer sources and optimistic clarification revision."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("ALTER TABLE agents.agent_runs ADD COLUMN IF NOT EXISTS revision INTEGER NOT NULL DEFAULT 1")
    if sa.inspect(op.get_bind()).has_table("agent_sources", schema="agents"):
        return
    op.create_table("agent_sources",
        sa.Column("run_id", UUID(as_uuid=True), sa.ForeignKey("agents.agent_runs.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("source_id", sa.String(120), primary_key=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column("content_type", sa.String(120), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("original", sa.LargeBinary(), nullable=False),
        sa.Column("extracted_text", sa.Text(), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()), schema="agents")


def downgrade():
    op.drop_table("agent_sources", schema="agents")
    op.drop_column("agent_runs", "revision", schema="agents")
