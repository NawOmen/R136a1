"""Shared database rate limits and bounded, secret-free security audit."""
import hashlib
import hmac
import json
import logging
import uuid
from datetime import datetime, timezone

from fastapi import HTTPException, Request
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from .config import settings

logger = logging.getLogger("porukam.security")


def fingerprint(value: str) -> str:
    return hmac.new(settings.jwt_secret.encode(), value.encode(), hashlib.sha256).hexdigest()


def correlation(request: Request) -> str:
    if not hasattr(request.state, "security_id"):
        request.state.security_id = str(uuid.uuid4())
    return request.state.security_id


async def audit(db: AsyncSession, request: Request, event: str, *,
                actor: uuid.UUID | None = None, target: uuid.UUID | None = None,
                before: str | None = None, after: str | None = None, reason: str | None = None) -> None:
    # No request bodies, email addresses, passwords, headers or exception strings.
    await db.execute(text("""
        INSERT INTO auth.security_events
            (id, event, actor_id, target_id, before_value, after_value, correlation_id, reason)
        VALUES (:id, :event, :actor, :target, :before, :after, :correlation, :reason)
    """), dict(id=uuid.uuid4(), event=event, actor=actor, target=target,
               before=before, after=after, correlation=correlation(request), reason=reason))


async def throttle(db: AsyncSession, request: Request, account: str, action: str) -> None:
    # Direct peer only: never trust client-supplied X-Forwarded-For.
    # Edge proxy has its own per-IP limiter; behind it this is also a global ceiling.
    peer = request.client.host if request.client else "unknown"
    await db.execute(text("DELETE FROM auth.login_limits WHERE bucket < floor(extract(epoch FROM now()) / 60) - 2"))
    await db.execute(text("DELETE FROM auth.security_events WHERE created_at < now() - interval '30 days'"))
    exceeded = False
    for kind, value, limit in (("peer", peer, 60), ("account", account.casefold(), 10)):
        count = (await db.execute(text("""
            INSERT INTO auth.login_limits (key, bucket, attempts)
            VALUES (:key, floor(extract(epoch FROM now()) / 60), 1)
            ON CONFLICT (key, bucket) DO UPDATE
                SET attempts = LEAST(auth.login_limits.attempts + 1, 1000000)
            RETURNING attempts
        """), {"key": fingerprint(action + ":" + kind + ":" + value)})).scalar_one()
        exceeded |= count > limit
    if exceeded:
        await audit(db, request, "auth.rate_limited")
    # Persist attempts even when authentication subsequently raises HTTPException.
    await db.commit()
    if exceeded:
        logger.warning(json.dumps({"event": "security.alert", "rule": "auth.rate_limited",
                                   "time": datetime.now(timezone.utc).isoformat(),
                                   "correlation_id": correlation(request)}))
        raise HTTPException(429, "Слишком много попыток. Повторите через минуту.",
                            headers={"Retry-After": "60"})
