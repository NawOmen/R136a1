"""Область действия и решение проверяющего для документов допуска, совместимо с API v1."""
from alembic import op

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None

COLUMNS = (
    ("scope_category", "VARCHAR(120)"),
    ("scope_subcategory", "VARCHAR(120)"),
    ("valid_until", "DATE"),
    ("verified_by_user_id", "UUID"),
    ("verified_at", "TIMESTAMPTZ"),
    ("verification_note", "VARCHAR(500)"),
)


def upgrade() -> None:
    # 0001 импортирует актуальные модели при чистой установке, поэтому колонки
    # могут уже существовать. Базы, созданные на 0009, получают их здесь.
    for name, type_ in COLUMNS:
        op.execute(f"ALTER TABLE marketplace.documents ADD COLUMN IF NOT EXISTS {name} {type_}")


def downgrade() -> None:
    for name, _ in COLUMNS:
        op.drop_column("documents", name, schema="marketplace")
