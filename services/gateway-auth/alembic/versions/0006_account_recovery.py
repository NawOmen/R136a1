"""Revocable account sessions and hashed, expiring recovery challenges."""
from alembic import op
revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("ALTER TABLE auth.users ADD COLUMN token_version INTEGER NOT NULL DEFAULT 0")
    op.execute("""CREATE TABLE auth.account_recovery (
        token_hash VARCHAR(64) PRIMARY KEY, nonce UUID NOT NULL,
        delivery_status VARCHAR(16) NOT NULL DEFAULT 'pending', delivery_attempts INTEGER NOT NULL DEFAULT 0,
        next_attempt_at TIMESTAMPTZ NOT NULL DEFAULT now(), user_id UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
        token_version INTEGER NOT NULL, expires_at TIMESTAMPTZ NOT NULL, used_at TIMESTAMPTZ)
    """)
    op.execute("""CREATE TABLE auth.account_agreements (
        user_id UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE, document VARCHAR(24) NOT NULL,
        version VARCHAR(32) NOT NULL, accepted_at TIMESTAMPTZ NOT NULL DEFAULT now(), PRIMARY KEY(user_id, document, version))""")
    op.execute("CREATE INDEX ix_auth_account_recovery_user_id ON auth.account_recovery(user_id)")


def downgrade():
    op.execute("DROP TABLE auth.account_agreements")
    op.execute("DROP TABLE auth.account_recovery")
    op.execute("ALTER TABLE auth.users DROP COLUMN token_version")
