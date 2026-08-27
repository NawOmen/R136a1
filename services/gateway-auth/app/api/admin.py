import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_db
from ..deps import require_admin
from ..models import Company, CompanyVerificationEvent, User
from ..schemas import AdminCompaniesOut, AdminVerificationIn, BlockIn, CompanyOut, UserOut

router = APIRouter(prefix="/admin", tags=["admin"])


@router.get("/companies", response_model=AdminCompaniesOut)
async def list_companies(
    status_filter: str = "pending_review",
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Company).where(Company.verification_status == status_filter).order_by(Company.created_at)
    )
    return AdminCompaniesOut(companies=[CompanyOut.model_validate(c) for c in result.scalars().all()])


@router.post("/companies/{company_id}/verification", response_model=CompanyOut)
async def verify_company(
    company_id: uuid.UUID,
    data: AdminVerificationIn,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    company = await db.get(Company, company_id)
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
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    user = await db.get(User, user_id)
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Пользователь не найден")

    user.account_status = "blocked" if data.blocked else "active"
    await db.commit()
    await db.refresh(user)
    return user
