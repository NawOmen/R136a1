"""S09: reserve switching and executable recovery orders."""
from alembic import op

revision = "0028"
down_revision = "0027"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("ALTER TABLE marketplace.reserve_commitments ADD COLUMN IF NOT EXISTS switchover_days INTEGER")
    op.execute("ALTER TABLE marketplace.resilience_plans ADD COLUMN IF NOT EXISTS failure_allocations JSONB NOT NULL DEFAULT '[]'")
    op.execute("ALTER TABLE marketplace.deals ADD COLUMN IF NOT EXISTS resilience_plan_id UUID REFERENCES marketplace.resilience_plans(id) ON DELETE RESTRICT")
    op.execute("ALTER TABLE marketplace.deals ADD COLUMN IF NOT EXISTS resilience_scenario_id UUID REFERENCES marketplace.resilience_scenarios(id) ON DELETE RESTRICT")
    op.execute("CREATE UNIQUE INDEX IF NOT EXISTS uq_resilience_baseline_deal ON marketplace.deals(resilience_plan_id, seller_company_id) WHERE resilience_plan_id IS NOT NULL AND resilience_scenario_id IS NULL")
    op.execute("CREATE UNIQUE INDEX IF NOT EXISTS uq_resilience_recovery_deal ON marketplace.deals(resilience_scenario_id, seller_company_id) WHERE resilience_scenario_id IS NOT NULL")


def downgrade():
    op.drop_index("uq_resilience_recovery_deal", table_name="deals", schema="marketplace")
    op.drop_index("uq_resilience_baseline_deal", table_name="deals", schema="marketplace")
    op.drop_column("deals", "resilience_scenario_id", schema="marketplace")
    op.drop_column("deals", "resilience_plan_id", schema="marketplace")
    op.drop_column("resilience_plans", "failure_allocations", schema="marketplace")
    op.drop_column("reserve_commitments", "switchover_days", schema="marketplace")
