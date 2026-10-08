"""Preserve existing diagnostic costs without inventing external billing."""
from alembic import op
import sqlalchemy as sa
revision='0004'
down_revision='0003'
branch_labels=None
depends_on=None


def upgrade():
    bad=op.get_bind().execute(sa.text("""SELECT 1 FROM agents.agent_runs WHERE estimated_cost_rub IS NOT NULL AND
      (estimated_cost_rub::text IN ('NaN','Infinity','-Infinity') OR abs(estimated_cost_rub::numeric)>=1000000000000
       OR estimated_cost_rub::numeric!=round(estimated_cost_rub::numeric,12)) LIMIT 1""")).first()
    if bad:raise RuntimeError('Оценки стоимости требуют проверки источника; автоматическое округление истории запрещено')
    op.alter_column('agent_runs','estimated_cost_rub',schema='agents',type_=sa.Numeric(24,12),
                    postgresql_using='estimated_cost_rub::numeric(24,12)')


def downgrade():
    raise RuntimeError('Обратная миграция теряет точность денежных значений; восстановите резервную копию')
