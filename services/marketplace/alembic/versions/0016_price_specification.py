"""Comparable price history; legacy observations have unknown specification."""
from alembic import op
revision = "0016"
down_revision = "0015"
branch_labels = None
depends_on = None

def upgrade():
    op.execute("ALTER TABLE marketplace.product_price_observations ADD COLUMN IF NOT EXISTS specification_hash VARCHAR(64)")

def downgrade():
    op.execute("ALTER TABLE marketplace.product_price_observations DROP COLUMN specification_hash")
