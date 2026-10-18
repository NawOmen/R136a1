"""Revocation is serialized with account changes and admin blocking."""
import asyncio

import pytest
from fastapi import Depends
from sqlalchemy import select, text, update

from app.api import account
from app.database import get_db
from app.deps import bearer_scheme, get_current_user
from app.main import app
from app.models import SecurityEvent, User
from app.security import create_access_token, hash_password


async def make_user(db, email="session-race@demo.ru", *, administrator=False):
    user = User(email=email, first_name="Проверка", last_name="Сеанса",
                password_hash=hash_password("synthetic-password-123"), is_marketplace_admin=administrator)
    db.add(user)
    await db.commit()
    return user


def authorization(user):
    return {"Authorization": f"Bearer {create_access_token(user.id, user.token_version)}"}


@pytest.mark.parametrize("path,body", [
    ("/api/v2/auth/sessions/end", None),
    ("/api/v2/auth/logout", None),
    ("/api/v2/auth/password/change", {"current_password": "synthetic-password-123", "password": "changed-password-123"}),
])
@pytest.mark.parametrize("concurrent_action", ["revoke", "block"])
async def test_account_action_rechecks_session_after_authentication(
    client, db_session, session_factory, path, body, concurrent_action,
):
    user = await make_user(db_session)
    headers = authorization(user)

    async def checked_then_changed(credentials=Depends(bearer_scheme), db=Depends(get_db)):
        current = await get_current_user(credentials, db)
        async with session_factory() as other:
            values = {"token_version": User.token_version + 1}
            if concurrent_action == "block":
                values["account_status"] = "blocked"
            await other.execute(update(User).where(User.id == user.id).values(**values))
            await other.commit()
        return current

    # Deterministically commit the competing transaction after the normal auth
    # check and before the endpoint reads the locked row.
    app.dependency_overrides[get_current_user] = checked_then_changed
    try:
        response = await client.post(path, headers=headers, json=body)
    finally:
        app.dependency_overrides.pop(get_current_user, None)
    assert response.status_code == 401
    await db_session.refresh(user)
    assert user.token_version == 1
    assert user.account_status == ("blocked" if concurrent_action == "block" else "active")
    assert await db_session.scalar(select(SecurityEvent.id)) is None


async def wait_for_blocked_transaction(session_factory, task):
    # Verify a real PostgreSQL lock wait rather than relying on a sleep to order
    # two HTTP requests. Each test has its own disposable database.
    async with asyncio.timeout(5):
        while not task.done():
            async with session_factory() as observer:
                waiting = await observer.scalar(text("""
                    SELECT EXISTS (SELECT 1 FROM pg_stat_activity
                    WHERE datname = current_database() AND wait_event_type = 'Lock')
                """))
            if waiting:
                return
            await asyncio.sleep(0.01)
        await task
        pytest.fail("Competing account mutation did not wait for the user row lock")


async def test_admin_block_preserves_concurrent_session_version(client, db_session, session_factory, monkeypatch):
    user = await make_user(db_session)
    admin = await make_user(db_session, "session-admin@demo.ru", administrator=True)
    headers, admin_headers = authorization(user), authorization(admin)
    locked = asyncio.Event()
    release = asyncio.Event()
    original_audit = account.audit

    async def pause_before_commit(db, request, event, **kwargs):
        if event == "auth.sessions_ended":
            locked.set()
            await release.wait()
        await original_audit(db, request, event, **kwargs)

    monkeypatch.setattr(account, "audit", pause_before_commit)
    change = asyncio.create_task(client.post("/api/v2/auth/sessions/end", headers=headers))
    block = None
    try:
        await asyncio.wait_for(locked.wait(), timeout=5)
        block = asyncio.create_task(client.post(f"/api/v1/admin/users/{user.id}/block", headers=admin_headers, json={"blocked": True}))
        await wait_for_blocked_transaction(session_factory, block)
        release.set()
        changed, blocked = await asyncio.wait_for(asyncio.gather(change, block), timeout=5)
        assert changed.status_code == blocked.status_code == 200
        replacement = {"Authorization": f"Bearer {changed.json()['access_token']}"}
        await db_session.refresh(user)
        assert user.token_version == 2 and user.account_status == "blocked"
        assert (await client.get("/api/v1/auth/me", headers=replacement)).status_code == 401
        assert (await client.post(f"/api/v1/admin/users/{user.id}/block", headers=admin_headers, json={"blocked": False})).status_code == 200
        assert (await client.get("/api/v1/auth/me", headers=replacement)).status_code == 401
        assert (await client.get("/api/v1/auth/me", headers=headers)).status_code == 401
        assert (await client.post("/api/v1/auth/login", json={"email": user.email, "password": "synthetic-password-123"})).status_code == 200
    finally:
        release.set()
        for task in (change, block):
            if task is not None and not task.done():
                task.cancel()
        await asyncio.gather(*(task for task in (change, block) if task is not None), return_exceptions=True)


async def test_competing_old_sessions_cannot_issue_two_replacements(client, db_session, session_factory, monkeypatch):
    user = await make_user(db_session)
    headers = authorization(user)
    locked, release = asyncio.Event(), asyncio.Event()
    original_audit = account.audit

    async def pause_before_commit(db, request, event, **kwargs):
        if event == "auth.sessions_ended":
            locked.set()
            await release.wait()
        await original_audit(db, request, event, **kwargs)

    monkeypatch.setattr(account, "audit", pause_before_commit)
    first = asyncio.create_task(client.post("/api/v2/auth/sessions/end", headers=headers))
    second = None
    try:
        await asyncio.wait_for(locked.wait(), timeout=5)
        second = asyncio.create_task(client.post("/api/v2/auth/sessions/end", headers=headers))
        await wait_for_blocked_transaction(session_factory, second)
        release.set()
        accepted, rejected = await asyncio.wait_for(asyncio.gather(first, second), timeout=5)
        assert accepted.status_code == 200
        assert rejected.status_code == 401
        await db_session.refresh(user)
        assert user.token_version == 1
        replacement = {"Authorization": f"Bearer {accepted.json()['access_token']}"}
        assert (await client.get("/api/v1/auth/me", headers=replacement)).status_code == 200
        assert (await client.get("/api/v1/auth/me", headers=headers)).status_code == 401
    finally:
        release.set()
        for task in (first, second):
            if task is not None and not task.done():
                task.cancel()
        await asyncio.gather(*(task for task in (first, second) if task is not None), return_exceptions=True)
