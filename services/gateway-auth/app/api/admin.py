import uuid
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_db
from ..deps import require_admin
from ..models import AccountAgreement, Company, CompanyVerificationEvent, SecurityEvent, User
from ..security_events import audit
from ..schemas import AdminCompaniesOut, AdminUsersOut, AdminVerificationIn, AdminVerificationV2In, BlockIn, CompanyOut, UserOut, VerificationEventOut

router = APIRouter(prefix="/admin", tags=["admin"])


@router.get("/users", response_model=AdminUsersOut)
async def list_users(
    search: str | None = Query(default=None, min_length=2, max_length=120),
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    del admin
    query = select(User).order_by(User.created_at.desc())
    if search:
        value = f"%{search.strip()}%"
        query = query.where(or_(User.email.ilike(value), User.first_name.ilike(value), User.last_name.ilike(value)))
    result = await db.execute(query)
    return AdminUsersOut(users=[UserOut.model_validate(item) for item in result.scalars().all()])


@router.get("/companies", response_model=AdminCompaniesOut)
async def list_companies(
    status_filter: Literal["draft", "pending_review", "verified", "rejected"] | None = Query(
        "pending_review", alias="status"
    ),
    search: str | None = Query(default=None, min_length=2, max_length=120),
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    query = select(Company).order_by(Company.created_at)
    if status_filter:
        query = query.where(Company.verification_status == status_filter)
    if search:
        value = f"%{search.strip()}%"
        query = query.where(
            or_(Company.display_name.ilike(value), Company.full_name.ilike(value), Company.inn.ilike(value))
        )
    result = await db.execute(query)
    return AdminCompaniesOut(companies=[CompanyOut.model_validate(c) for c in result.scalars().all()])


@router.get("/companies/{company_id}/verification-events", response_model=list[VerificationEventOut])
async def company_verification_history(
    company_id: uuid.UUID,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    if await db.get(Company, company_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Компания не найдена")
    result = await db.execute(
        select(CompanyVerificationEvent)
        .where(CompanyVerificationEvent.company_id == company_id)
        .order_by(CompanyVerificationEvent.created_at.desc())
    )
    return result.scalars().all()


@router.post("/companies/{company_id}/verification", response_model=CompanyOut)
async def verify_company(
    company_id: uuid.UUID,
    data: AdminVerificationIn,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    company = await db.scalar(select(Company).where(Company.id == company_id).with_for_update().execution_options(populate_existing=True))
    if company is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Компания не найдена")

    # Допустимы только переходы pending_review -> verified / rejected.
    if company.verification_status != "pending_review":
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail="Решение можно принять только для компании в статусе pending_review",
        )

    from_status = company.verification_status
    to_status = "verified" if data.decision == "approve" else "rejected"
    company.verification_status = to_status
    company.rejection_reason = (data.reason or "").strip() if data.decision == "reject" else None

    event = CompanyVerificationEvent(
        company_id=company.id,
        from_status=from_status,
        to_status=to_status,
        performed_by_user_id=admin.id,
        reason=data.reason,
    )
    db.add(event)
    await db.commit()
    await db.refresh(company)
    return company


@router.post("/users/{user_id}/block", response_model=UserOut)
async def block_user(
    user_id: uuid.UUID,
    data: BlockIn,
    request: Request,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    user = await db.get(User, user_id)
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Пользователь не найден")

    if user.id == admin.id and data.blocked:
        raise HTTPException(409, "Нельзя заблокировать собственный аккаунт администратора.")
    previous = user.account_status
    user.account_status = "blocked" if data.blocked else "active"
    if data.blocked:
        user.token_version += 1
    await audit(db, request, "admin.account_status", actor=admin.id, target=user.id,
                before=previous, after=user.account_status,
                reason=data.reason or "Ручное решение администратора")
    await db.commit()
    await db.refresh(user)
    return user


@router.get("/security-events")
async def security_events(alerts_only: bool = False, admin: User = Depends(require_admin), db: AsyncSession = Depends(get_db)):
    query = select(SecurityEvent)
    if alerts_only:
        query = query.where(SecurityEvent.event == "auth.rate_limited")
    rows = (await db.execute(query.order_by(SecurityEvent.created_at.desc()).limit(100))).scalars().all()
    return [{"event": row.event, "created_at": row.created_at, "actor_id": row.actor_id,
             "target_id": row.target_id, "before": row.before_value, "after": row.after_value,
             "correlation_id": row.correlation_id, "reason": row.reason} for row in rows]


class EditorRoleIn(BaseModel):
    model_config=ConfigDict(str_strip_whitespace=True)
    enabled: bool
    reason: str = Field(min_length=3,max_length=500)


@router.put("/users/{user_id}/category-editor", response_model=UserOut)
async def appoint_category_editor(user_id: uuid.UUID, data: EditorRoleIn, request: Request,
    admin: User=Depends(require_admin),db: AsyncSession=Depends(get_db)):
    user=await db.get(User,user_id)
    if user is None:raise HTTPException(404,"Пользователь не найден")
    previous=user.is_category_editor
    user.is_category_editor=data.enabled
    await audit(db,request,"admin.category_editor_role",actor=admin.id,target=user.id,
                before=str(previous),after=str(user.is_category_editor),reason=data.reason)
    await db.commit()
    await db.refresh(user)
    return user


v2_router = APIRouter(prefix="/admin", tags=["admin"])

@v2_router.post("/companies/{company_id}/verification", response_model=CompanyOut)
async def verify_company_v2(company_id: uuid.UUID, data: AdminVerificationV2In,
                            admin: User = Depends(require_admin), db: AsyncSession = Depends(get_db)):
    company = await db.scalar(select(Company).where(Company.id == company_id).with_for_update().execution_options(populate_existing=True))
    if company and company.verification_status != "pending_review":
        event = await db.scalar(select(CompanyVerificationEvent).where(CompanyVerificationEvent.company_id == company_id)
                                .order_by(CompanyVerificationEvent.created_at.desc()).limit(1))
        target = "verified" if data.decision == "approve" else "rejected"
        if (event and event.to_status == target and company.verification_status == target
                and event.performed_by_user_id == admin.id and event.reason == data.reason):
            return company
    return await verify_company(company_id, data, admin, db)


@router.get("/users/{user_id}/agreements")
async def user_agreements(user_id: uuid.UUID, admin: User = Depends(require_admin), db: AsyncSession = Depends(get_db)):
    rows = (await db.scalars(select(AccountAgreement).where(AccountAgreement.user_id == user_id).order_by(AccountAgreement.accepted_at))).all()
    return [{"document": row.document, "version": row.version, "accepted_at": row.accepted_at} for row in rows]
