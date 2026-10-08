"""Persist editor-published category rules without rewriting historical snapshots."""
from alembic import op
revision='0022'
down_revision='0021'
branch_labels=None
depends_on=None


def upgrade():
    op.execute("ALTER TABLE marketplace.products ADD COLUMN IF NOT EXISTS quantity_conversion JSONB")
    op.execute("ALTER TABLE marketplace.capacity_entries ADD COLUMN IF NOT EXISTS category_conversions JSONB NOT NULL DEFAULT '[]'")
    op.execute("ALTER TABLE marketplace.resource_reservations ADD COLUMN IF NOT EXISTS resource_units INTEGER")
    op.execute("ALTER TABLE marketplace.resource_reservations ADD COLUMN IF NOT EXISTS resource_conversion JSONB")
    op.execute('''CREATE TABLE IF NOT EXISTS marketplace.category_registry_revisions (
        id UUID PRIMARY KEY, sequence INTEGER NOT NULL UNIQUE, parent_hash VARCHAR(64) NOT NULL UNIQUE,
        registry_hash VARCHAR(64) NOT NULL UNIQUE, registry JSONB NOT NULL,
        published_by_user_id UUID NOT NULL, created_at TIMESTAMPTZ NOT NULL DEFAULT now())''')


def downgrade():
    if op.get_bind().exec_driver_sql('SELECT 1 FROM marketplace.category_registry_revisions LIMIT 1').first():
        raise RuntimeError('Preserve published category rules before dropping their history')
    if op.get_bind().exec_driver_sql('SELECT 1 FROM marketplace.resource_reservations WHERE resource_conversion IS NOT NULL OR resource_units IS NOT NULL LIMIT 1').first():
        raise RuntimeError('Preserve resource conversion evidence before downgrade')
    if op.get_bind().exec_driver_sql("SELECT 1 FROM marketplace.capacity_entries WHERE category_conversions <> '[]'::jsonb LIMIT 1").first():
        raise RuntimeError('Preserve capacity coefficients before downgrade')
    if op.get_bind().exec_driver_sql('SELECT 1 FROM marketplace.products WHERE quantity_conversion IS NOT NULL LIMIT 1').first():
        raise RuntimeError('Preserve product packaging conversion evidence before downgrade')
    op.execute('ALTER TABLE marketplace.products DROP COLUMN IF EXISTS quantity_conversion')
    op.execute('ALTER TABLE marketplace.resource_reservations DROP COLUMN IF EXISTS resource_conversion')
    op.execute('ALTER TABLE marketplace.resource_reservations DROP COLUMN IF EXISTS resource_units')
    op.execute('ALTER TABLE marketplace.capacity_entries DROP COLUMN IF EXISTS category_conversions')
    op.execute('DROP TABLE IF EXISTS marketplace.category_registry_revisions')
