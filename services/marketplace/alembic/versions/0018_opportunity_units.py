"""Keep market demand with different order units in separate opportunities."""
from alembic import op
import sqlalchemy as sa

revision = "0018"
down_revision = "0017"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("market_opportunities", sa.Column("unit", sa.String(32), nullable=False, server_default="шт"), schema="marketplace")
    op.drop_constraint("uq_opportunity_company_category", "market_opportunities", schema="marketplace", type_="unique")
    op.create_unique_constraint("uq_opportunity_company_category_unit", "market_opportunities", ["company_id", "category", "unit"], schema="marketplace")


def downgrade():
    op.drop_constraint("uq_opportunity_company_category_unit", "market_opportunities", schema="marketplace", type_="unique")
    op.drop_column("market_opportunities", "unit", schema="marketplace")
    op.create_unique_constraint("uq_opportunity_company_category", "market_opportunities", ["company_id", "category"], schema="marketplace")
