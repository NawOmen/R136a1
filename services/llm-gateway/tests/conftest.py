import os
import uuid

import jwt
import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

TEST_DATABASE_URL = os.getenv(
    "TEST_DATABASE_URL", "postgresql+asyncpg://sborka:sborka@localhost:5433/sborka_agents_test"
)

# CREATE TABLE IF NOT EXISTS does not upgrade pre-existing local test tables.
CAPABILITY_DETAILS_UPGRADE_SQL = (
    "ALTER TABLE marketplace.capability_passports "
    "ADD COLUMN IF NOT EXISTS details JSONB NOT NULL DEFAULT '{}'::jsonb"
)


@pytest.fixture(scope="session")
async def engine():
    from app import models  # noqa: F401
    from app.database import Base

    engine = create_async_engine(TEST_DATABASE_URL)
    async with engine.begin() as connection:
        await connection.execute(text("CREATE SCHEMA IF NOT EXISTS auth"))
        await connection.execute(text("CREATE SCHEMA IF NOT EXISTS marketplace"))
        await connection.execute(text("CREATE SCHEMA IF NOT EXISTS agents"))
        await connection.execute(
            text(
                "CREATE TABLE IF NOT EXISTS auth.users ("
                "id UUID PRIMARY KEY, last_name VARCHAR(120) NOT NULL, first_name VARCHAR(120) NOT NULL, "
                "middle_name VARCHAR(120), email VARCHAR(255) NOT NULL UNIQUE, password_hash VARCHAR(255) NOT NULL, "
                "phone VARCHAR(40), account_status VARCHAR(16) NOT NULL DEFAULT 'active', "
                "is_marketplace_admin BOOLEAN NOT NULL DEFAULT false, created_at TIMESTAMPTZ DEFAULT now(), "
                "updated_at TIMESTAMPTZ DEFAULT now())"
            )
        )
        await connection.execute(
            text(
                "CREATE TABLE IF NOT EXISTS auth.companies ("
                "id UUID PRIMARY KEY, full_name VARCHAR(255) NOT NULL, display_name VARCHAR(255) NOT NULL, "
                "legal_form VARCHAR(8) NOT NULL, inn VARCHAR(12) NOT NULL, ogrn VARCHAR(15), ogrnip VARCHAR(15), "
                "kpp VARCHAR(9), legal_address VARCHAR(500) NOT NULL, country VARCHAR(2) NOT NULL DEFAULT 'RU', "
                "verification_status VARCHAR(16) NOT NULL, rejection_reason VARCHAR(500), "
                "created_at TIMESTAMPTZ DEFAULT now(), updated_at TIMESTAMPTZ DEFAULT now())"
            )
        )
        await connection.execute(
            text(
                "CREATE TABLE IF NOT EXISTS auth.company_members ("
                "id UUID PRIMARY KEY, company_id UUID NOT NULL, user_id UUID NOT NULL, "
                "can_buy BOOLEAN NOT NULL DEFAULT false, can_sell BOOLEAN NOT NULL DEFAULT false, "
                "is_admin BOOLEAN NOT NULL DEFAULT false, created_at TIMESTAMPTZ DEFAULT now())"
            )
        )
        await connection.execute(
            text(
                "CREATE TABLE IF NOT EXISTS marketplace.capability_passports ("
                "company_id UUID PRIMARY KEY, technologies JSONB NOT NULL DEFAULT '[]', "
                "equipment JSONB NOT NULL DEFAULT '[]', materials JSONB NOT NULL DEFAULT '[]', "
                "size_ranges JSONB NOT NULL DEFAULT '{}', details JSONB NOT NULL DEFAULT '{}', tolerances VARCHAR(500), "
                "certifications JSONB NOT NULL DEFAULT '[]', min_order_units INTEGER, max_order_units INTEGER, "
                "delivery_regions JSONB NOT NULL DEFAULT '[]', completed_order_types JSONB NOT NULL DEFAULT '[]')"
            )
        )
        await connection.execute(text(CAPABILITY_DETAILS_UPGRADE_SQL))
        await connection.run_sync(Base.metadata.drop_all)
        await connection.execute(text(
            "CREATE TABLE IF NOT EXISTS marketplace.products (id UUID PRIMARY KEY, company_id UUID NOT NULL, "
            "name VARCHAR(255) NOT NULL, category VARCHAR(120) NOT NULL, subcategory VARCHAR(120), characteristics JSONB NOT NULL DEFAULT '{}', "
            "price_rub DOUBLE PRECISION NOT NULL, price_tiers JSONB NOT NULL DEFAULT '[]', "
            "moq_units INTEGER NOT NULL, lead_time_days INTEGER NOT NULL, is_published BOOLEAN NOT NULL DEFAULT false)"
        ))
        await connection.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest.fixture(scope="session")
