"""S12: versions, reproducible reports and evaluation evidence."""
from alembic import op
from app.models import DealCostVersion, CommercialReportSnapshot, BusinessDenialEvent, AgentQualityEvaluation

revision = "0032"
down_revision = "0031"
branch_labels = None
depends_on = None
TABLES = (DealCostVersion, CommercialReportSnapshot, BusinessDenialEvent, AgentQualityEvaluation)


def upgrade():
    for model in TABLES:
        model.__table__.create(op.get_bind(), checkfirst=True)
    op.execute("""INSERT INTO marketplace.deal_cost_versions
      (deal_id, revision, unit_cost_rub, attributable_expenses_rub, tax_basis, note,
       effective_from, recorded_at, updated_by_user_id, legacy_history_unknown)
      SELECT deal_id, revision, unit_cost_rub, attributable_expenses_rub, tax_basis, note,
             updated_at, updated_at, updated_by_user_id, true
      FROM marketplace.deal_cost_snapshots ON CONFLICT (deal_id, revision) DO NOTHING""")


def downgrade():
    for model in reversed(TABLES):
        model.__table__.drop(op.get_bind(), checkfirst=True)
