import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_db
from ..deps import get_current_user, require_company_admin
from ..models import Company, CompanyMember, User
from ..schemas import (
    CompanyIn,
    CompanyOut,
    CompanyPatch,
    CompanyWithMembership,
    MembershipOut,
    MembershipPatch,
)

router = APIRouter(prefix="/companies", tags=["companies"])


@router.post("", response_model=CompanyWithMembership, status_code=status.HTTP_201_CREATED)
async def create_company(
    data: CompanyIn, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
):
    company = Company(
        full_name=data.full_name,
        display_name=data.display_name,
        legal_form=data.legal_form,
        inn=data.inn,
        ogrn=data.ogrn,
        ogrnip=data.ogrnip,
        kpp=data.kpp,
        legal_address=data.legal_address,
        country="RU",
        verification_status="draft",
    )
    db.add(company)
    await db.flush()

    member = CompanyMember(
        user_id=user.id, company_id=company.id, can_buy=data.can_buy, can_sell=data.can_sell, is_admin=True
    )
    db.add(member)
    await db.commit()
    await db.refresh(company)

    return CompanyWithMembership(
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
        rejection_reason=None,
        membership=MembershipOut(can_buy=data.can_buy, can_sell=data.can_sell, is_admin=True),
    )


@router.patch("/{company_id}", response_model=CompanyOut)
async def update_company(
    company_id: uuid.UUID,
    data: CompanyPatch,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await require_company_admin(company_id, user, db)
    company = await db.get(Company, company_id)
    if company is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Компания не найдена")
    if company.verification_status not in ("draft", "rejected"):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="Профиль можно менять только до проверки")

    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(company, field, value)

    await db.commit()
    await db.refresh(company)
    return company


@router.post("/{company_id}/submit-review", response_model=CompanyOut)
async def submit_review(
    company_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await require_company_admin(company_id, user, db)
    company = await db.get(Company, company_id)
    if company is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Компания не найдена")
    if company.verification_status not in ("draft", "rejected"):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="Компания уже на проверке или проверена")

    company.verification_status = "pending_review"
    company.rejection_reason = None
    await db.commit()
    await db.refresh(company)
    return company


@router.patch("/{company_id}/membership", response_model=MembershipOut)
async def update_membership(
    company_id: uuid.UUID,
    data: MembershipPatch,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if not data.can_buy and not data.can_sell:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            detail="Хотя бы одно разрешение («Покупаю» или «Продаю») должно быть включено",
        )
    membership = await require_company_admin(company_id, user, db)
    membership.can_buy = data.can_buy
    membership.can_sell = data.can_sell
    await db.commit()
    await db.refresh(membership)
    return membership
