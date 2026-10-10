"""Confirmed reserve switchover time (stage S09)."""
from alembic import op

revision = "0027"
down_revision = "0026"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("ALTER TABLE marketplace.reserve_commitments ADD COLUMN IF NOT EXISTS switchover_days INTEGER")


def downgrade():
    op.drop_column("reserve_commitments", "switchover_days", schema="marketplace")
