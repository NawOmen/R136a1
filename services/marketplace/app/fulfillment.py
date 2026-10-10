"""S10 execution projection. All writes use the Need -> Deal lock in commerce.party."""
from fastapi import HTTPException
from sqlalchemy import select
from .models import Deal, DealFulfillment


async def require_legacy_execution(db, deal_id):
    deal = await db.get(Deal, deal_id)
    if (deal and deal.execution_contract == "fulfillment_v3") or await db.get(DealFulfillment, deal_id) is not None:
        raise HTTPException(409, "Исполнение ведётся по партиям. Используйте карточку исполнения сделки")
