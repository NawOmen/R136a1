"""Keep the technical profile used by a saved specification; legacy stays unknown."""
from alembic import op

revision = '0021'
down_revision = '0020'
branch_labels = None
depends_on = None


def upgrade():
    for table in ('products', 'needs'):
        op.execute(f'ALTER TABLE marketplace.{table} ADD COLUMN IF NOT EXISTS category_profile JSONB')


def downgrade():
    for table in ('products', 'needs'):
        used = op.get_bind().exec_driver_sql(
            f'SELECT 1 FROM marketplace.{table} WHERE category_profile IS NOT NULL LIMIT 1'
        ).first()
        if used:
            raise RuntimeError('Preserve category profile snapshots before dropping their columns')
    for table in ('products', 'needs'):
        op.execute(f'ALTER TABLE marketplace.{table} DROP COLUMN IF EXISTS category_profile')
