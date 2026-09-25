"""Scope production capacity by category and order unit."""
from alembic import op

revision = "0019"
down_revision = "0018"
branch_labels = None
depends_on = None


def upgrade():
    # 0001 creates current metadata for a fresh install; older databases need both columns.
    op.execute("ALTER TABLE marketplace.capacity_entries ADD COLUMN IF NOT EXISTS category VARCHAR(120) DEFAULT '' NOT NULL")
    op.execute("ALTER TABLE marketplace.capacity_entries ADD COLUMN IF NOT EXISTS unit VARCHAR(32) DEFAULT 'шт' NOT NULL")
    op.execute("ALTER TABLE marketplace.capacity_entries DROP CONSTRAINT IF EXISTS uq_capacity_company_date")
    op.execute("ALTER TABLE marketplace.capacity_entries DROP CONSTRAINT IF EXISTS uq_capacity_company_date_scope")
    op.create_unique_constraint("uq_capacity_company_date_scope", "capacity_entries", ["company_id", "date", "category", "unit"], schema="marketplace")


def downgrade():
    scoped = op.get_bind().exec_driver_sql("SELECT 1 FROM marketplace.capacity_entries WHERE category <> '' OR unit <> 'шт' LIMIT 1").first()
    if scoped:
        raise RuntimeError("Scoped capacity rows must be migrated explicitly before downgrade")
    op.execute("ALTER TABLE marketplace.capacity_entries DROP CONSTRAINT IF EXISTS uq_capacity_company_date_scope")
    op.execute("ALTER TABLE marketplace.capacity_entries DROP COLUMN IF EXISTS category")
    op.execute("ALTER TABLE marketplace.capacity_entries DROP COLUMN IF EXISTS unit")
    op.create_unique_constraint("uq_capacity_company_date", "capacity_entries", ["company_id", "date"], schema="marketplace")
