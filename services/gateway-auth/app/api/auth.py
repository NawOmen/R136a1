from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import IntegrityError

from ..database import get_db
from ..deps import get_current_user
from ..models import AccountAgreement, Company, CompanyMember, User
from ..config import settings
from ..schemas import (
    CompanyWithMembership,
    LoginIn,
    MeOut,
    MembershipOut,
    RegisterIn,
    RegisterV2In,
    RULES_VERSION,
    PRIVACY_VERSION,
    TokenResponse,
    UserOut,
)
from ..security import create_access_token, hash_password, verify_password
from ..security_events import audit, throttle

router = APIRouter(prefix="/auth", tags=["auth"])
v2_router = APIRouter(prefix="/auth", tags=["auth"])
_dummy_hash = hash_password("not-an-account-password")


@router.post("/register", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
async def register(data: RegisterIn, request: Request, db: AsyncSession = Depends(get_db)):
    if not settings.legacy_registration_enabled:
        raise HTTPException(410, "Откройте актуальную страницу регистрации и подтвердите правила работы.")
    return await register_account(data, request, db)


async def register_account(data: RegisterIn, request: Request, db: AsyncSession, *, acknowledged: bool = False):
    await throttle(db, request, str(data.email), "register")
    existing = await db.execute(select(User).where(User.email == data.email))
    if existing.scalar_one_or_none() is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, detail="Эта электронная почта уже используется")

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
    try:
        await db.flush()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(409, "Эта электронная почта уже используется")
    if acknowledged:
        db.add_all([AccountAgreement(user_id=user.id, document="rules", version=RULES_VERSION),
                    AccountAgreement(user_id=user.id, document="privacy", version=PRIVACY_VERSION)])
    await db.commit()
    await db.refresh(user)

    token = create_access_token(user.id, user.token_version)
    return TokenResponse(user=UserOut.model_validate(user), access_token=token)


@v2_router.post("/register", response_model=TokenResponse, status_code=201)
async def register_v2(data: RegisterV2In, request: Request, db: AsyncSession = Depends(get_db)):
    return await register_account(data, request, db, acknowledged=True)


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
    token = create_access_token(user.id, user.token_version)
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
