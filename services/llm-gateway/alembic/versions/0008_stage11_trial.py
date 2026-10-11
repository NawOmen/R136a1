"""S11: retry keys for buyer trial runs."""
from alembic import op
revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None

def upgrade():
    op.execute("ALTER TABLE agents.agent_runs ADD COLUMN IF NOT EXISTS request_key UUID, ADD COLUMN IF NOT EXISTS request_hash VARCHAR(64)")
    op.execute("""DO $$ BEGIN
        IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conrelid = 'agents.agent_runs'::regclass AND conname = 'uq_agent_run_user_request') THEN
            ALTER TABLE agents.agent_runs ADD CONSTRAINT uq_agent_run_user_request UNIQUE(user_id, agent_type, request_key);
        END IF;
    END $$""")

def downgrade():
    op.execute("ALTER TABLE agents.agent_runs DROP CONSTRAINT IF EXISTS uq_agent_run_user_request, DROP COLUMN IF EXISTS request_key, DROP COLUMN IF EXISTS request_hash")
