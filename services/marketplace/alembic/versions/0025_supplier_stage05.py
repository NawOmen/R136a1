"""Supplier card versions, provenance, stable external ids, offer idempotency (stage S05)."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision = "0025"
down_revision = "0024"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("ALTER TABLE marketplace.products ADD COLUMN IF NOT EXISTS revision INTEGER NOT NULL DEFAULT 1")
    op.execute("ALTER TABLE marketplace.products ADD COLUMN IF NOT EXISTS external_id VARCHAR(64)")
    op.execute("ALTER TABLE marketplace.products ADD COLUMN IF NOT EXISTS sources JSONB NOT NULL DEFAULT '[]'")
    op.execute(
        "DO $$ BEGIN "
        "IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'uq_product_company_external') THEN "
        "ALTER TABLE marketplace.products ADD CONSTRAINT uq_product_company_external UNIQUE (company_id, external_id); "
        "END IF; END $$"
    )
    op.execute("ALTER TABLE marketplace.offers ADD COLUMN IF NOT EXISTS request_key UUID")
    op.execute("ALTER TABLE marketplace.market_opportunities ADD COLUMN IF NOT EXISTS dismissal_reason VARCHAR(500)")


def downgrade():
    op.drop_column("market_opportunities", "dismissal_reason", schema="marketplace")
    op.drop_column("offers", "request_key", schema="marketplace")
    op.execute("ALTER TABLE marketplace.products DROP CONSTRAINT IF EXISTS uq_product_company_external")
    op.drop_column("products", "sources", schema="marketplace")
    op.drop_column("products", "external_id", schema="marketplace")
    op.drop_column("products", "revision", schema="marketplace")
