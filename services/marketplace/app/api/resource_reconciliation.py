"""S06.04: сверка и контролируемый ремонт ресурсного ledger.

GET показывает продавцу занятость, свежесть и расхождения.
POST выполняет только идемпотентное освобождение просроченных удержаний
и пишет запись Human Approval; молчаливых правок остатка нет.
Модели ответов определены здесь, чтобы не конфликтовать с общей схемой.
"""
import uuid

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_db
from ..deps import CurrentUser, get_current_user, require_company_admin, require_company_seller
from ..resources import reconcile_company, sweep_expired_holds
from ..trust import record_human_approval

router = APIRouter(prefix="/companies", tags=["resources"])


class ReconciliationIssue(BaseModel):
    model_config = ConfigDict(extra="allow")

    code: str
    message: str


class StockLine(BaseModel):
    model_config = ConfigDict(extra="allow")

    product_id: str
    name: str
    on_hand: int | None
    occupied: int
    free: int
    stale: bool
    stock_updated_at: str | None


class CapacityLine(BaseModel):
    model_config = ConfigDict(extra="allow")

    capacity_entry_id: str
    date: str
    available: int
    occupied: int
    free: int


class ObligationOut(BaseModel):
    model_config = ConfigDict(extra="allow")

    anchor_type: str
    anchor_id: str
    units: int
    business_exists: bool
    business_status: str | None
    business_version: int | None = None
    resources: list[str]


class ReconciliationOut(BaseModel):
    stock: list[StockLine]
    capacity: list[CapacityLine]
    issues: list[ReconciliationIssue]
    obligations: list[ObligationOut] = []


class RepairOut(BaseModel):
    swept: int
    remaining_issues: list[ReconciliationIssue]


@router.get("/{company_id}/resources/reconciliation", response_model=ReconciliationOut)
async def get_reconciliation(
    company_id: uuid.UUID,
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await require_company_seller(company_id, user, db)
    report = await reconcile_company(db, company_id=company_id)
    return report


@router.post("/{company_id}/resources/repair", response_model=RepairOut)
async def repair_resources(
    company_id: uuid.UUID,
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await require_company_seller(company_id, user, db)
    await require_company_admin(company_id, user, db)
    swept = await sweep_expired_holds(db, company_id=company_id)
    report = await reconcile_company(db, company_id=company_id)
    await record_human_approval(
        db,
        action="resource_repair",
        entity_type="company",
        entity_id=company_id,
        actor_user_id=user.id,
        actor_company_id=company_id,
        permission="company_admin",
        decision="approved",
        payload={"swept": swept, "remaining": len(report["issues"])},
        explanation="Контролируемое освобождение просроченных удержаний; остатки правились только этим действием",
    )
    await db.commit()
    return {"swept": swept, "remaining_issues": report["issues"]}
