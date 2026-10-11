"""S11: idempotent support submissions."""
from alembic import op
revision = "0030"
down_revision = "0029"
branch_labels = None
depends_on = None

def upgrade():
    op.execute("ALTER TABLE marketplace.support_tickets ADD COLUMN IF NOT EXISTS request_key UUID, ADD COLUMN IF NOT EXISTS request_hash VARCHAR(64)")
    op.execute("""DO $$ BEGIN
        IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conrelid = 'marketplace.support_tickets'::regclass AND conname = 'uq_support_user_request') THEN
            ALTER TABLE marketplace.support_tickets ADD CONSTRAINT uq_support_user_request UNIQUE(user_id, request_key);
        END IF;
    END $$""")

def downgrade():
    op.execute("ALTER TABLE marketplace.support_tickets DROP CONSTRAINT IF EXISTS uq_support_user_request, DROP COLUMN IF EXISTS request_key, DROP COLUMN IF EXISTS request_hash")
