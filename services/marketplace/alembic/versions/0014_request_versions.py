"""Request retries, file deduplication and offer revision preconditions."""
from alembic import op

revision = "0014"
down_revision = "0013"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("ALTER TABLE marketplace.needs ADD COLUMN IF NOT EXISTS request_key UUID")
    op.execute("ALTER TABLE marketplace.needs ADD COLUMN IF NOT EXISTS request_hash VARCHAR(64)")
    op.execute("ALTER TABLE marketplace.needs ADD COLUMN IF NOT EXISTS revision INTEGER NOT NULL DEFAULT 1")
    op.execute("CREATE UNIQUE INDEX IF NOT EXISTS uq_need_request ON marketplace.needs(company_id, request_key)")
    op.execute("ALTER TABLE marketplace.offers ADD COLUMN IF NOT EXISTS revision INTEGER NOT NULL DEFAULT 1")
    op.execute("ALTER TABLE marketplace.need_files ADD COLUMN IF NOT EXISTS content_hash VARCHAR(64)")


def downgrade():
    op.execute("ALTER TABLE marketplace.need_files DROP COLUMN content_hash")
    op.execute("ALTER TABLE marketplace.offers DROP COLUMN revision")
    op.execute("ALTER TABLE marketplace.needs DROP COLUMN request_key, DROP COLUMN request_hash, DROP COLUMN revision")
