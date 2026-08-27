import os

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

TEST_DATABASE_URL = os.getenv(
    "TEST_DATABASE_URL", "postgresql+asyncpg://sborka:sborka@localhost:5432/sborka_test"
)


@pytest.fixture(scope="session")
async def engine():
    from app import models  # noqa: F401
    from app.database import Base

    eng = create_async_engine(TEST_DATABASE_URL)
    async with eng.begin() as conn:
        await conn.execute(text("CREATE SCHEMA IF NOT EXISTS auth"))
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
        await session.execute(
            text(
                "TRUNCATE auth.company_verification_events, auth.company_members, "
                "auth.companies, auth.users CASCADE"
            )
        )
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
