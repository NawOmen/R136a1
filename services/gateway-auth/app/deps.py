import uuid

import jwt as pyjwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .database import get_db
from .models import Company, CompanyMember, User
from .security import decode_access_token

bearer_scheme = HTTPBearer(auto_error=False)


async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    db: AsyncSession = Depends(get_db),
) -> User:
    if credentials is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="Не авторизован")
    try:
        payload = decode_access_token(credentials.credentials)
    except pyjwt.PyJWTError:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="Неверный токен")

    user_id = payload.get("sub")
    if not user_id:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="Неверный токен")

    try:
        parsed_id = uuid.UUID(str(user_id))
    except (ValueError, TypeError):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="Неверный токен")
    user = await db.get(User, parsed_id)
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="Пользователь не найден")
    if user.account_status == "blocked":
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="Аккаунт заблокирован")
    return user


async def require_admin(user: User = Depends(get_current_user)) -> User:
    if not user.is_marketplace_admin:
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="Недостаточно прав администратора")
    return user


async def get_membership(company_id: uuid.UUID, user: User, db: AsyncSession) -> CompanyMember:
    result = await db.execute(
        select(CompanyMember).where(
            CompanyMember.company_id == company_id, CompanyMember.user_id == user.id
        )
    )
    membership = result.scalar_one_or_none()
    if membership is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Вы не являетесь участником компании")
    return membership


async def require_company_admin(company_id: uuid.UUID, user: User, db: AsyncSession) -> CompanyMember:
    membership = await get_membership(company_id, user, db)
    if not membership.is_admin:
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="Требуются права администратора компании")
    return membership


async def require_verified_company(company_id: uuid.UUID, user: User, db: AsyncSession) -> Company:
    """Защита публикации: действовать может только проверенная компания.

    Будущие endpoint'ы публикации потребностей, товаров и предложений обязаны
    использовать этот guard (см. docs/api/auth-api.md).
    """
    await get_membership(company_id, user, db)
    company = await db.get(Company, company_id)
    if company is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Компания не найдена")
    if company.verification_status != "verified":
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            detail="Компания не проверена: публикация и подтверждение обязательств запрещены",
        )
    return company


async def require_company_buyer(company_id: uuid.UUID, user: User, db: AsyncSession) -> CompanyMember:
    """Действие покупателя: компания должна иметь разрешение can_buy."""
    membership = await get_membership(company_id, user, db)
    if not membership.can_buy:
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="У компании нет разрешения на покупку")
    return membership


async def require_company_seller(company_id: uuid.UUID, user: User, db: AsyncSession) -> CompanyMember:
    """Действие производителя: компания должна иметь разрешение can_sell."""
    membership = await get_membership(company_id, user, db)
    if not membership.can_sell:
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="У компании нет разрешения на продажу")
    return membership
