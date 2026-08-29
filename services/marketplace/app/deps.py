import uuid
from dataclasses import dataclass

import jwt as pyjwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from .database import get_db
from .security import decode_access_token

bearer_scheme = HTTPBearer(auto_error=False)


@dataclass
class CurrentUser:
    id: uuid.UUID


async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    db: AsyncSession = Depends(get_db),
) -> CurrentUser:
    if credentials is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="Не авторизован")
    try:
        payload = decode_access_token(credentials.credentials)
    except pyjwt.PyJWTError:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="Неверный токен")

    user_id_raw = payload.get("sub")
    if not user_id_raw:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="Неверный токен")
    try:
        user_id = uuid.UUID(str(user_id_raw))
    except (TypeError, ValueError):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="Неверный токен")

    result = await db.execute(
        text("SELECT account_status FROM auth.users WHERE id = :uid"), {"uid": user_id}
    )
    row = result.mappings().first()
    if row is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="Пользователь не найден")
    if row["account_status"] == "blocked":
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="Аккаунт заблокирован")
    return CurrentUser(id=user_id)


async def get_membership(db: AsyncSession, company_id: uuid.UUID, user_id: uuid.UUID) -> dict | None:
    result = await db.execute(
        text(
            "SELECT can_buy, can_sell, is_admin FROM auth.company_members "
            "WHERE company_id = :cid AND user_id = :uid"
        ),
        {"cid": company_id, "uid": user_id},
    )
    row = result.mappings().first()
    return dict(row) if row else None


async def get_company(db: AsyncSession, company_id: uuid.UUID) -> dict | None:
    result = await db.execute(
        text("SELECT id, verification_status FROM auth.companies WHERE id = :cid"),
        {"cid": company_id},
    )
    row = result.mappings().first()
    return dict(row) if row else None


async def require_membership(company_id: uuid.UUID, user: CurrentUser, db: AsyncSession) -> dict:
    membership = await get_membership(db, company_id, user.id)
    if membership is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Вы не являетесь участником компании")
    return membership


async def require_verified_company(company_id: uuid.UUID, user: CurrentUser, db: AsyncSession) -> dict:
    await require_membership(company_id, user, db)
    company = await get_company(db, company_id)
    if company is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Компания не найдена")
    if company["verification_status"] != "verified":
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            detail="Компания не проверена: публикация и сделки запрещены",
        )
    return company


async def require_company_buyer(company_id: uuid.UUID, user: CurrentUser, db: AsyncSession) -> dict:
    membership = await require_membership(company_id, user, db)
    if not membership["can_buy"]:
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="У компании нет разрешения на покупку")
    return membership


async def require_company_seller(company_id: uuid.UUID, user: CurrentUser, db: AsyncSession) -> dict:
    membership = await require_membership(company_id, user, db)
    if not membership["can_sell"]:
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="У компании нет разрешения на продажу")
    return membership


async def require_company_admin(company_id: uuid.UUID, user: CurrentUser, db: AsyncSession) -> dict:
    membership = await require_membership(company_id, user, db)
    if not membership["is_admin"]:
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="Требуются права администратора компании")
    return membership


async def notify(db: AsyncSession, user_id: uuid.UUID, message: str, type_: str = "info") -> None:
    """Создать внутреннее уведомление для пользователя."""
    from .models import Notification

    db.add(Notification(user_id=user_id, message=message, type=type_))
