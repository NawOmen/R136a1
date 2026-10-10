"""Persist the hazardous-cargo flag on delivery arrangements (stage S10)."""
from alembic import op

revision = "0029"
down_revision = "0028"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("ALTER TABLE marketplace.delivery_arrangements ADD COLUMN IF NOT EXISTS hazard_class VARCHAR(32)")


def downgrade():
    op.execute("ALTER TABLE marketplace.delivery_arrangements DROP COLUMN IF EXISTS hazard_class")
