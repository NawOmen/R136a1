import importlib.util
import io
from pathlib import Path

from alembic.migration import MigrationContext
from alembic.operations import Operations
from pydantic import ValidationError
import pytest

from app.schemas import CapabilityDetails, CapabilityPassportIn


def test_existing_v1_payload_is_valid():
    passport = CapabilityPassportIn(materials=["крафт"])
    assert "details" not in passport.model_fields_set
    assert passport.details.business_kind == "manufacturer"


@pytest.mark.parametrize("payload", [{"product_types": "x" * 1201}, {"business_kind": "unknown"}, {"secret": "no"}])
def test_details_are_bounded_and_typed(payload):
    with pytest.raises(ValidationError):
        CapabilityDetails(**payload)


def test_order_limits():
    with pytest.raises(ValidationError):
        CapabilityPassportIn(min_order_units=1000, max_order_units=100)


def test_migration_has_database_default_for_existing_passports():
    path = Path(__file__).resolve().parents[1] / "alembic/versions/0009_capability_details.py"
    spec = importlib.util.spec_from_file_location("capability_details_migration", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.down_revision == "0008"
    output = io.StringIO()
    ctx = MigrationContext.configure(dialect_name="postgresql", opts={"as_sql": True, "output_buffer": output})
    with Operations.context(ctx):
        module.upgrade()
        module.downgrade()
    assert "ADD COLUMN details JSONB DEFAULT '{}'::jsonb NOT NULL" in output.getvalue()
    assert "DROP COLUMN details" in output.getvalue()
