"""Keep explicit need classification separate from its capacity category."""
from alembic import op

revision = "0020"
down_revision = "0019"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("ALTER TABLE marketplace.needs ADD COLUMN IF NOT EXISTS subcategory VARCHAR(120)")


def downgrade():
    classified = op.get_bind().exec_driver_sql(
        "SELECT 1 FROM marketplace.needs WHERE subcategory IS NOT NULL LIMIT 1"
    ).first()
    if classified:
        raise RuntimeError("Migrate classified needs explicitly before dropping their classification")
    op.execute("ALTER TABLE marketplace.needs DROP COLUMN IF EXISTS subcategory")
