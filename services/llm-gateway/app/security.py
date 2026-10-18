import uuid
from dataclasses import dataclass

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from .config import settings
from .database import get_db

bearer = HTTPBearer(auto_error=False)


@dataclass(frozen=True)
class CurrentUser:
    id: uuid.UUID


async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
    db: AsyncSession = Depends(get_db),
) -> CurrentUser:
    if credentials is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="Не авторизован")
    try:
        payload = jwt.decode(
            credentials.credentials,
            settings.jwt_secret,
            algorithms=[settings.jwt_algorithm],
            options={"require": ["sub", "exp"]},
        )
        user_id = uuid.UUID(str(payload["sub"]))
    except (jwt.PyJWTError, KeyError, TypeError, ValueError):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="Неверный токен")

    row = (
        await db.execute(
            text("SELECT account_status, token_version FROM auth.users WHERE id = :user_id"),
            {"user_id": user_id},
        )
    ).mappings().first()
    if row is None or row["account_status"] != "active" or payload.get("ver", 0) != row["token_version"]:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="Аккаунт недоступен")
    return CurrentUser(user_id)
