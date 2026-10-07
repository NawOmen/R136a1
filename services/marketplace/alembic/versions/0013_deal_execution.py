"""Execution events and seller-only cost snapshots; legacy prices remain unknown."""
from alembic import op

revision = "0013"
down_revision = "0012"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("ALTER TABLE marketplace.deals ADD COLUMN IF NOT EXISTS unit_price_rub NUMERIC(18,2)")
    op.execute("ALTER TABLE marketplace.deals ADD COLUMN IF NOT EXISTS delivery_price_rub NUMERIC(18,2)")
    op.execute("""CREATE TABLE IF NOT EXISTS marketplace.deal_execution_events (
        id UUID PRIMARY KEY, deal_id UUID NOT NULL REFERENCES marketplace.deals(id) ON DELETE CASCADE,
        actor_company_id UUID NOT NULL, actor_user_id UUID NOT NULL, idempotency_key UUID NOT NULL,
        kind VARCHAR(24) NOT NULL, units INTEGER NOT NULL CHECK (units > 0), note VARCHAR(1000) NOT NULL,
        status VARCHAR(16) NOT NULL, decided_by_user_id UUID, decided_at TIMESTAMPTZ,
        created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        CONSTRAINT uq_execution_request UNIQUE (deal_id, actor_company_id, idempotency_key))""")
    op.execute("CREATE INDEX IF NOT EXISTS ix_marketplace_deal_execution_events_deal_id ON marketplace.deal_execution_events(deal_id)")
    op.execute("""CREATE TABLE IF NOT EXISTS marketplace.deal_cost_snapshots (
        deal_id UUID PRIMARY KEY REFERENCES marketplace.deals(id) ON DELETE CASCADE,
        unit_cost_rub NUMERIC(18,2), attributable_expenses_rub NUMERIC(18,2), revision INTEGER NOT NULL,
        note VARCHAR(1000) NOT NULL, updated_by_user_id UUID NOT NULL,
        updated_at TIMESTAMPTZ NOT NULL DEFAULT now())""")


def downgrade():
    op.execute("DROP TABLE marketplace.deal_cost_snapshots")
    op.execute("DROP TABLE marketplace.deal_execution_events")
    op.execute("ALTER TABLE marketplace.deals DROP COLUMN delivery_price_rub, DROP COLUMN unit_price_rub")
