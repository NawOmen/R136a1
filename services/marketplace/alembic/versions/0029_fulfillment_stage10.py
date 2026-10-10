"""S10: versioned fulfillment, protected attachments and legacy execution migration."""
from alembic import op

revision = "0029"
down_revision = "0028"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("ALTER TABLE marketplace.deals ADD COLUMN IF NOT EXISTS execution_contract VARCHAR(32) NOT NULL DEFAULT 'legacy'")
    op.execute("ALTER TABLE marketplace.deals ALTER COLUMN execution_contract SET DEFAULT 'fulfillment_v3'")
    op.execute("""CREATE TABLE IF NOT EXISTS marketplace.deal_fulfillments (
        deal_id UUID PRIMARY KEY REFERENCES marketplace.deals(id) ON DELETE CASCADE,
        revision INTEGER NOT NULL, data JSONB NOT NULL)""")
    op.execute("""CREATE TABLE IF NOT EXISTS marketplace.deal_attachments (
        id UUID PRIMARY KEY, deal_id UUID NOT NULL REFERENCES marketplace.deals(id) ON DELETE CASCADE,
        company_id UUID NOT NULL, terms_version INTEGER NOT NULL, filename VARCHAR(255) NOT NULL,
        storage_key VARCHAR(255) NOT NULL, content_type VARCHAR(80) NOT NULL, sha256 VARCHAR(64) NOT NULL)""")
    op.execute("CREATE INDEX IF NOT EXISTS ix_marketplace_deal_attachments_deal_id ON marketplace.deal_attachments(deal_id)")
    op.execute("ALTER TABLE marketplace.delivery_arrangements ADD COLUMN IF NOT EXISTS hazard_class VARCHAR(32)")


def downgrade():
    op.execute("ALTER TABLE marketplace.deals DROP COLUMN IF EXISTS execution_contract")
    op.execute("DROP TABLE IF EXISTS marketplace.deal_attachments")
    op.execute("DROP TABLE IF EXISTS marketplace.deal_fulfillments")
    op.execute("ALTER TABLE marketplace.delivery_arrangements DROP COLUMN IF EXISTS hazard_class")
