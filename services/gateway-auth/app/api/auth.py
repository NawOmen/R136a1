from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_db
from ..deps import get_current_user
from ..models import Company, CompanyMember, User
from ..schemas import (
    CompanyWithMembership,
    LoginIn,
    MeOut,
    MembershipOut,
    RegisterIn,
    TokenResponse,
    UserOut,
)
from ..security import create_access_token, hash_password, verify_password
from ..security_events import audit, throttle

router = APIRouter(prefix="/auth", tags=["auth"])
_dummy_hash = hash_password("not-an-account-password")


@router.post("/register", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
async def register(data: RegisterIn, request: Request, db: AsyncSession = Depends(get_db)):
    await throttle(db, request, str(data.email), "register")
    existing = await db.execute(select(User).where(User.email == data.email))
    if existing.scalar_one_or_none() is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, detail="Email уже занят")

    user = User(
        last_name=data.last_name,
        first_name=data.first_name,
        middle_name=data.middle_name,
        email=str(data.email),
        password_hash=hash_password(data.password),
        phone=data.phone,
        account_status="active",
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)

    token = create_access_token(user.id)
    return TokenResponse(user=UserOut.model_validate(user), access_token=token)


@router.post("/login", response_model=TokenResponse)
async def login(data: LoginIn, request: Request, db: AsyncSession = Depends(get_db)):
    await throttle(db, request, str(data.email), "login")
    result = await db.execute(select(User).where(User.email == data.email))
    user = result.scalar_one_or_none()
    valid = verify_password(data.password, user.password_hash if user else _dummy_hash)
    if user is None or not valid:
        await audit(db, request, "auth.login_failed")
        await db.commit()
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="Неверный email или пароль")
    if user.account_status == "blocked":
        await audit(db, request, "auth.blocked_login", actor=user.id)
        await db.commit()
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="Аккаунт заблокирован")

    await audit(db, request, "auth.login_success", actor=user.id)
    await db.commit()
    token = create_access_token(user.id)
    return TokenResponse(user=UserOut.model_validate(user), access_token=token)


@router.get("/me", response_model=MeOut)
async def me(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(Company, CompanyMember)
        .join(CompanyMember, CompanyMember.company_id == Company.id)
        .where(CompanyMember.user_id == user.id)
        .order_by(Company.created_at)
    )
    companies = [
        CompanyWithMembership(
            id=company.id,
            full_name=company.full_name,
            display_name=company.display_name,
            legal_form=company.legal_form,
            inn=company.inn,
            ogrn=company.ogrn,
            ogrnip=company.ogrnip,
            kpp=company.kpp,
            legal_address=company.legal_address,
            country=company.country,
            verification_status=company.verification_status,
            rejection_reason=company.rejection_reason,
            created_at=company.created_at,
            updated_at=company.updated_at,
            membership=MembershipOut.model_validate(member),
        )
        for company, member in result.all()
    ]
    return MeOut(user=UserOut.model_validate(user), companies=companies)
