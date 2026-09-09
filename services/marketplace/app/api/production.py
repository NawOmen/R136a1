import uuid

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_db
from ..deps import CurrentUser, get_current_user, require_company_admin, require_company_seller
from ..models import CapabilityPassport, ProductionProfile
from ..schemas import CapabilityPassportIn, CapabilityPassportOut, ProductionProfileIn, ProductionProfileOut

router = APIRouter(prefix="/companies", tags=["production"])


@router.get("/{company_id}/production-profile", response_model=ProductionProfileOut)
async def get_production_profile(
    company_id: uuid.UUID,
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await require_company_seller(company_id, user, db)
    profile = await db.get(ProductionProfile, company_id)
    if profile is None:
        return ProductionProfileOut(company_id=company_id, production_site_address=None, region=None, about=None)
    return profile


@router.put("/{company_id}/production-profile", response_model=ProductionProfileOut)
async def upsert_production_profile(
    company_id: uuid.UUID,
    data: ProductionProfileIn,
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await require_company_seller(company_id, user, db)
    await require_company_admin(company_id, user, db)
    profile = await db.get(ProductionProfile, company_id)
    if profile is None:
        profile = ProductionProfile(company_id=company_id, **data.model_dump())
        db.add(profile)
    else:
        for field, value in data.model_dump().items():
            setattr(profile, field, value)
    await db.commit()
    await db.refresh(profile)
    return profile


@router.get("/{company_id}/capability-passport", response_model=CapabilityPassportOut)
async def get_passport(
    company_id: uuid.UUID,
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await require_company_seller(company_id, user, db)
    passport = await db.get(CapabilityPassport, company_id)
    if passport is None:
        return CapabilityPassportOut(
            company_id=company_id,
            technologies=[], equipment=[], materials=[], size_ranges={}, tolerances=None,
            certifications=[], min_order_units=None, max_order_units=None,
            delivery_regions=[], completed_order_types=[],
        )
    return passport


@router.put("/{company_id}/capability-passport", response_model=CapabilityPassportOut)
async def upsert_passport(
    company_id: uuid.UUID,
    data: CapabilityPassportIn,
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await require_company_seller(company_id, user, db)
    await require_company_admin(company_id, user, db)
    passport = await db.get(CapabilityPassport, company_id)
    if passport is None:
        passport = CapabilityPassport(company_id=company_id, **data.model_dump())
        db.add(passport)
    else:
        for field, value in data.model_dump().items():
            # Старые клиенты API v1 не должны стирать расширенный паспорт.
            if field == "details" and field not in data.model_fields_set:
                continue
            setattr(passport, field, value)
    await db.commit()
    await db.refresh(passport)
    return passport
