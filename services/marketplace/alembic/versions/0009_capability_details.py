"""Add manufacturer / stock supplier details, compatible with API v1."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("capability_passports", sa.Column(
        "details", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")
    ), schema="marketplace")


def downgrade() -> None:
    op.drop_column("capability_passports", "details", schema="marketplace")
