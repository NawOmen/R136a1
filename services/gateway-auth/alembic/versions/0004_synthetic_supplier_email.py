"""Repair only the deterministic legacy synthetic supplier, retaining its identity."""
import uuid

from alembic import op
import sqlalchemy as sa

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None

LEGACY_ID = uuid.uuid5(uuid.UUID("63fbb020-7627-4b46-baa9-6cdd823cbe52"), "user:supplier@porukam.test")


def upgrade():
    connection = op.get_bind()
    legacy = connection.execute(sa.text(
        "SELECT id FROM auth.users WHERE id=:id AND email='supplier@porukam.test'"
    ), {"id": LEGACY_ID}).first()
    if legacy is None:
        return
    conflict = connection.execute(sa.text(
        "SELECT id FROM auth.users WHERE email='supplier@demo.ru' AND id<>:id"
    ), {"id": LEGACY_ID}).first()
    if conflict:
        raise RuntimeError("Synthetic supplier email collision: resolve fixture identities before migration")
    connection.execute(sa.text(
        "UPDATE auth.users SET email='supplier@demo.ru' WHERE id=:id AND email='supplier@porukam.test'"
    ), {"id": LEGACY_ID})


def downgrade():
    # Restoring a reserved-domain address would break the current API contract.
    pass
