"""Shared company quota for address suggestions."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql as pg

revision = "0035"
down_revision = "0034"
branch_labels = None
depends_on = None


def upgrade():
    # Initial migration creates current metadata on a fresh installation.
    op.create_table("address_suggestion_limits",
        sa.Column("company_id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column("bucket", sa.BigInteger(), primary_key=True),
        sa.Column("attempts", sa.Integer(), nullable=False),
        schema="marketplace", if_not_exists=True)


def downgrade():
    op.drop_table("address_suggestion_limits", schema="marketplace")
