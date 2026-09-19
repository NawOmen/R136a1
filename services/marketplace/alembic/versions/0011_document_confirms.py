"""Подтверждённые проверяющим характеристики изделия, совместимо с API v1."""
from alembic import op

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 0001 импортирует актуальные модели при чистой установке, поэтому колонка
    # может уже существовать. Базы, созданные на 0010, получают её здесь.
    op.execute(
        "ALTER TABLE marketplace.documents "
        "ADD COLUMN IF NOT EXISTS confirms JSONB DEFAULT '{}'::jsonb NOT NULL"
    )


def downgrade() -> None:
    op.drop_column("documents", "confirms", schema="marketplace")
