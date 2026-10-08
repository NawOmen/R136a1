"""Upgrade preserves old resources; downgrade cannot discard conversion evidence."""
import importlib.util
import os
import uuid
from pathlib import Path
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine


@pytest.mark.asyncio
@pytest.mark.skipif(not os.getenv('TEST_DATABASE_URL'), reason='Requires isolated PostgreSQL')
async def test_0022_preserves_legacy_rows_repeats_and_guards_downgrade():
    path=Path(__file__).resolve().parents[1]/'alembic/versions/0022_category_registry_revisions.py'
    spec=importlib.util.spec_from_file_location('category_revision_migration',path)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    engine=create_async_engine(os.environ['TEST_DATABASE_URL'])
    schema='test_category_revision_'+uuid.uuid4().hex
    try:
        async with engine.connect() as connection:
            transaction=await connection.begin()
            try:
                await connection.execute(text(f'CREATE SCHEMA {schema}'))
                for table in ('products','capacity_entries','resource_reservations'):
                    await connection.execute(text(f'CREATE TABLE {schema}.{table} (id INTEGER PRIMARY KEY, units INTEGER NOT NULL)'))
                    await connection.execute(text(f'INSERT INTO {schema}.{table} VALUES (1, 12)'))
                def run(sync_connection,direction):
                    class Operations:
                        def execute(self,sql):sync_connection.exec_driver_sql(sql.replace('marketplace.',schema+'.'))
                        def get_bind(self):return self
                        def exec_driver_sql(self,sql):return sync_connection.exec_driver_sql(sql.replace('marketplace.',schema+'.'))
                    module.op=Operations();getattr(module,direction)()
                for _ in range(2):await connection.run_sync(run,'upgrade')
                assert (await connection.execute(text(f'SELECT units, resource_units, resource_conversion FROM {schema}.resource_reservations'))).one()==(12,None,None)
                assert (await connection.execute(text(f'SELECT units, category_conversions FROM {schema}.capacity_entries'))).one()==(12,[])
                assert (await connection.execute(text(f'SELECT units, quantity_conversion FROM {schema}.products'))).one()==(12,None)
                for table,column,value in [('products','quantity_conversion','{}'),('resource_reservations','resource_conversion','{}'),('capacity_entries','category_conversions','[{}]')]:
                    await connection.execute(text(f'UPDATE {schema}.{table} SET {column}=CAST(:value AS JSONB)'),{'value':value})
                    with pytest.raises(RuntimeError):await connection.run_sync(run,'downgrade')
                    await connection.execute(text(f'UPDATE {schema}.{table} SET {column}='+('NULL' if table!='capacity_entries' else "'[]'::jsonb")))
                await connection.run_sync(run,'downgrade');await connection.run_sync(run,'upgrade')
                assert (await connection.execute(text(f'SELECT units FROM {schema}.products'))).scalar()==12
            finally:await transaction.rollback()
    finally:await engine.dispose()
