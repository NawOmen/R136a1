"""Regression checks for installations already at revision 0007."""
import importlib.util
import io
import os
from pathlib import Path
import uuid

from alembic.migration import MigrationContext
from alembic.operations import Operations
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from app.models import MarketWatch, ProductPriceObservation


def migration_sql(direction="upgrade"):
    path = Path(__file__).resolve().parents[1] / "alembic/versions/0008_stage9_indexes.py"
    spec = importlib.util.spec_from_file_location("stage9_indexes", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    assert migration.down_revision == "0007"
    output = io.StringIO()
    context = MigrationContext.configure(
        dialect_name="postgresql", opts={"as_sql": True, "output_buffer": output}
    )
    with Operations.context(context):
        getattr(migration, direction)()
    return output.getvalue()


def test_index_migration_matches_models_and_has_safe_downgrade():
    upgrade = migration_sql()
    downgrade = migration_sql("downgrade")
    for model, column in ((ProductPriceObservation, "product_id"), (MarketWatch, "user_id")):
        index = next(i for i in model.__table__.indexes if list(i.columns.keys()) == [column])
        assert f"CREATE INDEX IF NOT EXISTS {index.name} ON marketplace.{model.__tablename__}({column})" in upgrade
        assert f"DROP INDEX IF EXISTS marketplace.{index.name}" in downgrade


@pytest.mark.asyncio
async def test_index_migration_on_existing_tables_and_repeated_upgrade():
    database_url = os.getenv("TEST_DATABASE_URL")
    if not database_url:
        pytest.skip("Требуется отдельная тестовая PostgreSQL: TEST_DATABASE_URL")
    engine = create_async_engine(database_url)
    schema = f"test_stage9_{uuid.uuid4().hex}"
    try:
        async with engine.connect() as connection:
            transaction = await connection.begin()
            try:
                await connection.execute(text(f"CREATE SCHEMA {schema}"))
                await connection.execute(text(f"CREATE TABLE {schema}.product_price_observations (product_id UUID)"))
                await connection.execute(text(f"CREATE TABLE {schema}.market_watches (user_id UUID)"))
                for direction in ("upgrade", "upgrade", "downgrade", "upgrade"):
                    for statement in migration_sql(direction).replace("marketplace.", f"{schema}.").split(";"):
                        if statement.strip():
                            await connection.execute(text(statement))
                    names = set((await connection.execute(
                        text("SELECT indexname FROM pg_indexes WHERE schemaname = :schema"),
                        {"schema": schema},
                    )).scalars())
                    assert names == (set() if direction == "downgrade" else {
                        "ix_marketplace_product_price_observations_product_id", "ix_marketplace_market_watches_user_id",
                    })
            finally:
                await transaction.rollback()
    finally:
        await engine.dispose()
