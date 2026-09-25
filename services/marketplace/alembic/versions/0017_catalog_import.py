"""Idempotent confirmed catalogue imports."""
from alembic import op
revision = "0017"
down_revision = "0016"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""CREATE TABLE IF NOT EXISTS marketplace.catalog_imports (
        id UUID PRIMARY KEY, company_id UUID NOT NULL, request_key UUID NOT NULL,
        content_hash VARCHAR(64) NOT NULL, product_ids JSONB NOT NULL,
        created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        CONSTRAINT uq_catalog_import_request UNIQUE(company_id, request_key))""")


def downgrade():
    op.drop_table("catalog_imports", schema="marketplace")
