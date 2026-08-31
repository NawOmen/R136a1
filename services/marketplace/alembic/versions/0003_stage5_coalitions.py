"""stage 5 coalitions and market optimizer entities

Revision ID: 0003
Revises: 0002
Create Date: 2026-09-01
"""
from typing import Sequence, Union

from alembic import op

revision: str = "0003"
down_revision: Union[str, None] = "0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TABLE marketplace.needs ADD COLUMN IF NOT EXISTS valid_until DATE")
    op.execute("ALTER TABLE marketplace.needs ADD COLUMN IF NOT EXISTS no_match_reason VARCHAR(500)")
    op.execute("ALTER TABLE marketplace.needs ADD COLUMN IF NOT EXISTS confirmed_at TIMESTAMPTZ")
    op.execute("ALTER TABLE marketplace.offers ADD COLUMN IF NOT EXISTS moq_units INTEGER NOT NULL DEFAULT 1")
    op.execute("ALTER TABLE marketplace.offers ADD COLUMN IF NOT EXISTS price_tiers JSONB NOT NULL DEFAULT '[]'::jsonb")
    op.execute("ALTER TABLE marketplace.offers ADD COLUMN IF NOT EXISTS valid_until DATE")
    op.execute(
        "ALTER TABLE marketplace.offers "
        "ADD COLUMN IF NOT EXISTS delivery_cost_rub DOUBLE PRECISION NOT NULL DEFAULT 0"
    )

    op.execute("""
        CREATE TABLE IF NOT EXISTS marketplace.match_events (
            id UUID PRIMARY KEY, event_type VARCHAR(64) NOT NULL, entity_id UUID,
            payload JSONB NOT NULL DEFAULT '{}'::jsonb, status VARCHAR(32) NOT NULL DEFAULT 'processed',
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_match_events_event_type ON marketplace.match_events (event_type)")
    op.execute("""
        CREATE TABLE IF NOT EXISTS marketplace.market_opportunities (
            id UUID PRIMARY KEY, company_id UUID NOT NULL, category VARCHAR(120) NOT NULL,
            score INTEGER NOT NULL, competition_level VARCHAR(32) NOT NULL,
            saturation_risk VARCHAR(32) NOT NULL, unmet_volume_units INTEGER NOT NULL,
            buyers_count INTEGER NOT NULL, need_ids JSONB NOT NULL DEFAULT '[]'::jsonb,
            reasons JSONB NOT NULL DEFAULT '[]'::jsonb, missing_data JSONB NOT NULL DEFAULT '[]'::jsonb,
            status VARCHAR(32) NOT NULL DEFAULT 'active', created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT uq_opportunity_company_category UNIQUE (company_id, category)
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_market_opportunities_company_id ON marketplace.market_opportunities (company_id)")
    op.execute("""
        CREATE TABLE IF NOT EXISTS marketplace.compatibility_profiles (
            id UUID PRIMARY KEY, category VARCHAR(120) NOT NULL,
            common_base JSONB NOT NULL DEFAULT '{}'::jsonb,
            hard_constraints JSONB NOT NULL DEFAULT '{}'::jsonb,
            flexible_parameters JSONB NOT NULL DEFAULT '{}'::jsonb,
            individual_parts JSONB NOT NULL DEFAULT '{}'::jsonb,
            input_hash VARCHAR(64) NOT NULL UNIQUE,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """)
    op.execute("""
        CREATE TABLE IF NOT EXISTS marketplace.coalitions (
            id UUID PRIMARY KEY,
            compatibility_profile_id UUID NOT NULL REFERENCES marketplace.compatibility_profiles(id) ON DELETE CASCADE,
            producer_company_id UUID, category VARCHAR(120) NOT NULL,
            combined_volume_units INTEGER NOT NULL, target_moq_units INTEGER,
            status VARCHAR(32) NOT NULL DEFAULT 'candidate', version INTEGER NOT NULL DEFAULT 1,
            explanation JSONB NOT NULL DEFAULT '[]'::jsonb,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(), updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """)
    op.execute("""
        CREATE TABLE IF NOT EXISTS marketplace.coalition_members (
            id UUID PRIMARY KEY, coalition_id UUID NOT NULL REFERENCES marketplace.coalitions(id) ON DELETE CASCADE,
            need_id UUID NOT NULL REFERENCES marketplace.needs(id) ON DELETE CASCADE,
            buyer_company_id UUID NOT NULL, units INTEGER NOT NULL,
            individual_operations JSONB NOT NULL DEFAULT '{}'::jsonb,
            common_cost_rub DOUBLE PRECISION, individual_cost_rub DOUBLE PRECISION,
            delivery_cost_rub DOUBLE PRECISION, total_cost_rub DOUBLE PRECISION,
            baseline_cost_rub DOUBLE PRECISION, benefit_rub DOUBLE PRECISION,
            approval_status VARCHAR(32) NOT NULL DEFAULT 'pending',
            CONSTRAINT uq_coalition_member_need UNIQUE (coalition_id, need_id)
        )
    """)
    op.execute("""
        CREATE TABLE IF NOT EXISTS marketplace.group_offers (
            id UUID PRIMARY KEY, coalition_id UUID NOT NULL REFERENCES marketplace.coalitions(id) ON DELETE CASCADE,
            company_id UUID NOT NULL,
            opportunity_id UUID REFERENCES marketplace.market_opportunities(id) ON DELETE SET NULL,
            min_total_units INTEGER, max_total_units INTEGER,
            price_tiers JSONB NOT NULL DEFAULT '[]'::jsonb,
            production_start DATE, production_end DATE, fill_deadline DATE,
            non_fill_rule VARCHAR(64), status VARCHAR(32) NOT NULL DEFAULT 'draft',
            seller_approval_status VARCHAR(32) NOT NULL DEFAULT 'pending', created_by_user_id UUID,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(), updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """)
    op.execute("""
        CREATE TABLE IF NOT EXISTS marketplace.participant_orders (
            id UUID PRIMARY KEY, coalition_id UUID NOT NULL REFERENCES marketplace.coalitions(id) ON DELETE CASCADE,
            group_offer_id UUID NOT NULL REFERENCES marketplace.group_offers(id) ON DELETE CASCADE,
            need_id UUID NOT NULL REFERENCES marketplace.needs(id) ON DELETE CASCADE,
            buyer_company_id UUID NOT NULL, seller_company_id UUID NOT NULL,
            units INTEGER NOT NULL, total_price_rub DOUBLE PRECISION NOT NULL,
            status VARCHAR(32) NOT NULL DEFAULT 'created', created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT uq_participant_order_need UNIQUE (coalition_id, need_id)
        )
    """)
    op.execute("""
        CREATE TABLE IF NOT EXISTS marketplace.optimization_variants (
            id UUID PRIMARY KEY, need_id UUID NOT NULL REFERENCES marketplace.needs(id) ON DELETE CASCADE,
            kind VARCHAR(32) NOT NULL, result JSONB NOT NULL, input_hash VARCHAR(64) NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT uq_variant_need_kind_hash UNIQUE (need_id, kind, input_hash)
        )
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS marketplace.optimization_variants")
    op.execute("DROP TABLE IF EXISTS marketplace.participant_orders")
    op.execute("DROP TABLE IF EXISTS marketplace.group_offers")
    op.execute("DROP TABLE IF EXISTS marketplace.coalition_members")
    op.execute("DROP TABLE IF EXISTS marketplace.coalitions")
    op.execute("DROP TABLE IF EXISTS marketplace.compatibility_profiles")
    op.execute("DROP TABLE IF EXISTS marketplace.market_opportunities")
    op.execute("DROP TABLE IF EXISTS marketplace.match_events")
    op.execute("ALTER TABLE marketplace.offers DROP COLUMN IF EXISTS valid_until")
    op.execute("ALTER TABLE marketplace.offers DROP COLUMN IF EXISTS delivery_cost_rub")
    op.execute("ALTER TABLE marketplace.offers DROP COLUMN IF EXISTS price_tiers")
    op.execute("ALTER TABLE marketplace.offers DROP COLUMN IF EXISTS moq_units")
    op.execute("ALTER TABLE marketplace.needs DROP COLUMN IF EXISTS confirmed_at")
    op.execute("ALTER TABLE marketplace.needs DROP COLUMN IF EXISTS no_match_reason")
    op.execute("ALTER TABLE marketplace.needs DROP COLUMN IF EXISTS valid_until")
