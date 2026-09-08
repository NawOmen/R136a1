"""Add manufacturer / stock supplier details, compatible with API v1."""
from alembic import op

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 0001 imports current ORM metadata on clean installs, so this column may
    # already exist. Existing 0008 databases still need the additive migration.
    op.execute("ALTER TABLE marketplace.capability_passports "
               "ADD COLUMN IF NOT EXISTS details JSONB DEFAULT '{}'::jsonb NOT NULL")


def downgrade() -> None:
    op.drop_column("capability_passports", "details", schema="marketplace")
