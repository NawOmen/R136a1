"""Category editor is appointed; registration can never grant this role."""
from alembic import op
revision='0005'
down_revision='0004'
branch_labels=None
depends_on=None


def upgrade():
    op.execute('ALTER TABLE auth.users ADD COLUMN IF NOT EXISTS is_category_editor BOOLEAN NOT NULL DEFAULT false')


def downgrade():
    op.execute('ALTER TABLE auth.users DROP COLUMN IF EXISTS is_category_editor')
