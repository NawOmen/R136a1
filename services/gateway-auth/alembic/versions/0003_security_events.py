"""Shared rate limits and security audit, including existing installations."""
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
        CREATE TABLE IF NOT EXISTS auth.login_limits (
            key varchar(64) NOT NULL, bucket bigint NOT NULL,
            attempts integer NOT NULL, PRIMARY KEY (key, bucket))
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_auth_login_limits_bucket ON auth.login_limits (bucket)")
    op.execute("""
        CREATE TABLE IF NOT EXISTS auth.security_events (
            id uuid PRIMARY KEY, event varchar(64) NOT NULL,
            actor_id uuid, target_id uuid, before_value varchar(32), after_value varchar(32), reason varchar(500),
            correlation_id varchar(36) NOT NULL, created_at timestamptz NOT NULL DEFAULT now())
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_auth_security_events_created_at ON auth.security_events (created_at)")


def downgrade():
    op.drop_table("security_events", schema="auth")
    op.drop_table("login_limits", schema="auth")
