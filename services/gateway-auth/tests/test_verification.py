import uuid

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from app.deps import require_company_buyer, require_company_seller, require_verified_company
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


async def _create_company(client, token: str, **overrides) -> dict:
    payload = {**COMPANY, **overrides}
    r = await client.post("/api/v1/companies", json=payload, headers=_auth(token))
    assert r.status_code == 201
    return r.json()


async def _submit(client, token: str, company_id: str) -> None:
    r = await client.post(f"/api/v1/companies/{company_id}/submit-review", headers=_auth(token))
    assert r.status_code == 200


async def _user(db_session, email: str) -> User:
    return (await db_session.execute(select(User).where(User.email == email))).scalar_one()


async def _company(db_session, company_id: str) -> Company:
    return (await db_session.execute(select(Company).where(Company.id == uuid.UUID(company_id)))).scalar_one()


# ---------- Решение администратора ----------


async def test_admin_approve_company(client, db_session):
    admin_token = await _make_admin(client, db_session)
    user_token = await _register(client, USER_EMAIL)
    company = await _create_company(client, user_token)
    await _submit(client, user_token, company["id"])

    r = await client.post(
        f"/api/v1/admin/companies/{company['id']}/verification",
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
    company = await _create_company(client, user_token)
    await _submit(client, user_token, company["id"])

    r = await client.post(
        f"/api/v1/admin/companies/{company['id']}/verification",
        json={"decision": "reject", "reason": "неверные реквизиты"},
        headers=_auth(admin_token),
    )
    assert r.status_code == 200
    assert r.json()["verification_status"] == "rejected"
    assert r.json()["rejection_reason"] == "неверные реквизиты"


async def test_non_admin_cannot_verify(client, db_session):
    user_token = await _register(client, USER_EMAIL)
    company = await _create_company(client, user_token)
    await _submit(client, user_token, company["id"])

    r = await client.post(
        f"/api/v1/admin/companies/{company['id']}/verification",
        json={"decision": "approve"},
        headers=_auth(user_token),
    )
    assert r.status_code == 403


# ---------- Переходы статусов ----------


async def test_draft_to_verified_forbidden(client, db_session):
    admin_token = await _make_admin(client, db_session)
    user_token = await _register(client, USER_EMAIL)
    company = await _create_company(client, user_token)  # draft

    r = await client.post(
        f"/api/v1/admin/companies/{company['id']}/verification",
        json={"decision": "approve"},
        headers=_auth(admin_token),
    )
    assert r.status_code == 409


async def test_verified_to_rejected_forbidden(client, db_session):
    admin_token = await _make_admin(client, db_session)
    user_token = await _register(client, USER_EMAIL)
    company = await _create_company(client, user_token)
    await _submit(client, user_token, company["id"])
    await client.post(
        f"/api/v1/admin/companies/{company['id']}/verification",
        json={"decision": "approve"},
        headers=_auth(admin_token),
    )

    r = await client.post(
        f"/api/v1/admin/companies/{company['id']}/verification",
        json={"decision": "reject", "reason": "передумал"},
        headers=_auth(admin_token),
    )
    assert r.status_code == 409


async def test_rejected_to_verified_without_resubmit_forbidden(client, db_session):
    admin_token = await _make_admin(client, db_session)
    user_token = await _register(client, USER_EMAIL)
    company = await _create_company(client, user_token)
    await _submit(client, user_token, company["id"])
    await client.post(
        f"/api/v1/admin/companies/{company['id']}/verification",
        json={"decision": "reject", "reason": "неверные данные"},
        headers=_auth(admin_token),
    )

    r = await client.post(
        f"/api/v1/admin/companies/{company['id']}/verification",
        json={"decision": "approve"},
        headers=_auth(admin_token),
    )
    assert r.status_code == 409


async def test_resubmit_then_approve_allowed(client, db_session):
    admin_token = await _make_admin(client, db_session)
    user_token = await _register(client, USER_EMAIL)
    company = await _create_company(client, user_token)
    await _submit(client, user_token, company["id"])
    await client.post(
        f"/api/v1/admin/companies/{company['id']}/verification",
        json={"decision": "reject", "reason": "уточните ИНН"},
        headers=_auth(admin_token),
    )
    # повторная отправка из rejected
    await _submit(client, user_token, company["id"])

    r = await client.post(
        f"/api/v1/admin/companies/{company['id']}/verification",
        json={"decision": "approve"},
        headers=_auth(admin_token),
    )
    assert r.status_code == 200
    assert r.json()["verification_status"] == "verified"


# ---------- Причина отклонения ----------


async def test_reject_without_reason_fails(client, db_session):
    admin_token = await _make_admin(client, db_session)
    user_token = await _register(client, USER_EMAIL)
    company = await _create_company(client, user_token)
    await _submit(client, user_token, company["id"])

    r = await client.post(
        f"/api/v1/admin/companies/{company['id']}/verification",
        json={"decision": "reject"},
        headers=_auth(admin_token),
    )
    assert r.status_code == 422


async def test_me_returns_rejection_reason(client, db_session):
    admin_token = await _make_admin(client, db_session)
    user_token = await _register(client, USER_EMAIL)
    company = await _create_company(client, user_token)
    await _submit(client, user_token, company["id"])
    await client.post(
        f"/api/v1/admin/companies/{company['id']}/verification",
        json={"decision": "reject", "reason": "реквизиты не совпадают"},
        headers=_auth(admin_token),
    )

    me = await client.get("/api/v1/auth/me", headers=_auth(user_token))
    mine = me.json()["companies"][0]
    assert mine["verification_status"] == "rejected"
    assert mine["rejection_reason"] == "реквизиты не совпадают"


async def test_resubmit_clears_rejection_reason(client, db_session):
    admin_token = await _make_admin(client, db_session)
    user_token = await _register(client, USER_EMAIL)
    company = await _create_company(client, user_token)
    await _submit(client, user_token, company["id"])
    await client.post(
        f"/api/v1/admin/companies/{company['id']}/verification",
        json={"decision": "reject", "reason": "уточните данные"},
        headers=_auth(admin_token),
    )
    await _submit(client, user_token, company["id"])

    me = await client.get("/api/v1/auth/me", headers=_auth(user_token))
    mine = me.json()["companies"][0]
    assert mine["verification_status"] == "pending_review"
    assert mine["rejection_reason"] is None


# ---------- Блокировка пользователя ----------


async def test_block_user(client, db_session):
    admin_token = await _make_admin(client, db_session)
    await _register(client, USER_EMAIL)
    user = (await db_session.execute(select(User).where(User.email == USER_EMAIL))).scalar_one()

    r = await client.post(
        f"/api/v1/admin/users/{user.id}/block", json={"blocked": True}, headers=_auth(admin_token)
    )
    assert r.status_code == 200
    assert r.json()["account_status"] == "blocked"

    login = await client.post("/api/v1/auth/login", json={"email": USER_EMAIL, "password": "secret123"})
    assert login.status_code == 401


# ---------- Guard публикации ----------


@pytest.mark.parametrize(
    "status,allowed",
    [("draft", False), ("pending_review", False), ("rejected", False), ("verified", True)],
)
async def test_verified_company_guard_for_statuses(client, db_session, status, allowed):
    token = await _register(client, USER_EMAIL)
    company = await _create_company(client, token)
    row = await _company(db_session, company["id"])
    row.verification_status = status
    await db_session.commit()

    user = await _user(db_session, USER_EMAIL)
    if allowed:
        result = await require_verified_company(uuid.UUID(company["id"]), user, db_session)
        assert result.verification_status == "verified"
    else:
        with pytest.raises(HTTPException) as exc_info:
            await require_verified_company(uuid.UUID(company["id"]), user, db_session)
        assert exc_info.value.status_code == 403


async def test_buyer_seller_guards(client, db_session):
    token = await _register(client, USER_EMAIL)
    company = await _create_company(client, token, can_buy=False, can_sell=True)
    user = await _user(db_session, USER_EMAIL)
    cid = uuid.UUID(company["id"])

    with pytest.raises(HTTPException) as exc_info:
        await require_company_buyer(cid, user, db_session)
    assert exc_info.value.status_code == 403

    membership = await require_company_seller(cid, user, db_session)
    assert membership.can_sell is True


# ---------- Фильтрация компаний администратором ----------


async def test_admin_filter_companies(client, db_session):
    admin_token = await _make_admin(client, db_session)
    user_token = await _register(client, USER_EMAIL)

    draft = await _create_company(client, user_token)

    pending = await _create_company(client, user_token)
    await _submit(client, user_token, pending["id"])

    verified = await _create_company(client, user_token)
    await _submit(client, user_token, verified["id"])
    await client.post(
        f"/api/v1/admin/companies/{verified['id']}/verification",
        json={"decision": "approve"},
        headers=_auth(admin_token),
    )

    rejected = await _create_company(client, user_token)
    await _submit(client, user_token, rejected["id"])
    await client.post(
        f"/api/v1/admin/companies/{rejected['id']}/verification",
        json={"decision": "reject", "reason": "плохие реквизиты"},
        headers=_auth(admin_token),
    )

    async def ids(status_param: str | None = None) -> set[str]:
        url = "/api/v1/admin/companies"
        if status_param is not None:
            url += f"?status={status_param}"
        r = await client.get(url, headers=_auth(admin_token))
        assert r.status_code == 200
        return {c["id"] for c in r.json()["companies"]}

    assert await ids() == {pending["id"]}  # по умолчанию pending_review
    assert await ids("pending_review") == {pending["id"]}
    assert await ids("verified") == {verified["id"]}
    assert await ids("rejected") == {rejected["id"]}
    assert await ids("draft") == {draft["id"]}


async def test_admin_filter_invalid_status(client, db_session):
    admin_token = await _make_admin(client, db_session)
    r = await client.get("/api/v1/admin/companies?status=whatever", headers=_auth(admin_token))
    assert r.status_code == 422


async def test_admin_search_and_verification_history(client, db_session):
    admin_token = await _make_admin(client, db_session)
    user_token = await _register(client, USER_EMAIL)
    company = await _create_company(client, user_token, display_name="ООО «Искомая фабрика»")
    await _submit(client, user_token, company["id"])
    await client.post(
        f"/api/v1/admin/companies/{company['id']}/verification",
        json={"decision": "reject", "reason": "нужно уточнить адрес"},
        headers=_auth(admin_token),
    )

    found = await client.get(
        "/api/v1/admin/companies?status=rejected&search=Искомая",
        headers=_auth(admin_token),
    )
    assert found.status_code == 200
    assert [item["id"] for item in found.json()["companies"]] == [company["id"]]

    history = await client.get(
        f"/api/v1/admin/companies/{company['id']}/verification-events",
        headers=_auth(admin_token),
    )
    assert history.status_code == 200
    assert history.json()[0]["reason"] == "нужно уточнить адрес"
