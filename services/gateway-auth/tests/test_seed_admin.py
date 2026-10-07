import importlib.util
from pathlib import Path
from types import SimpleNamespace
import uuid

import pytest
from sqlalchemy import select

from app.models import Company, CompanyMember, User
from app.security import create_access_token


def migration():
    path = Path(__file__).resolve().parents[1] / "alembic/versions/0004_synthetic_supplier_email.py"
    spec = importlib.util.spec_from_file_location("supplier_email_migration", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


async def test_seed_accounts_can_be_listed_by_admin(client, session_factory, monkeypatch):
    import seed

    monkeypatch.setattr(seed, "SessionLocal", session_factory)
    for name in ("SEED_ADMIN_PASSWORD", "SEED_DEMO_PASSWORD", "SEED_SELLER_PASSWORD"):
        monkeypatch.setenv(name, "synthetic-seed-password-for-test")
    for name in ("SEED_ADMIN_EMAIL", "SEED_DEMO_EMAIL", "SEED_SELLER_EMAIL", "SEED_SELLER2_EMAIL"):
        monkeypatch.delenv(name, raising=False)
    await seed.seed()
    # Re-running the seed retains the same accounts.
    await seed.seed()
    async with session_factory() as db:
        admin = await db.scalar(select(User).where(User.email == "admin@demo.ru"))
        token = create_access_token(str(admin.id))
    response = await client.get("/api/v1/admin/users", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 200, response.text
    assert {row["email"] for row in response.json()["users"]} == {
        "admin@demo.ru", "demo@demo.ru", "seller@demo.ru", "supplier@demo.ru",
    }


async def test_legacy_seed_migration_preserves_identity_and_membership(db_session, monkeypatch):
    module = migration()
    user = User(id=module.LEGACY_ID, email="supplier@porukam.test", first_name="Мария",
                last_name="Петрова", password_hash="unchanged-synthetic-hash")
    company = Company(id=uuid.uuid4(), display_name="Синтетическая компания", full_name="Синтетическая компания",
                      legal_form="ООО", inn="0000000003", legal_address="Синтетический адрес", country="RU")
    db_session.add_all([user, company])
    await db_session.flush()
    member = CompanyMember(user_id=user.id, company_id=company.id, can_sell=True, is_admin=True)
    db_session.add(member)
    await db_session.flush()
    connection = await db_session.connection()
    def upgrade(sync_connection):
        monkeypatch.setattr(module, "op", SimpleNamespace(get_bind=lambda: sync_connection))
        module.upgrade()
        module.upgrade()
    await connection.run_sync(upgrade)
    await db_session.refresh(user)
    await db_session.refresh(member)
    assert user.email == "supplier@demo.ru"
    assert user.password_hash == "unchanged-synthetic-hash"
    assert member.user_id == module.LEGACY_ID and member.can_sell and member.is_admin


async def test_legacy_seed_email_collision_does_not_merge_accounts(db_session, monkeypatch):
    module = migration()
    db_session.add_all([
        User(id=module.LEGACY_ID, email="supplier@porukam.test", first_name="Мария", last_name="Петрова", password_hash="legacy"),
        User(email="supplier@demo.ru", first_name="Другой", last_name="Пользователь", password_hash="other"),
    ])
    await db_session.flush()
    connection = await db_session.connection()
    def upgrade(sync_connection):
        monkeypatch.setattr(module, "op", SimpleNamespace(get_bind=lambda: sync_connection))
        with pytest.raises(RuntimeError, match="collision"):
            module.upgrade()
    await connection.run_sync(upgrade)
    legacy = await db_session.get(User, module.LEGACY_ID)
    assert legacy.email == "supplier@porukam.test"
