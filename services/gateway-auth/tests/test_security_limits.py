import time
import uuid
from datetime import datetime, timedelta, timezone

import jwt
from sqlalchemy import select, text

from app.config import settings
from app.models import User
from app.security_events import fingerprint


def _bucket() -> int:
    return int(time.time() // 60)


async def _pin_account_limit(db_session, email: str, action: str = "login", attempts: int = 10) -> None:
    """Заполнить счётчик текущей минуты, чтобы лимит срабатывал детерминированно.

    Лимиты хранятся в минутных бакетах, поэтому без предзаполнения тест зависит от
    момента запуска: последовательные запросы могут разнестись по границе минуты,
    счётчик обнулится и 429 не наступит.
    """
    await db_session.execute(
        text(
            "INSERT INTO auth.login_limits (key, bucket, attempts) VALUES (:key, :bucket, :attempts) "
            "ON CONFLICT (key, bucket) DO UPDATE SET attempts = EXCLUDED.attempts"
        ),
        {"key": fingerprint(f"{action}:account:{email.casefold()}"), "bucket": _bucket(), "attempts": attempts},
    )
    await db_session.commit()


async def _limited_login(client, db_session, email: str = "missing@demo.ru", headers: dict | None = None):
    """Вход, который обязан упереться в лимит; повтор — только на смене бакета."""
    response = None
    for _ in range(3):
        await _pin_account_limit(db_session, email)
        response = await client.post(
            "/api/v1/auth/login", json={"email": email, "password": "secret123"}, headers=headers
        )
        if response.status_code == 429:
            return response
    return response


async def test_failed_login_limit_is_shared_and_audited(client, db_session):
    payload = {"email": "missing@demo.ru", "password": "secret123"}
    limited = await _limited_login(client, db_session)
    assert limited.status_code == 429
    assert limited.headers["Retry-After"] == "60"

    # Лимит по аккаунту общий: подставной X-Forwarded-For не создаёт отдельный счётчик.
    other_peer = await client.post(
        "/api/v1/auth/login", headers={"X-Forwarded-For": "10.9.9.9"}, json=payload
    )
    assert other_peer.status_code == 429

    rows = (await db_session.execute(text("SELECT event, correlation_id FROM auth.security_events"))).mappings().all()
    assert sum(row["event"] == "auth.rate_limited" for row in rows) >= 1
    assert all(uuid.UUID(row["correlation_id"]) for row in rows)

    # После очистки счётчиков обычная неудачная попытка снова обрабатывается и логируется.
    await db_session.execute(text("DELETE FROM auth.login_limits"))
    await db_session.commit()
    assert (await client.post("/api/v1/auth/login", json=payload)).status_code == 401
    events = (await db_session.execute(text("SELECT event FROM auth.security_events"))).scalars().all()
    assert "auth.login_failed" in events


async def test_forged_forwarded_header_does_not_bypass_limit(client, db_session):
    response = await _limited_login(client, db_session, headers={"X-Forwarded-For": "10.0.0.1"})
    assert response.status_code == 429
    again = await client.post(
        "/api/v1/auth/login",
        headers={"X-Forwarded-For": "10.0.0.2"},
        json={"email": "missing@demo.ru", "password": "secret123"},
    )
    assert again.status_code == 429


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

    limited = await _limited_login(client, db_session)
    assert limited.status_code == 429
    alerts = (await client.get("/api/v1/admin/security-events?alerts_only=true", headers=headers)).json()
    assert len(alerts) == 1 and alerts[0]["event"] == "auth.rate_limited"
