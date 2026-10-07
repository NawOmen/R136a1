"""Keep market demand with different order units in separate opportunities."""
from alembic import op

revision = "0018"
down_revision = "0017"
branch_labels = None
depends_on = None


def upgrade():
    # 0001 creates tables from current metadata on a fresh database. An upgrade
    # from an older database still needs this column and constraint transition.
    op.execute("ALTER TABLE marketplace.market_opportunities ADD COLUMN IF NOT EXISTS unit VARCHAR(32) DEFAULT 'шт' NOT NULL")
    op.execute("ALTER TABLE marketplace.market_opportunities DROP CONSTRAINT IF EXISTS uq_opportunity_company_category")
    op.execute("ALTER TABLE marketplace.market_opportunities DROP CONSTRAINT IF EXISTS uq_opportunity_company_category_unit")
    op.create_unique_constraint("uq_opportunity_company_category_unit", "market_opportunities", ["company_id", "category", "unit"], schema="marketplace")


def downgrade():
    op.drop_constraint("uq_opportunity_company_category_unit", "market_opportunities", schema="marketplace", type_="unique")
    op.drop_column("market_opportunities", "unit", schema="marketplace")
    op.create_unique_constraint("uq_opportunity_company_category", "market_opportunities", ["company_id", "category"], schema="marketplace")
