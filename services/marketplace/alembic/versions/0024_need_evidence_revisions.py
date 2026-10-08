"""Persist requirement evidence and immutable specification revisions."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision = "0024"
down_revision = "0023"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("ALTER TABLE marketplace.needs ADD COLUMN IF NOT EXISTS requirements_evidence JSONB")
    op.execute("ALTER TABLE marketplace.resilience_plans DROP CONSTRAINT IF EXISTS uq_resilience_plan_need")
    op.execute("CREATE UNIQUE INDEX IF NOT EXISTS uq_resilience_plan_current_need ON marketplace.resilience_plans (need_id) WHERE status != 'stale'")
    if sa.inspect(op.get_bind()).has_table("need_revisions", schema="marketplace"):
        return
    op.create_table("need_revisions",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("need_id", UUID(as_uuid=True), sa.ForeignKey("marketplace.needs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("snapshot", JSONB(), nullable=False),
        sa.Column("impact", JSONB(), nullable=False),
        sa.Column("actor_user_id", UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("need_id", "revision", name="uq_need_revision"), schema="marketplace")


def downgrade():
    op.execute("DROP INDEX IF EXISTS marketplace.uq_resilience_plan_current_need")
    op.create_unique_constraint("uq_resilience_plan_need", "resilience_plans", ["need_id"], schema="marketplace")
    op.drop_table("need_revisions", schema="marketplace")
    op.drop_column("needs", "requirements_evidence", schema="marketplace")
