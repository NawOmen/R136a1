"""Persist the catalog import source system (stage S14)."""
from alembic import op

revision = "0033"
down_revision = "0032"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("ALTER TABLE marketplace.catalog_imports ADD COLUMN IF NOT EXISTS source_system VARCHAR(64)")


def downgrade():
    op.execute("ALTER TABLE marketplace.catalog_imports DROP COLUMN IF EXISTS source_system")
