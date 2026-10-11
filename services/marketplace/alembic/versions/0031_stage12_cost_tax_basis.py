"""S12: налоговая база снимка затрат продавца."""
from alembic import op
revision = "0031"
down_revision = "0030"
branch_labels = None
depends_on = None

def upgrade():
    op.execute("ALTER TABLE marketplace.deal_cost_snapshots ADD COLUMN IF NOT EXISTS tax_basis VARCHAR(16) NOT NULL DEFAULT 'unknown'")

def downgrade():
    op.execute("ALTER TABLE marketplace.deal_cost_snapshots DROP COLUMN IF EXISTS tax_basis")
