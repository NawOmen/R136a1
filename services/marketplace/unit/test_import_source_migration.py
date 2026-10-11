"""Catalog provenance stays unknown for legacy rows during migration."""
import importlib.util
import os
import uuid
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine


@pytest.mark.asyncio
@pytest.mark.skipif(not os.getenv("TEST_DATABASE_URL"), reason="Requires isolated PostgreSQL")
async def test_import_source_migration_preserves_legacy_rows_and_repeat():
    path = Path(__file__).resolve().parents[1] / "alembic/versions/0033_import_source.py"
    spec = importlib.util.spec_from_file_location("import_source_migration", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    engine = create_async_engine(os.environ["TEST_DATABASE_URL"])
    schema = "test_import_source_" + uuid.uuid4().hex
    try:
        async with engine.connect() as connection:
            transaction = await connection.begin()
            try:
                await connection.execute(text(f"CREATE SCHEMA {schema}"))
                await connection.execute(text(f"CREATE TABLE {schema}.catalog_imports "
                                              "(id INTEGER PRIMARY KEY, content_hash VARCHAR(64), product_ids JSONB)"))
                await connection.execute(text(f"INSERT INTO {schema}.catalog_imports "
                                              "VALUES (1, 'original-hash', '[\"original-product\"]')"))

                def run(sync_connection, direction):
                    class SchemaOperations:
                        def execute(self, statement):
                            return sync_connection.execute(text(statement.replace("marketplace.", schema + ".")))

                    migration.op = SchemaOperations()
                    getattr(migration, direction)()

                for _ in range(2):
                    await connection.run_sync(run, "upgrade")
                row = (await connection.execute(text(f"SELECT content_hash, product_ids, source_system "
                                                      f"FROM {schema}.catalog_imports WHERE id=1"))).one()
                assert tuple(row) == ("original-hash", ["original-product"], None)
                await connection.execute(text(f"UPDATE {schema}.catalog_imports SET source_system='1C:ERP' WHERE id=1"))
                await connection.run_sync(run, "upgrade")
                assert await connection.scalar(text(f"SELECT source_system FROM {schema}.catalog_imports WHERE id=1")) == "1C:ERP"
                await connection.run_sync(run, "downgrade")
                row = (await connection.execute(text(f"SELECT content_hash, product_ids "
                                                      f"FROM {schema}.catalog_imports WHERE id=1"))).one()
                assert tuple(row) == ("original-hash", ["original-product"])
                await connection.run_sync(run, "upgrade")
                assert await connection.scalar(text(f"SELECT source_system FROM {schema}.catalog_imports WHERE id=1")) is None
            finally:
                await transaction.rollback()
    finally:
        await engine.dispose()
