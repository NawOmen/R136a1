"""Shared resource reservations across binding operations."""
from alembic import op

revision = "0015"
down_revision = "0014"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("ALTER TABLE marketplace.offers ADD COLUMN IF NOT EXISTS resource_kind VARCHAR(16) NOT NULL DEFAULT 'capacity'")
    op.execute("ALTER TABLE marketplace.offers ADD COLUMN IF NOT EXISTS product_id UUID REFERENCES marketplace.products(id) ON DELETE RESTRICT")
    op.execute("""CREATE TABLE IF NOT EXISTS marketplace.resource_reservations (
        id UUID PRIMARY KEY, company_id UUID NOT NULL,
        product_id UUID REFERENCES marketplace.products(id) ON DELETE RESTRICT,
        capacity_entry_id UUID REFERENCES marketplace.capacity_entries(id) ON DELETE RESTRICT,
        anchor_type VARCHAR(24) NOT NULL, anchor_id UUID NOT NULL, units INTEGER NOT NULL CHECK (units > 0),
        status VARCHAR(16) NOT NULL, expires_at TIMESTAMPTZ, created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        CHECK ((product_id IS NOT NULL) <> (capacity_entry_id IS NOT NULL)),
        CONSTRAINT uq_stock_anchor UNIQUE(anchor_type, anchor_id, product_id),
        CONSTRAINT uq_capacity_anchor UNIQUE(anchor_type, anchor_id, capacity_entry_id))""")
    op.execute("CREATE INDEX IF NOT EXISTS ix_marketplace_resource_reservations_company_id ON marketplace.resource_reservations(company_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_marketplace_resource_reservations_anchor_id ON marketplace.resource_reservations(anchor_id)")


def downgrade():
    op.execute("DROP TABLE marketplace.resource_reservations")
    op.execute("ALTER TABLE marketplace.offers DROP COLUMN product_id, DROP COLUMN resource_kind")
