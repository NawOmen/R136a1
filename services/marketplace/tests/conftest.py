import os
import uuid
from datetime import date, datetime, timedelta, timezone

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
    "CREATE TABLE IF NOT EXISTS auth.users ("
    " id UUID PRIMARY KEY, last_name VARCHAR(120) NOT NULL, first_name VARCHAR(120) NOT NULL,"
    " middle_name VARCHAR(120), email VARCHAR(255) NOT NULL UNIQUE, password_hash VARCHAR(255) NOT NULL,"
    " phone VARCHAR(40), token_version INTEGER NOT NULL DEFAULT 0, account_status VARCHAR(16) NOT NULL DEFAULT 'active',"
    " is_category_editor BOOLEAN NOT NULL DEFAULT false, is_marketplace_admin BOOLEAN NOT NULL DEFAULT false, created_at TIMESTAMPTZ NOT NULL DEFAULT now(),"
    " updated_at TIMESTAMPTZ NOT NULL DEFAULT now())",
    "CREATE TABLE IF NOT EXISTS auth.companies ("
    " id UUID PRIMARY KEY, full_name VARCHAR(255) NOT NULL, display_name VARCHAR(255) NOT NULL,"
    " legal_form VARCHAR(8) NOT NULL, inn VARCHAR(12) NOT NULL, ogrn VARCHAR(15), ogrnip VARCHAR(15),"
    " kpp VARCHAR(9), legal_address VARCHAR(500) NOT NULL, country VARCHAR(2) NOT NULL DEFAULT 'RU',"
    " verification_status VARCHAR(16) NOT NULL, rejection_reason VARCHAR(500),"
    " created_at TIMESTAMPTZ NOT NULL DEFAULT now(), updated_at TIMESTAMPTZ NOT NULL DEFAULT now())",
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
  marketplace.address_suggestion_limits,
  marketplace.commercial_report_snapshots, marketplace.agent_quality_evaluations, marketplace.business_denial_events,
  auth.company_members, auth.companies, auth.users,
  marketplace.category_registry_revisions, marketplace.market_watches, marketplace.product_price_observations,
  marketplace.deal_reviews, marketplace.delivery_arrangements, marketplace.deal_checkpoints,
  marketplace.support_tickets, marketplace.human_approval_records, marketplace.trust_audit_events,
  marketplace.resilience_events, marketplace.resilience_scenarios,
  marketplace.reserve_commitments, marketplace.resilience_plans,
  marketplace.participant_orders, marketplace.group_offers,
  marketplace.coalition_members, marketplace.coalitions,
  marketplace.compatibility_profiles, marketplace.optimization_variants,
  marketplace.market_opportunities, marketplace.match_events,
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


@pytest.fixture(autouse=True)
def stub_object_storage(monkeypatch):
    """Тесты не должны зависеть от запущенного MinIO: файлы держим в памяти."""
    from app import storage
    from app.api import documents as documents_api, needs as needs_api, products as products_api, stage9 as stage9_api

    stored: dict[str, bytes] = {}

    def upload_object(key: str, data: bytes, content_type: str) -> str:
        stored[key] = data
        return key

    def download_object(key: str) -> bytes:
        return stored.get(key, b"")

    def delete_object(key: str) -> None:
        stored.pop(key, None)

    for module in (storage, documents_api, needs_api, products_api, stage9_api):
        monkeypatch.setattr(module, "upload_object", upload_object, raising=False)
        monkeypatch.setattr(module, "download_object", download_object, raising=False)
        monkeypatch.setattr(module, "delete_object", delete_object, raising=False)
    return stored


@pytest.fixture
async def client(session_factory):
    from app.database import get_db
    from app.main import app

    async def override_get_db():
        async with session_factory() as session:
            from app.category_runtime import current_registry_context
            async with current_registry_context(session):
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
    unique_email = f"{uid.hex}@demo.ru" if email == "u@demo.ru" else email
    await db_session.execute(
        text(
            "INSERT INTO auth.users "
            "(id, last_name, first_name, email, password_hash, account_status) "
            "VALUES (:id, :last_name, :first_name, :email, :password_hash, 'active')"
        ),
        {
            "id": uid,
            "last_name": "Тестов",
            "first_name": "Пользователь",
            "email": unique_email,
            "password_hash": "$2b$12$synthetic.hash.for.marketplace.tests.only",
        },
    )
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
        text(
            "INSERT INTO auth.companies "
            "(id, full_name, display_name, legal_form, inn, legal_address, country, verification_status) "
            "VALUES (:id, :full_name, :display_name, 'ООО', :inn, :address, 'RU', :status)"
        ),
        {
            "id": cid,
            "full_name": f"Общество с ограниченной ответственностью «Тест {cid.hex[:8]}»",
            "display_name": f"ООО «Тест {cid.hex[:8]}»",
            "inn": str(int(cid.hex[:10], 16)).zfill(12)[-10:],
            "address": "г. Москва, ул. Синтетическая, д. 1",
            "status": status,
        },
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

    return jwt.encode({"sub": str(user_id), "exp": __import__("time").time() + 3600}, settings.jwt_secret, algorithm=settings.jwt_algorithm)


