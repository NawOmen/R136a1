"""No-DB contract checks; distinct module name from API integration tests."""
import importlib.util
import io
import os
import uuid
from pathlib import Path

from alembic.migration import MigrationContext
from alembic.operations import Operations
from pydantic import ValidationError
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

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


def migration_sql(direction="upgrade"):
    path = Path(__file__).resolve().parents[1] / "alembic/versions/0009_capability_details.py"
    spec = importlib.util.spec_from_file_location("capability_details_migration", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.down_revision == "0008"
    output = io.StringIO()
    ctx = MigrationContext.configure(dialect_name="postgresql", opts={"as_sql": True, "output_buffer": output})
    with Operations.context(ctx):
        getattr(module, direction)()
    return output.getvalue()


def test_migration_has_database_default_for_existing_passports():
    assert "ADD COLUMN IF NOT EXISTS details JSONB DEFAULT '{}'::jsonb NOT NULL" in migration_sql()
    assert "DROP COLUMN details" in migration_sql("downgrade")


@pytest.mark.asyncio
@pytest.mark.parametrize("already_present", [False, True])
async def test_migration_preserves_existing_rows_on_old_and_new_databases(already_present):
    url = os.getenv("TEST_DATABASE_URL")
    if not url:
        pytest.skip("Требуется отдельная тестовая PostgreSQL: TEST_DATABASE_URL")
    engine = create_async_engine(url)
    schema = f"test_capabilities_{uuid.uuid4().hex}"
    try:
        async with engine.connect() as connection:
            transaction = await connection.begin()
            try:
                await connection.execute(text(f"CREATE SCHEMA {schema}"))
                suffix = ", details JSONB NOT NULL DEFAULT '{}'::jsonb" if already_present else ""
                await connection.execute(text(f"CREATE TABLE {schema}.capability_passports (id INTEGER PRIMARY KEY{suffix})"))
                await connection.execute(text(f"INSERT INTO {schema}.capability_passports (id) VALUES (1)"))
                if already_present:
                    await connection.execute(text(f"UPDATE {schema}.capability_passports SET details = :value"),
                                             {"value": '{"product_types":"Синтетические детали"}'})
                for _ in range(2):
                    await connection.execute(text(migration_sql().replace("marketplace.", f"{schema}.")))
                result = await connection.scalar(text(f"SELECT details FROM {schema}.capability_passports WHERE id = 1"))
                assert result == ({"product_types": "Синтетические детали"} if already_present else {})
                await connection.execute(text(migration_sql("downgrade").replace("marketplace.", f"{schema}.")))
                await connection.execute(text(migration_sql().replace("marketplace.", f"{schema}.")))
                assert await connection.scalar(text(f"SELECT count(*) FROM {schema}.capability_passports")) == 1
            finally:
                await transaction.rollback()
    finally:
        await engine.dispose()
