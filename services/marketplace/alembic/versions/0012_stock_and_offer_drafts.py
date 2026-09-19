"""Остатки товара и черновики коммерческих предложений, совместимо с API v1."""
from alembic import op

revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 0001 импортирует актуальные модели при чистой установке, поэтому объекты
    # могут уже существовать. Базы, созданные на 0011, получают их здесь.
    op.execute("ALTER TABLE marketplace.products ADD COLUMN IF NOT EXISTS stock_units INTEGER")
    op.execute("ALTER TABLE marketplace.products ADD COLUMN IF NOT EXISTS stock_updated_at TIMESTAMPTZ")
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS marketplace.offer_drafts (
            id UUID PRIMARY KEY,
            need_id UUID NOT NULL REFERENCES marketplace.needs(id) ON DELETE CASCADE,
            company_id UUID NOT NULL,
            created_by_user_id UUID,
            status VARCHAR(16) NOT NULL DEFAULT 'draft',
            payload JSONB NOT NULL DEFAULT '{}'::jsonb,
            fields JSONB NOT NULL DEFAULT '[]'::jsonb,
            missing JSONB NOT NULL DEFAULT '[]'::jsonb,
            warnings JSONB NOT NULL DEFAULT '[]'::jsonb,
            explanation TEXT NOT NULL DEFAULT '',
            used_offer_id UUID,
            changed_fields JSONB NOT NULL DEFAULT '[]'::jsonb,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            used_at TIMESTAMPTZ
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_offer_drafts_need_company "
        "ON marketplace.offer_drafts (need_id, company_id)"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS marketplace.offer_drafts")
    op.execute("ALTER TABLE marketplace.products DROP COLUMN IF EXISTS stock_updated_at")
    op.execute("ALTER TABLE marketplace.products DROP COLUMN IF EXISTS stock_units")
