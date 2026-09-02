"""stage 7 trust, approvals and support

Revision ID: 0005
Revises: 0004
Create Date: 2026-09-02
"""
from typing import Sequence, Union

from alembic import op

revision: str = "0005"
down_revision: Union[str, None] = "0004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE marketplace.documents ADD COLUMN IF NOT EXISTS verification_status "
        "VARCHAR(24) NOT NULL DEFAULT 'unverified'"
    )
    op.execute("""
        CREATE TABLE IF NOT EXISTS marketplace.trust_audit_events (
            id UUID PRIMARY KEY, sequence INTEGER NOT NULL UNIQUE,
            previous_hash VARCHAR(64) NOT NULL, event_hash VARCHAR(64) NOT NULL UNIQUE,
            event_type VARCHAR(80) NOT NULL, entity_type VARCHAR(80) NOT NULL,
            entity_id UUID, actor_user_id UUID, actor_company_id UUID,
            source_refs JSONB NOT NULL DEFAULT '[]'::jsonb,
            explanation TEXT NOT NULL, payload JSONB NOT NULL DEFAULT '{}'::jsonb,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_trust_audit_event_type ON marketplace.trust_audit_events (event_type)")
    op.execute("""
        CREATE TABLE IF NOT EXISTS marketplace.human_approval_records (
            id UUID PRIMARY KEY, action VARCHAR(100) NOT NULL,
            entity_type VARCHAR(80) NOT NULL, entity_id UUID,
            actor_user_id UUID NOT NULL, actor_company_id UUID,
            permission VARCHAR(80) NOT NULL, decision VARCHAR(24) NOT NULL,
            reason VARCHAR(500), payload_hash VARCHAR(64) NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT ck_human_approval_decision CHECK (decision IN ('approved', 'rejected'))
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_human_approval_action ON marketplace.human_approval_records (action)")
    op.execute("""
        CREATE TABLE IF NOT EXISTS marketplace.support_tickets (
            id UUID PRIMARY KEY, user_id UUID NOT NULL, company_id UUID,
            subject VARCHAR(200) NOT NULL, message TEXT NOT NULL,
            status VARCHAR(32) NOT NULL DEFAULT 'new', admin_response TEXT,
            assigned_admin_user_id UUID, created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT ck_support_status CHECK (status IN ('new', 'in_progress', 'resolved', 'closed'))
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_support_tickets_user_id ON marketplace.support_tickets (user_id)")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS marketplace.support_tickets")
    op.execute("DROP TABLE IF EXISTS marketplace.human_approval_records")
    op.execute("DROP TABLE IF EXISTS marketplace.trust_audit_events")
    op.execute("ALTER TABLE marketplace.documents DROP COLUMN IF EXISTS verification_status")