async def make_marketplace_admin(db_session: AsyncSession, email: str = "admin@demo.ru") -> uuid.UUID:
    uid = await make_user(db_session, email=email)
    await db_session.execute(
        text("UPDATE auth.users SET is_marketplace_admin = true WHERE id = :id"), {"id": uid}
    )
    await db_session.commit()
    return uid


async def grant_packaging_documents(
    db_session: AsyncSession,
    company_id: uuid.UUID,
    *,
    category: str = "Упаковка и тара",
    subcategory: str | None = "Бумажные стаканы",
    decision_user_id: uuid.UUID | None = None,
    confirms: dict[str, list[str]] | None = None,
) -> list[uuid.UUID]:
    """Подтверждённые проверяющим документы для категории упаковки.

    Тесты, которым нужна успешная публикация товара категории упаковки, должны
    явно подготовить доказательства: загрузка файла сама допуск не выдаёт.
    """
    from app.models import Document

    today = datetime.now(timezone.utc).date()
    created: list[uuid.UUID] = []
    for document_type in ("declaration", "test_report"):
        document = Document(
            company_id=company_id,
            created_by_user_id=decision_user_id,
            name=f"Тестовый документ {document_type}",
            document_type=document_type,
            file_key=f"tests/{uuid.uuid4()}",
            content_type="application/pdf",
            verification_status="verified",
            scope_category=category,
            scope_subcategory=subcategory,
            valid_until=today + timedelta(days=365),
            confirms=(confirms or {}) if document_type == "test_report" else {},
            verified_by_user_id=decision_user_id,
            verified_at=datetime.now(timezone.utc),
            verification_note="Тестовое подтверждение применимости.",
        )
        db_session.add(document)
        await db_session.flush()
        created.append(document.id)
    await db_session.commit()
    return created


async def grant_capacity(db_session, company_id, units, day=None, *, category_id="packaging.paper-cups", unit="шт"):
    """Explicit physical capacity for tests that create binding obligations."""
    from app.models import CapacityEntry
    from app.resource_scopes import prepare_conversions
    conversions=prepare_conversions([{"category_id":category_id,"order_unit":unit,"resource_units_per_order_unit":1}],True)
    db_session.add(CapacityEntry(company_id=company_id, date=day or date.today(), unit=unit,
                                 category_conversions=conversions,available_units=units))
    await db_session.commit()


async def grant_category_capability(db_session,company_id,category_id,characteristics,*,unit='шт',min_units=1,max_units=None):
    """Explicit synthetic producer declaration; never substitutes document review."""
    from app.models import CapabilityPassport
    from app.resource_scopes import find_leaf
    leaf=find_leaf(category_id)
    assert leaf is not None
    scope={'category_id':category_id,'unit':unit,'profile_version':leaf['technical_profile']['version'],
           'min_units':min_units,'max_units':max_units,'characteristics':{key:[value] for key,value in characteristics.items()}}
    passport=await db_session.get(CapabilityPassport,company_id)
    if passport is None:
        passport=CapabilityPassport(company_id=company_id,details={'business_kind':'manufacturer','category_scopes':[scope]},
            technologies=[],materials=[],equipment=[],certifications=[],size_ranges={},delivery_regions=['Москва'],completed_order_types=[])
        db_session.add(passport)
    else:
        passport.details={**(passport.details or {}),'category_scopes':[scope]}
    await db_session.commit()


def confirmed_quote_terms():
    """Explicit synthetic quoted delivery/tax conditions, never a production default."""
    return {'delivery_method':'separate','tax_basis':'no_vat','vat_rate_pct':None,'delivery_conditions':'Синтетический адрес получателя, Россия','expenses':[]}
