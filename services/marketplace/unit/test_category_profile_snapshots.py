"""Saved technical identity, legacy compatibility and detached audit material."""
import hashlib
import importlib.util
import io
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import unittest

from alembic.migration import MigrationContext
from alembic.operations import Operations
from app.category_profile_snapshot import capture_category_profile, profile_for_insert, profile_after_specification_change
from app.category_registry import registry_snapshot
from app.commerce import product_specification_hash
from app.models import Product, Need
from app.schemas import ProductIn
from app.admission import admission_audit_payload


class ProfileSnapshotTests(unittest.TestCase):
    def test_every_registered_leaf_captures_its_exact_definition(self):
        registry=registry_snapshot()
        for group in registry['groups']:
            for leaf in group['leaves']:
                snap=capture_category_profile(group['label'],leaf['label'])
                self.assertEqual(snap['category_id'],leaf['id'])
                self.assertEqual(snap['profile_version'],leaf['technical_profile']['version'])
                self.assertEqual(snap['fields'],{key:registry['characteristic_fields'][key] for key in leaf['technical_profile']['fields']})

    def test_unknown_and_unclassified_are_unknown_not_current(self):
        self.assertIsNone(capture_category_profile('Строительство',None))
        self.assertIsNone(capture_category_profile('Строительство','Выдумано'))
        self.assertEqual(capture_category_profile('Крепёж',None)['category_id'],'construction.fasteners')

    def test_capture_is_detached_from_future_capture_and_registry(self):
        first=capture_category_profile('Строительство','Крепёж')
        first['fields']['material']['label']='Другое'
        self.assertEqual(capture_category_profile('Строительство','Крепёж')['fields']['material']['label'],'Материал')

    def test_all_trusted_inserts_use_same_capture_and_explicit_unknown_is_nullable(self):
        context=SimpleNamespace(get_current_parameters=lambda:{'category':'Строительство','subcategory':'Крепёж'})
        self.assertEqual(profile_for_insert(context),capture_category_profile('Строительство','Крепёж'))
        for model in (Product,Need):
            column=model.__table__.c.category_profile
            self.assertTrue(column.nullable)
            self.assertTrue(column.type.none_as_null)
            self.assertIsNone(column.server_default)
            self.assertIsNotNone(column.default)

    def test_non_specification_edits_preserve_old_or_unknown_profile(self):
        for snap in (None,{'profile_version':7,'fields':{'material':{'label':'Старое'}}}):
            record=SimpleNamespace(category='Строительство',subcategory='Крепёж',characteristics={'unit':'шт'},category_profile=snap)
            with patch('app.category_profile_snapshot.capture_category_profile',side_effect=AssertionError('Не обновлять автоматически')):
                actual=profile_after_specification_change(record,record.category,record.subcategory,dict(record.characteristics))
            self.assertEqual(actual,snap)
            if actual: actual['fields']['material']['label']='Изменено'
            self.assertEqual(record.category_profile,snap)

    def test_specification_edit_captures_current_without_mutating_old(self):
        record=SimpleNamespace(category='Строительство',subcategory='Крепёж',characteristics={'length_mm':40},category_profile={'profile_version':99})
        new=profile_after_specification_change(record,record.category,record.subcategory,{'length_mm':50})
        self.assertEqual(new,capture_category_profile(record.category,record.subcategory))
        self.assertEqual(record.category_profile,{'profile_version':99})

    def test_legacy_price_history_hash_is_exactly_unchanged(self):
        fields={'category':'Строительство','subcategory':'Крепёж','characteristics':{'unit':'шт'},'moq_units':1}
        expected=hashlib.sha256(json.dumps(fields,sort_keys=True,ensure_ascii=False).encode()).hexdigest()
        self.assertEqual(product_specification_hash(SimpleNamespace(**fields)),expected)
        self.assertEqual(product_specification_hash(SimpleNamespace(**fields,category_profile=None)),expected)
        self.assertNotEqual(product_specification_hash(SimpleNamespace(**fields,category_profile=capture_category_profile(fields['category'],fields['subcategory']))),expected)

    def test_profile_metadata_is_not_a_business_characteristic_or_input(self):
        data=ProductIn(name='Болт',category='Строительство',subcategory='Крепёж',characteristics={'unit':'шт'},price_rub=1,moq_units=1,lead_time_days=1,category_profile={'profile_version':999})
        self.assertNotIn('category_profile',data.model_dump())
        self.assertEqual(data.characteristics,{'unit':'шт'})

    def test_audit_owns_a_detached_specification_snapshot(self):
        from datetime import datetime,timezone
        report=SimpleNamespace(state='admitted',profile_title='Профиль',profile_key='key',rules_version='rules',blocking_open=0,checked_at=datetime.now(timezone.utc),requirements=[])
        specification={'category_profile':capture_category_profile('Строительство','Крепёж'),'characteristics':{'unit':'шт'}}
        payload=admission_audit_payload(report,specification=specification)
        specification['category_profile']['fields']['material']['label']='Изменено'
        specification['characteristics']['unit']='кг'
        self.assertEqual(payload['specification']['characteristics']['unit'],'шт')
        self.assertEqual(payload['specification']['category_profile']['fields']['material']['label'],'Материал')

    def test_migration_adds_only_nullable_columns_without_backfill_or_defaults(self):
        module=migration()
        output=io.StringIO()
        context=MigrationContext.configure(dialect_name='postgresql',opts={'as_sql':True,'output_buffer':output})
        with Operations.context(context): module.upgrade()
        sql=output.getvalue()
        self.assertEqual(module.down_revision,'0020')
        self.assertIn('marketplace.products ADD COLUMN IF NOT EXISTS category_profile JSONB',sql)
        self.assertIn('marketplace.needs ADD COLUMN IF NOT EXISTS category_profile JSONB',sql)
        for forbidden in ('UPDATE ', 'NOT NULL', 'DEFAULT '): self.assertNotIn(forbidden,sql)


