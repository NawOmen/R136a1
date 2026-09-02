"""stage 8 product cards

Revision ID: 0006
Revises: 0005
"""
from typing import Sequence, Union

from alembic import op

revision: str = "0006"
down_revision: Union[str, None] = "0005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TABLE marketplace.products ADD COLUMN IF NOT EXISTS subcategory VARCHAR(120)")
    op.execute("ALTER TABLE marketplace.products ADD COLUMN IF NOT EXISTS price_tiers JSONB NOT NULL DEFAULT '[]'::jsonb")
    op.execute("""
        CREATE TABLE IF NOT EXISTS marketplace.product_images (
            id UUID PRIMARY KEY, product_id UUID NOT NULL REFERENCES marketplace.products(id) ON DELETE CASCADE,
            file_name VARCHAR(255) NOT NULL, file_key VARCHAR(500) NOT NULL,
            content_type VARCHAR(80) NOT NULL, position INTEGER NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT uq_product_image_position UNIQUE (product_id, position),
            CONSTRAINT ck_product_image_position CHECK (position BETWEEN 0 AND 4)
        )
    """)
    op.execute("""
        CREATE TABLE IF NOT EXISTS marketplace.deal_messages (
            id UUID PRIMARY KEY, deal_id UUID NOT NULL REFERENCES marketplace.deals(id) ON DELETE CASCADE,
            author_user_id UUID NOT NULL, author_company_id UUID NOT NULL,
            message VARCHAR(2000) NOT NULL, created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """)
    op.execute(
        "ALTER TABLE marketplace.products "
        "DROP CONSTRAINT IF EXISTS ck_product_characteristics_limit"
    )
    op.execute(
        "ALTER TABLE marketplace.products "
        "ADD CONSTRAINT ck_product_characteristics_limit "
        "CHECK (jsonb_object_length(characteristics) <= 25)"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS marketplace.deal_messages")
    op.execute("DROP TABLE IF EXISTS marketplace.product_images")
    op.execute("ALTER TABLE marketplace.products DROP CONSTRAINT IF EXISTS ck_product_characteristics_limit")
    op.execute("ALTER TABLE marketplace.products DROP COLUMN IF EXISTS price_tiers")
    op.execute("ALTER TABLE marketplace.products DROP COLUMN IF EXISTS subcategory")