def session_factory(engine):
    return async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


@pytest.fixture(autouse=True)
async def clean_db(session_factory):
    async with session_factory() as session:
        await session.execute(
            text(
                "TRUNCATE agents.tool_calls, agents.agent_runs, "
                "auth.company_members, auth.companies, auth.users, "
                "marketplace.capability_passports, marketplace.products CASCADE"
            )
        )
        await session.commit()
    yield


@pytest.fixture
async def db_session(session_factory):
    async with session_factory() as session:
        yield session


@pytest.fixture
async def user_id(db_session):
    user_id = uuid.uuid4()
    await db_session.execute(
        text(
            "INSERT INTO auth.users "
            "(id, last_name, first_name, email, password_hash, account_status) "
            "VALUES (:id, 'Тестов', 'Пользователь', :email, 'synthetic-hash', 'active')"
        ),
        {"id": user_id, "email": f"{user_id.hex}@demo.ru"},
    )
    await db_session.commit()
    return user_id


@pytest.fixture
def token(user_id):
    from app.config import settings

    return jwt.encode(
        {"sub": str(user_id), "exp": __import__("time").time() + 3600}, settings.jwt_secret, algorithm=settings.jwt_algorithm
    )


@pytest.fixture
async def client(session_factory, fake_provider):
    from app.database import get_db
    from app.main import app

    async def override_db():
        async with session_factory() as session:
            yield session

    app.dependency_overrides[get_db] = override_db
    app.state.llm_provider = fake_provider
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        yield client
    app.dependency_overrides.clear()
    del app.state.llm_provider


class FakeProvider:
    route_name = "local_qwen"

    def __init__(self):
        self.local = self
        self.extraction = None
        self.prompts = []

    async def structured(self, system, prompt, response_model, prefer_external=False):
        from app.schemas import RawExtraction, RawFact

        self.prompts.append((response_model.__name__, prompt, prefer_external))

        if response_model.__name__ == "ExplanationDraft":
            return (
                response_model(
                    explanation="Возможности производства сопоставлены с категорией запроса."
                ),
                self.route_name,
                None,
            )
        if response_model.__name__ == "ComplexReview":
            return response_model(notes=[]), self.route_name, None

        result = self.extraction or RawExtraction(
            category="бумажные стаканы",
            facts=[
                RawFact(
                    key="quantity_units",
                    value=5000,
                    source_id="request_text",
                    confidence=0.95,
                    evidence="нужно 5000 стаканов",
                ),
                RawFact(
                    key="lead_time_days",
                    value=10,
                    source_id="request_text",
                    confidence=0.9,
                    evidence="за десять дней",
                ),
                RawFact(
                    key="delivery_city",
                    value="Москва",
                    source_id="request_text",
                    confidence=0.95,
                    evidence="доставка в Москву",
                ),
            ],
        )
        return result, self.route_name, None

    async def vision_text(self, image_base64, prompt):
        return "На изображении бумажный стакан с маркировкой 400 мл"


@pytest.fixture
def fake_provider():
    return FakeProvider()
