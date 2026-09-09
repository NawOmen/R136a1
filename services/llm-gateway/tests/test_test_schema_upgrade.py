"""Regression for a developer's database created before capability details."""
import uuid

from sqlalchemy import text

from conftest import CAPABILITY_DETAILS_UPGRADE_SQL


async def test_test_schema_upgrade_keeps_existing_rows_and_details(db_session):
    # A transaction-local test schema; never alter the shared application table.
    schema = f"test_old_passports_{uuid.uuid4().hex}"
    await db_session.execute(text(f"CREATE SCHEMA {schema}"))
    await db_session.execute(text(f"CREATE TABLE {schema}.capability_passports (company_id UUID PRIMARY KEY)"))
    company_id = uuid.uuid4()
    await db_session.execute(text(f"INSERT INTO {schema}.capability_passports VALUES (:id)"), {"id": company_id})
    upgrade = text(CAPABILITY_DETAILS_UPGRADE_SQL.replace("marketplace.", f"{schema}."))
    await db_session.execute(upgrade)
    assert await db_session.scalar(text(f"SELECT details FROM {schema}.capability_passports")) == {}
    await db_session.execute(text(f"UPDATE {schema}.capability_passports SET details = :value"),
                             {"value": '{"business_kind":"stock_supplier"}'})
    await db_session.execute(upgrade)
    row = (await db_session.execute(text(f"SELECT company_id, details FROM {schema}.capability_passports"))).one()
    assert row.company_id == company_id
    assert row.details == {"business_kind": "stock_supplier"}
    # db_session closes without commit, rolling back this isolated schema.
