"""Migrate recorded monetary scalars without inventing legacy missing terms."""
from alembic import op
import sqlalchemy as sa

revision = '0023'
down_revision = '0022'
branch_labels = None
depends_on = None


def upgrade():
    # PostgreSQL float::numeric preserves its decimal representation; do not infer
    # historic prices, delivery/taxes or commercial snapshots from current cards.
    conn = op.get_bind()
    columns = conn.execute(sa.text("""SELECT table_name,column_name FROM information_schema.columns
        WHERE table_schema='marketplace' AND right(column_name,4)='_rub'
        AND data_type IN ('double precision','real','numeric')""")).all()
    for table,column in columns:
        bad = conn.execute(sa.text(f'SELECT 1 FROM marketplace."{table}" WHERE "{column}" IS NOT NULL AND '
            f'("{column}"::text IN (\'NaN\',\'Infinity\',\'-Infinity\') OR abs("{column}"::numeric)>=1000000000000 '
            f'OR "{column}"::numeric!=round("{column}"::numeric,12)) LIMIT 1')).first()
        if bad:raise RuntimeError(f'Денежное поле {table}.{column} требует проверки источника: миграция не округляет исторические значения')
    for table, column in columns:
        op.alter_column(table,column,type_=sa.Numeric(24,12),schema='marketplace',
                        postgresql_using=f'"{column}"::numeric(24,12)')

    for table,column in [('offers','commercial_terms'),('offers','commercial_quote'),('deals','commercial_snapshot'),
                         ('coalition_members','commercial_estimate'),('participant_orders','commercial_snapshot'),
                         ('resilience_plans','commercial_snapshot'),('reserve_commitments','commercial_terms'),('reserve_commitments','commercial_snapshot')]:
        conn.execute(sa.text(f'ALTER TABLE marketplace."{table}" ADD COLUMN IF NOT EXISTS "{column}" JSONB'))
    op.alter_column('offers','delivery_cost_rub',nullable=True,server_default=None,schema='marketplace')


def downgrade():
    raise RuntimeError('Обратная миграция потеряет точность денежных значений; восстановите резервную копию')
