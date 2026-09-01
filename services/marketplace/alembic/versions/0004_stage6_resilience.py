"""stage 6 reserve pool and resilience scenarios

Revision ID: 0004
Revises: 0003
Create Date: 2026-09-01
"""
from typing import Sequence, Union

from alembic import op

revision: str = "0004"
down_revision: Union[str, None] = "0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS marketplace.resilience_plans (
            id UUID PRIMARY KEY,
            need_id UUID NOT NULL REFERENCES marketplace.needs(id) ON DELETE CASCADE,
            buyer_company_id UUID NOT NULL,
            baseline_variant_id UUID NOT NULL REFERENCES marketplace.optimization_variants(id) ON DELETE RESTRICT,
            baseline_allocations JSONB NOT NULL,
            baseline_total_cost_rub DOUBLE PRECISION NOT NULL,
            baseline_lead_time_days INTEGER NOT NULL,
            current_allocations JSONB NOT NULL DEFAULT '[]'::jsonb,
            current_total_cost_rub DOUBLE PRECISION NOT NULL,
            current_lead_time_days INTEGER NOT NULL,
            max_price_increase_pct DOUBLE PRECISION NOT NULL DEFAULT 5,
            max_delay_days INTEGER NOT NULL DEFAULT 0,
            auto_replace_within_thresholds BOOLEAN NOT NULL DEFAULT false,
            failed_company_ids JSONB NOT NULL DEFAULT '[]'::jsonb,
            status VARCHAR(48) NOT NULL DEFAULT 'preparing_reserves',
            version INTEGER NOT NULL DEFAULT 1,
            confirmed_by_user_id UUID,
            confirmed_at TIMESTAMPTZ,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT uq_resilience_plan_need UNIQUE (need_id)
        )
    """)
    op.execute("""
        CREATE TABLE IF NOT EXISTS marketplace.reserve_commitments (
            id UUID PRIMARY KEY,
            plan_id UUID NOT NULL REFERENCES marketplace.resilience_plans(id) ON DELETE CASCADE,
            company_id UUID NOT NULL,
            offer_id UUID REFERENCES marketplace.offers(id) ON DELETE SET NULL,
            reserve_tier VARCHAR(16) NOT NULL,
            confirmation_status VARCHAR(32) NOT NULL DEFAULT 'pending',
            proposed_capacity_units INTEGER,
            proposed_moq_units INTEGER,
            proposed_unit_price_rub DOUBLE PRECISION,
            proposed_delivery_cost_rub DOUBLE PRECISION,
            proposed_lead_time_days INTEGER,
            price_tiers JSONB NOT NULL DEFAULT '[]'::jsonb,
            confirmed_capacity_units INTEGER,
            confirmed_moq_units INTEGER,
            confirmed_unit_price_rub DOUBLE PRECISION,
            confirmed_delivery_cost_rub DOUBLE PRECISION,
            confirmed_lead_time_days INTEGER,
            held_until DATE,
            confirmed_by_user_id UUID,
            confirmed_at TIMESTAMPTZ,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT uq_reserve_plan_company UNIQUE (plan_id, company_id)
        )
    """)
    op.execute("""
        CREATE TABLE IF NOT EXISTS marketplace.resilience_scenarios (
            id UUID PRIMARY KEY,
            plan_id UUID NOT NULL REFERENCES marketplace.resilience_plans(id) ON DELETE CASCADE,
            scenario_type VARCHAR(24) NOT NULL,
            failed_company_ids JSONB NOT NULL,
            result JSONB NOT NULL,
            input_hash VARCHAR(64) NOT NULL,
            status VARCHAR(32) NOT NULL DEFAULT 'calculated',
            is_simulation BOOLEAN NOT NULL DEFAULT false,
            approved_by_user_id UUID,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """)
    op.execute("""
        CREATE TABLE IF NOT EXISTS marketplace.resilience_events (
            id UUID PRIMARY KEY,
            plan_id UUID NOT NULL REFERENCES marketplace.resilience_plans(id) ON DELETE CASCADE,
            event_type VARCHAR(64) NOT NULL,
            actor_user_id UUID,
            actor_company_id UUID,
            payload JSONB NOT NULL DEFAULT '{}'::jsonb,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """)
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_resilience_events_event_type "
        "ON marketplace.resilience_events (event_type)"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS marketplace.resilience_events")
    op.execute("DROP TABLE IF EXISTS marketplace.resilience_scenarios")
    op.execute("DROP TABLE IF EXISTS marketplace.reserve_commitments")
    op.execute("DROP TABLE IF EXISTS marketplace.resilience_plans")
