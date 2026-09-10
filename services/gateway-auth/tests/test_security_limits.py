import asyncio
import uuid
from datetime import datetime, timedelta, timezone

import jwt
from sqlalchemy import text

from app.config import settings
from app.models import User
from sqlalchemy import select


async def test_failed_login_limit_is_shared_and_audited(client, db_session):
    payload = {"email": "missing@demo.ru", "password": "secret123"}
    responses = await asyncio.gather(*[
        client.post("/api/v1/auth/login", json=payload) for _ in range(12)
    ])
    assert sorted(r.status_code for r in responses) == [401] * 10 + [429] * 2
    limited = next(r for r in responses if r.status_code == 429)
    assert limited.headers["Retry-After"] == "60"
    rows = (await db_session.execute(text("SELECT event, correlation_id FROM auth.security_events"))).mappings().all()
    assert sum(row["event"] == "auth.login_failed" for row in rows) == 10
    assert sum(row["event"] == "auth.rate_limited" for row in rows) == 2
    assert all(uuid.UUID(row["correlation_id"]) for row in rows)
    await db_session.execute(text("DELETE FROM auth.login_limits"))
    await db_session.commit()
    assert (await client.post("/api/v1/auth/login", json=payload)).status_code == 401


async def test_forged_forwarded_header_does_not_bypass_limit(client):
    for number in range(11):
        response = await client.post("/api/v1/auth/login",
            headers={"X-Forwarded-For": f"10.0.0.{number}"},
            json={"email": "missing@demo.ru", "password": "secret123"})
    assert response.status_code == 429


async def test_malformed_subject_is_401_not_500(client):
    token = jwt.encode({"sub": "not-a-uuid", "exp": datetime.now(timezone.utc) + timedelta(minutes=1)},
                       settings.jwt_secret, algorithm="HS256")
    assert (await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})).status_code == 401


async def test_security_events_require_admin(client):
    assert (await client.get("/api/v1/admin/security-events")).status_code == 401


async def test_admin_change_and_alert_channel(client, db_session):
    async def register(email):
        response = await client.post("/api/v1/auth/register", json={
            "last_name": "Тест", "first_name": "Тест", "email": email, "password": "secret123"})
        assert response.status_code == 201
        return response.json()
    admin = await register("admin-security@demo.ru")
    buyer = await register("buyer-security@demo.ru")
    ordinary = {"Authorization": "Bearer " + buyer["access_token"]}
    assert (await client.get("/api/v1/admin/security-events", headers=ordinary)).status_code == 403
    user = (await db_session.execute(select(User).where(User.id == uuid.UUID(admin["user"]["id"])))).scalar_one()
    user.is_marketplace_admin = True
    await db_session.commit()
    headers = {"Authorization": "Bearer " + admin["access_token"]}
    response = await client.post(f"/api/v1/admin/users/{buyer['user']['id']}/block",
                                 json={"blocked": True, "reason": "Демонстрационная проверка"}, headers=headers)
    assert response.status_code == 200
    events = (await client.get("/api/v1/admin/security-events", headers=headers)).json()
    event = next(item for item in events if item["event"] == "admin.account_status")
    assert event["before"] == "active" and event["after"] == "blocked"
    assert event["actor_id"] == admin["user"]["id"]
    assert event["reason"] == "Демонстрационная проверка"
    assert (await client.get("/api/v1/auth/me", headers=ordinary)).status_code == 401
    for _ in range(11):
        await client.post("/api/v1/auth/login", json={"email": "missing@demo.ru", "password": "wrong"})
    alerts = (await client.get("/api/v1/admin/security-events?alerts_only=true", headers=headers)).json()
    assert len(alerts) == 1 and alerts[0]["event"] == "auth.rate_limited"
