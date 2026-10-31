"""Persist destinations without guessing entities for legacy notifications."""
from alembic import op

revision = "0036"
down_revision = "0035"
branch_labels = None
depends_on = None


def upgrade():
    # 0001 creates current metadata on fresh installations.
    op.execute("ALTER TABLE marketplace.notifications ADD COLUMN IF NOT EXISTS href VARCHAR(500)")


def downgrade():
    op.execute("ALTER TABLE marketplace.notifications DROP COLUMN IF EXISTS href")