def migration():
    path=Path(__file__).resolve().parents[1]/'alembic/versions/0021_category_profile_snapshots.py'
    spec=importlib.util.spec_from_file_location('snapshot_migration',path)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module


import os
import uuid
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine


@unittest.skipUnless(os.getenv('TEST_DATABASE_URL'), 'Изолированная PostgreSQL проверяется в CI')
class MigrationDatabaseTests(unittest.IsolatedAsyncioTestCase):
    async def test_existing_rows_repeat_upgrade_and_guarded_downgrade(self):
        engine=create_async_engine(os.environ['TEST_DATABASE_URL'])
        schema='test_profiles_'+uuid.uuid4().hex
        try:
            async with engine.connect() as connection:
                transaction=await connection.begin()
                try:
                    for sql in (f'CREATE SCHEMA {schema}',
                                f'CREATE TABLE {schema}.products (id INTEGER PRIMARY KEY, characteristics JSONB NOT NULL)',
                                f'CREATE TABLE {schema}.needs (id INTEGER PRIMARY KEY, characteristics JSONB NOT NULL)'):
                        await connection.execute(text(sql))
                    for table in ('products','needs'):
                        await connection.execute(text(f'INSERT INTO {schema}.{table} VALUES (1, :value)'),{'value':'{"dimensions":"120×60×75 см"}'})
                    module=migration()
                    def run(connection_sync,direction):
                        operations=Operations(MigrationContext.configure(connection_sync))
                        class SchemaOperations:
                            def execute(self,statement): operations.execute(statement.replace('marketplace.',schema+'.'))
                            def get_bind(self): return self
                            def exec_driver_sql(self,statement): return connection_sync.exec_driver_sql(statement.replace('marketplace.',schema+'.'))
                        module.op=SchemaOperations()
                        getattr(module,direction)()
                    for _ in range(2): await connection.run_sync(run,'upgrade')
                    for table in ('products','needs'):
                        row=(await connection.execute(text(f'SELECT characteristics, category_profile FROM {schema}.{table} WHERE id=1'))).one()
                        self.assertEqual(row.characteristics,{'dimensions':'120×60×75 см'})
                        self.assertIsNone(row.category_profile)
                    await connection.execute(text(f"UPDATE {schema}.needs SET category_profile='{{\"profile_version\":1}}'::jsonb WHERE id=1"))
                    with self.assertRaises(RuntimeError): await connection.run_sync(run,'downgrade')
                    for table in ('products','needs'):
                        await connection.execute(text(f'SELECT category_profile FROM {schema}.{table}'))
                    await connection.execute(text(f'UPDATE {schema}.needs SET category_profile=NULL'))
                    await connection.run_sync(run,'downgrade')
                    await connection.run_sync(run,'upgrade')
                    self.assertIsNone((await connection.execute(text(f'SELECT category_profile FROM {schema}.needs'))).scalar())
                finally: await transaction.rollback()
        finally: await engine.dispose()
