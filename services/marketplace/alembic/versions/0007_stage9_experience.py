"""stage 9 experience, delivery and verified reviews

Revision ID: 0007
Revises: 0006
"""
from typing import Sequence, Union

from alembic import op

revision: str = "0007"
down_revision: Union[str, None] = "0006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TABLE marketplace.production_profiles ADD COLUMN IF NOT EXISTS photo_file_name VARCHAR(255)")
    op.execute("ALTER TABLE marketplace.production_profiles ADD COLUMN IF NOT EXISTS photo_file_key VARCHAR(500)")
    op.execute("ALTER TABLE marketplace.production_profiles ADD COLUMN IF NOT EXISTS photo_content_type VARCHAR(80)")
    op.execute("""
        CREATE TABLE IF NOT EXISTS marketplace.deal_checkpoints (
            id UUID PRIMARY KEY, deal_id UUID NOT NULL REFERENCES marketplace.deals(id) ON DELETE CASCADE,
            kind VARCHAR(32) NOT NULL, status VARCHAR(24) NOT NULL DEFAULT 'pending',
            note VARCHAR(500), confirmed_by_user_id UUID, completed_at TIMESTAMPTZ,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT uq_deal_checkpoint_kind UNIQUE (deal_id, kind),
            CONSTRAINT ck_deal_checkpoint_kind CHECK (kind IN ('production', 'shipment', 'delivery')),
            CONSTRAINT ck_deal_checkpoint_status CHECK (status IN ('pending', 'completed'))
        )
    """)
    op.execute("""
        CREATE TABLE IF NOT EXISTS marketplace.delivery_arrangements (
            id UUID PRIMARY KEY, deal_id UUID NOT NULL REFERENCES marketplace.deals(id) ON DELETE CASCADE UNIQUE,
            weight_kg DOUBLE PRECISION NOT NULL, volume_m3 DOUBLE PRECISION NOT NULL,
            cargo_class VARCHAR(32) NOT NULL, classification_note VARCHAR(500) NOT NULL,
            method VARCHAR(32) NOT NULL, carrier_name VARCHAR(255), tracking_number VARCHAR(255),
            buyer_responsible BOOLEAN NOT NULL DEFAULT true, confirmed_by_user_id UUID NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(), updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT ck_delivery_positive CHECK (weight_kg > 0 AND volume_m3 > 0),
            CONSTRAINT ck_delivery_method CHECK (method IN ('buyer_carrier', 'self_pickup', 'seller_delivery'))
        )
    """)
    op.execute("""
        CREATE TABLE IF NOT EXISTS marketplace.deal_reviews (
            id UUID PRIMARY KEY, deal_id UUID NOT NULL REFERENCES marketplace.deals(id) ON DELETE CASCADE,
            reviewer_company_id UUID NOT NULL, reviewed_company_id UUID NOT NULL,
            rating INTEGER NOT NULL, comment VARCHAR(2000) NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT uq_deal_review_reviewer UNIQUE (deal_id, reviewer_company_id),
            CONSTRAINT ck_deal_review_rating CHECK (rating BETWEEN 1 AND 5)
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_deal_reviews_reviewed_company_id ON marketplace.deal_reviews(reviewed_company_id)")
    op.execute("""
        CREATE TABLE IF NOT EXISTS marketplace.product_price_observations (
            id UUID PRIMARY KEY, product_id UUID NOT NULL REFERENCES marketplace.products(id) ON DELETE CASCADE,
            category VARCHAR(120) NOT NULL, unit_price_rub DOUBLE PRECISION NOT NULL,
            observed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT ck_product_price_observation_positive CHECK (unit_price_rub > 0)
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_product_price_observations_category ON marketplace.product_price_observations(category)")
    op.execute("""
        INSERT INTO marketplace.product_price_observations (id, product_id, category, unit_price_rub, observed_at)
        SELECT gen_random_uuid(), p.id, p.category, p.price_rub, COALESCE(p.updated_at, p.created_at)
        FROM marketplace.products p
        WHERE p.is_published = true
        AND NOT EXISTS (
            SELECT 1 FROM marketplace.product_price_observations o WHERE o.product_id = p.id
        )
    """)
    op.execute("""
        CREATE TABLE IF NOT EXISTS marketplace.market_watches (
            id UUID PRIMARY KEY, user_id UUID NOT NULL, category VARCHAR(120) NOT NULL,
            demand_changes BOOLEAN NOT NULL DEFAULT true, supply_changes BOOLEAN NOT NULL DEFAULT true,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT uq_market_watch_user_category UNIQUE (user_id, category)
        )
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS marketplace.market_watches")
    op.execute("DROP TABLE IF EXISTS marketplace.product_price_observations")
    op.execute("DROP TABLE IF EXISTS marketplace.deal_reviews")
    op.execute("DROP TABLE IF EXISTS marketplace.delivery_arrangements")
    op.execute("DROP TABLE IF EXISTS marketplace.deal_checkpoints")
    op.execute("ALTER TABLE marketplace.production_profiles DROP COLUMN IF EXISTS photo_content_type")
    op.execute("ALTER TABLE marketplace.production_profiles DROP COLUMN IF EXISTS photo_file_key")
    op.execute("ALTER TABLE marketplace.production_profiles DROP COLUMN IF EXISTS photo_file_name")
