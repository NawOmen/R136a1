"""Attribute agent runs to the company active when the run was created."""
from alembic import op
revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("ALTER TABLE agents.agent_runs ADD COLUMN IF NOT EXISTS company_id UUID")
    op.execute("CREATE INDEX IF NOT EXISTS ix_agents_agent_runs_company_id ON agents.agent_runs(company_id)")


def downgrade():
    op.execute("DROP INDEX IF EXISTS agents.ix_agents_agent_runs_company_id")
    op.execute("ALTER TABLE agents.agent_runs DROP COLUMN IF EXISTS company_id")
