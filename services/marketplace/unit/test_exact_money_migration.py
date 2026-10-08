"""The monetary migration preserves unknown history and refuses precision loss."""
import importlib.util
import os
import uuid
from decimal import Decimal
from pathlib import Path
import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine


@pytest.mark.asyncio
@pytest.mark.skipif(not os.getenv('TEST_DATABASE_URL'), reason='Requires isolated PostgreSQL')
async def test_0023_preserves_values_nulls_and_refuses_loss():
    spec=importlib.util.spec_from_file_location('money_migration',Path(__file__).resolve().parents[1]/'alembic/versions/0023_exact_money.py')
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    engine=create_async_engine(os.environ['TEST_DATABASE_URL'])
    schema='test_money_'+uuid.uuid4().hex
    try:
        async with engine.connect() as connection:
            transaction=await connection.begin()
            try:
                await connection.execute(text(f'CREATE SCHEMA {schema}'))
                for table in ('offers','deals','coalition_members','participant_orders','resilience_plans','reserve_commitments'):
                    await connection.execute(text(f'CREATE TABLE {schema}.{table} (id INTEGER PRIMARY KEY, price_rub DOUBLE PRECISION, delivery_cost_rub DOUBLE PRECISION DEFAULT 0)'))
                    await connection.execute(text(f'INSERT INTO {schema}.{table} VALUES (1,10.9,NULL),(2,NULL,2.675)'))
                def run(sync_connection,direction):
                    real_op=Operations(MigrationContext.configure(sync_connection))
                    class AdaptedOperations:
                        def get_bind(self):return self
                        def execute(self,query):
                            return sync_connection.execute(text(str(query).replace("table_schema='marketplace'",f"table_schema='{schema}'").replace('marketplace.',schema+'.')))
                        def alter_column(self,*args,**kwargs):kwargs['schema']=schema;return real_op.alter_column(*args,**kwargs)
                        def add_column(self,*args,**kwargs):kwargs['schema']=schema;return real_op.add_column(*args,**kwargs)
                    module.op=AdaptedOperations();getattr(module,direction)()
                await connection.execute(text(f'UPDATE {schema}.offers SET price_rub=0.0000000000001 WHERE id=1'))
                with pytest.raises(RuntimeError,match='не округляет'):await connection.run_sync(run,'upgrade')
                await connection.execute(text(f'UPDATE {schema}.offers SET price_rub=10.9 WHERE id=1'))
                await connection.run_sync(run,'upgrade')
                rows=(await connection.execute(text(f'SELECT price_rub,delivery_cost_rub,commercial_quote FROM {schema}.offers ORDER BY id'))).all()
                assert rows==[(Decimal('10.9'),None,None),(None,Decimal('2.675'),None)]
                assert (await connection.execute(text(f"SELECT data_type,numeric_scale FROM information_schema.columns WHERE table_schema='{schema}' AND table_name='offers' AND column_name='price_rub'"))).one()==('numeric',12)
                with pytest.raises(RuntimeError,match='потеряет точность'):await connection.run_sync(run,'downgrade')
            finally:await transaction.rollback()
    finally:await engine.dispose()
