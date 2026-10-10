"""Consent idempotency keys for deals and coalition decisions (stage S07)."""
from alembic import op

revision = "0026"
down_revision = "0025"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("ALTER TABLE marketplace.deals ADD COLUMN IF NOT EXISTS request_key UUID")
    op.execute("ALTER TABLE marketplace.deals ADD COLUMN IF NOT EXISTS request_hash VARCHAR(64)")
    op.execute("ALTER TABLE marketplace.coalition_members ADD COLUMN IF NOT EXISTS decision_request_key UUID")
    op.execute("ALTER TABLE marketplace.coalition_members ADD COLUMN IF NOT EXISTS decision_request_hash VARCHAR(64)")


def downgrade():
    op.drop_column("coalition_members", "decision_request_hash", schema="marketplace")
    op.drop_column("coalition_members", "decision_request_key", schema="marketplace")
    op.drop_column("deals", "request_hash", schema="marketplace")
    op.drop_column("deals", "request_key", schema="marketplace")
