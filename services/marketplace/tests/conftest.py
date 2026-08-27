import os
import uuid

import jwt
import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

TEST_DATABASE_URL = os.getenv(
    "TEST_DATABASE_URL", "postgresql+asyncpg://sborka:sborka@localhost:5433/sborka_marketplace_test"
)

AUTH_DDL_STATEMENTS = [
    "CREATE SCHEMA IF NOT EXISTS auth",
    "CREATE TABLE IF NOT EXISTS auth.users (id UUID PRIMARY KEY)",
    "CREATE TABLE IF NOT EXISTS auth.companies (id UUID PRIMARY KEY, verification_status VARCHAR(16) NOT NULL)",
    "CREATE TABLE IF NOT EXISTS auth.company_members ("
    " id UUID PRIMARY KEY,"
    " company_id UUID NOT NULL REFERENCES auth.companies(id),"
    " user_id UUID NOT NULL REFERENCES auth.users(id),"
    " can_buy BOOLEAN NOT NULL DEFAULT false,"
    " can_sell BOOLEAN NOT NULL DEFAULT false,"
    " is_admin BOOLEAN NOT NULL DEFAULT false)",
]

TRUNCATE = """
TRUNCATE
  auth.company_members, auth.companies, auth.users,
  marketplace.need_files, marketplace.offers, marketplace.deals,
  marketplace.notifications, marketplace.needs, marketplace.documents,
  marketplace.capacity_entries, marketplace.products, marketplace.capability_passports,
  marketplace.production_profiles, marketplace.delivery_addresses
CASCADE
"""


@pytest.fixture(scope="session")
async def engine():
    from app import models  # noqa: F401
    from app.database import Base

    eng = create_async_engine(TEST_DATABASE_URL)
    async with eng.begin() as conn:
        await conn.execute(text("CREATE SCHEMA IF NOT EXISTS marketplace"))
        for statement in AUTH_DDL_STATEMENTS:
            await conn.execute(text(statement))
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    yield eng
    await eng.dispose()


@pytest.fixture(scope="session")
def session_factory(engine):
    return async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


@pytest.fixture(autouse=True)
async def clean_db(session_factory):
    async with session_factory() as session:
        await session.execute(text(TRUNCATE))
        await session.commit()
    yield


@pytest.fixture
async def client(session_factory):
    from app.database import get_db
    from app.main import app

    async def override_get_db():
        async with session_factory() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture
async def db_session(session_factory):
    async with session_factory() as session:
        yield session


# ---------- Хелперы для тестов ----------


async def make_user(db_session: AsyncSession, email: str = "u@demo.ru") -> uuid.UUID:
    uid = uuid.uuid4()
    await db_session.execute(text("INSERT INTO auth.users (id) VALUES (:id)"), {"id": uid})
    await db_session.commit()
    return uid


async def make_company(
    db_session: AsyncSession,
    user_id: uuid.UUID,
    can_buy: bool = True,
    can_sell: bool = True,
    verified: bool = True,
) -> uuid.UUID:
    cid = uuid.uuid4()
    status = "verified" if verified else "draft"
    await db_session.execute(
        text("INSERT INTO auth.companies (id, verification_status) VALUES (:id, :s)"),
        {"id": cid, "s": status},
    )
    await db_session.execute(
        text(
            "INSERT INTO auth.company_members (id, company_id, user_id, can_buy, can_sell, is_admin) "
            "VALUES (:id, :cid, :uid, :cb, :cs, true)"
        ),
        {"id": uuid.uuid4(), "cid": cid, "uid": user_id, "cb": can_buy, "cs": can_sell},
    )
    await db_session.commit()
    return cid


def make_token(user_id: uuid.UUID) -> str:
    from app.config import settings

    return jwt.encode({"sub": str(user_id)}, settings.jwt_secret, algorithm=settings.jwt_algorithm)
