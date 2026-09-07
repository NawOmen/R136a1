"""Align stage 9 indexes with ORM models, including already upgraded databases.

Revision ID: 0008
Revises: 0007
"""
from alembic import op

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_marketplace_product_price_observations_product_id "
        "ON marketplace.product_price_observations(product_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_marketplace_market_watches_user_id "
        "ON marketplace.market_watches(user_id)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS marketplace.ix_marketplace_market_watches_user_id")
    op.execute("DROP INDEX IF EXISTS marketplace.ix_marketplace_product_price_observations_product_id")
