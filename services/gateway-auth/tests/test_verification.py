import uuid

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from app.deps import require_verified_company
from app.models import Company, CompanyVerificationEvent, User

ADMIN_EMAIL = "admin@test.ru"
USER_EMAIL = "user@test.ru"

COMPANY = {
    "full_name": "ООО «Проверка»",
    "display_name": "ООО «Проверка»",
    "legal_form": "ООО",
    "inn": "1234567890",
    "ogrn": "1234567890123",
    "kpp": "123456789",
    "legal_address": "г. Москва, ул. Проверочная, д. 1",
    "can_buy": True,
    "can_sell": True,
}


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


async def _register(client, email: str, last: str = "Тест", first: str = "Пользователь") -> str:
    r = await client.post(
        "/api/v1/auth/register",
        json={"last_name": last, "first_name": first, "email": email, "password": "secret123"},
    )
    assert r.status_code == 201
    return r.json()["access_token"]


async def _make_admin(client, db_session) -> str:
    token = await _register(client, ADMIN_EMAIL, "Админ", "Администратор")
    user = (await db_session.execute(select(User).where(User.email == ADMIN_EMAIL))).scalar_one()
    user.is_marketplace_admin = True
    await db_session.commit()
    return token


async def _company_in_review(client, token: str) -> str:
    c = (await client.post("/api/v1/companies", json=COMPANY, headers=_auth(token))).json()
    await client.post(f"/api/v1/companies/{c['id']}/submit-review", headers=_auth(token))
    return c["id"]


async def test_admin_approve_company(client, db_session):
    admin_token = await _make_admin(client, db_session)
    user_token = await _register(client, USER_EMAIL)
    cid = await _company_in_review(client, user_token)

    r = await client.post(
        f"/api/v1/admin/companies/{cid}/verification",
        json={"decision": "approve", "reason": "реквизиты корректны"},
        headers=_auth(admin_token),
    )
    assert r.status_code == 200
    assert r.json()["verification_status"] == "verified"

    events = (await db_session.execute(select(CompanyVerificationEvent))).scalars().all()
    assert len(events) == 1
    assert events[0].to_status == "verified"
    assert events[0].performed_by_user_id is not None


async def test_admin_reject_company(client, db_session):
    admin_token = await _make_admin(client, db_session)
    user_token = await _register(client, USER_EMAIL)
    cid = await _company_in_review(client, user_token)

    r = await client.post(
        f"/api/v1/admin/companies/{cid}/verification",
        json={"decision": "reject", "reason": "неверные реквизиты"},
        headers=_auth(admin_token),
    )
    assert r.status_code == 200
    assert r.json()["verification_status"] == "rejected"


async def test_non_admin_cannot_verify(client, db_session):
    user_token = await _register(client, USER_EMAIL)
    cid = await _company_in_review(client, user_token)

    r = await client.post(
        f"/api/v1/admin/companies/{cid}/verification",
        json={"decision": "approve"},
        headers=_auth(user_token),
    )
    assert r.status_code == 403


async def test_block_user(client, db_session):
    admin_token = await _make_admin(client, db_session)
    user_token = await _register(client, USER_EMAIL)
    user = (await db_session.execute(select(User).where(User.email == USER_EMAIL))).scalar_one()

    r = await client.post(
        f"/api/v1/admin/users/{user.id}/block", json={"blocked": True}, headers=_auth(admin_token)
    )
    assert r.status_code == 200
    assert r.json()["account_status"] == "blocked"

    login = await client.post("/api/v1/auth/login", json={"email": USER_EMAIL, "password": "secret123"})
    assert login.status_code == 401


async def test_unverified_company_cannot_publish(client, db_session):
    token = await _register(client, USER_EMAIL)
    c = (await client.post("/api/v1/companies", json=COMPANY, headers=_auth(token))).json()
    company_id = uuid.UUID(c["id"])

    user = (await db_session.execute(select(User).where(User.email == USER_EMAIL))).scalar_one()

    with pytest.raises(HTTPException) as exc_info:
        await require_verified_company(company_id, user, db_session)
    assert exc_info.value.status_code == 403

    company = (await db_session.execute(select(Company).where(Company.id == company_id))).scalar_one()
    company.verification_status = "verified"
    await db_session.commit()

    result = await require_verified_company(company_id, user, db_session)
    assert result.verification_status == "verified"
