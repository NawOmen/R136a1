"""Coalition composition changes after confirmation (stage S08)."""
from alembic import op

revision = "0026"
down_revision = "0025"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("ALTER TABLE marketplace.group_offers ADD COLUMN IF NOT EXISTS lot_multiple INTEGER NOT NULL DEFAULT 1")
    op.execute(
        "CREATE TABLE IF NOT EXISTS marketplace.coalition_change_requests ("
        "id UUID PRIMARY KEY, "
        'coalition_id UUID NOT NULL REFERENCES marketplace.coalitions(id) ON DELETE CASCADE, '
        "requested_by_company_id UUID NOT NULL, requested_by_user_id UUID, "
        "reason VARCHAR(1000) NOT NULL, proposed_units JSONB NOT NULL DEFAULT '{}', "
        "resource_policy VARCHAR(64) NOT NULL DEFAULT 'release_and_rereserve', "
        "status VARCHAR(32) NOT NULL DEFAULT 'pending', idempotency_key UUID NOT NULL, "
        "version_from INTEGER NOT NULL, version_to INTEGER, "
        "decisions JSONB NOT NULL DEFAULT '[]', "
        "created_at TIMESTAMPTZ NOT NULL DEFAULT now(), updated_at TIMESTAMPTZ NOT NULL DEFAULT now())"
    )
    op.execute(
        "DO $$ BEGIN "
        "IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'uq_coalition_change_request_key') THEN "
        "ALTER TABLE marketplace.coalition_change_requests ADD CONSTRAINT uq_coalition_change_request_key "
        "UNIQUE (coalition_id, idempotency_key); "
        "END IF; END $$"
    )


def downgrade():
    op.execute("ALTER TABLE marketplace.coalition_change_requests DROP CONSTRAINT IF EXISTS uq_coalition_change_request_key")
    op.execute("DROP TABLE IF EXISTS marketplace.coalition_change_requests")
    op.execute("ALTER TABLE marketplace.group_offers DROP COLUMN IF EXISTS lot_multiple")
