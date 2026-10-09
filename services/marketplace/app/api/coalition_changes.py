"""S08.04: изменение состава подтверждённой группы.

Старая группа не удаляется; история и действующее обязательство сохраняются
до допустимого перехода. Выход крупного участника ниже MOQ аннулирует старые
условия, а не исполненную историю. Повтор по тому же ключу не создаёт вторую
группу и возвращает тот же запрос.
"""
import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_db
from ..deps import (
    CurrentUser,
    get_current_user,
    require_company_admin,
    require_company_buyer,
    require_company_seller,
)
from ..models import (
    Coalition,
    CoalitionChangeRequest,
    CoalitionMember,
    GroupOffer,
    Need,
    ParticipantOrder,
)
from ..resources import release, reserve
from ..trust import append_audit_event

router = APIRouter(tags=["coalition-changes"])


class ChangeRequestIn(BaseModel):
    company_id: uuid.UUID
    reason: str = Field(min_length=3, max_length=1000)
    proposed_units: dict[str, int]
    resource_policy: str = Field(default="release_and_rereserve")
    idempotency_key: uuid.UUID


class ChangeDecisionIn(BaseModel):
    company_id: uuid.UUID
    approved: bool
    expected_revision: int = Field(ge=1)


class ChangeRequestOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    coalition_id: uuid.UUID
    requested_by_company_id: uuid.UUID
    reason: str
    proposed_units: dict
    resource_policy: str
    status: str
    version_from: int
    version_to: int | None


async def _locked_coalition(db: AsyncSession, coalition_id: uuid.UUID) -> Coalition | None:
    return (
        await db.execute(
            select(Coalition)
            .where(Coalition.id == coalition_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    ).scalar_one_or_none()


@router.post("/coalitions/{coalition_id}/change-requests", response_model=ChangeRequestOut, status_code=201)
async def create_change_request(
    coalition_id: uuid.UUID,
    data: ChangeRequestIn,
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    coalition = await _locked_coalition(db, coalition_id)
    if coalition is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Коалиция не найдена")
    if coalition.status != "confirmed":
        raise HTTPException(409, "Изменение состава доступно только подтверждённой группе")
    members = (
        await db.execute(select(CoalitionMember).where(CoalitionMember.coalition_id == coalition.id))
    ).scalars().all()
    member_need_ids = {str(item.need_id) for item in members}
    if not any(item.buyer_company_id == data.company_id for item in members):
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="Компания не является участником коалиции")
    await require_company_buyer(data.company_id, user, db)
    await require_company_admin(data.company_id, user, db)
    if set(data.proposed_units) - member_need_ids:
        raise HTTPException(422, "Изменение касается только текущих участников группы")
    if any(units < 0 for units in data.proposed_units.values()):
        raise HTTPException(422, "Объём участника не может быть отрицательным")
    if data.resource_policy not in {"release_and_rereserve"}:
        raise HTTPException(422, "Неизвестная политика ресурса")
    existing = (
        await db.execute(
            select(CoalitionChangeRequest).where(
                CoalitionChangeRequest.coalition_id == coalition.id,
                CoalitionChangeRequest.idempotency_key == data.idempotency_key,
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        if (
            existing.requested_by_company_id != data.company_id
            or existing.reason != data.reason
            or {str(key): value for key, value in existing.proposed_units.items()} !=
            {str(key): value for key, value in data.proposed_units.items()}
        ):
            raise HTTPException(409, "Ключ запроса уже использован для других данных")
        return existing
    request = CoalitionChangeRequest(
        coalition_id=coalition.id,
        requested_by_company_id=data.company_id,
        requested_by_user_id=user.id,
        reason=data.reason,
        proposed_units={str(key): value for key, value in data.proposed_units.items()},
        resource_policy=data.resource_policy,
        idempotency_key=data.idempotency_key,
        version_from=coalition.version,
    )
    db.add(request)
    await db.commit()
    return request


@router.post("/coalition-changes/{request_id}/decision", response_model=ChangeRequestOut)
async def decide_change_request(
    request_id: uuid.UUID,
    data: ChangeDecisionIn,
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    request = await db.get(CoalitionChangeRequest, request_id)
    if request is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Запрос изменения не найден")
    coalition = await _locked_coalition(db, request.coalition_id)
    if coalition is None or coalition.status != "confirmed":
        raise HTTPException(409, "Группа уже не подтверждена: запрос изменения не применим")
    if request.status != "pending":
        return request
    if coalition.version != request.version_from or coalition.version != data.expected_revision:
        raise HTTPException(409, "Условия группы изменились. Запросите изменение заново")
    if data.company_id != coalition.producer_company_id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="Изменение подтверждает производитель")
    await require_company_seller(data.company_id, user, db)
    await require_company_admin(data.company_id, user, db)
    request.decisions = [
        *(request.decisions or []),
        {"company_id": str(data.company_id), "approved": data.approved},
    ]
    if not data.approved:
        request.status = "rejected"
        await db.commit()
        return request
    members = (
        await db.execute(
            select(CoalitionMember)
            .where(CoalitionMember.coalition_id == coalition.id)
            .order_by(CoalitionMember.id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    ).scalars().all()
    group_offer = (
        await db.execute(
            select(GroupOffer)
            .where(GroupOffer.coalition_id == coalition.id)
            .order_by(GroupOffer.created_at.desc())
            .execution_options(populate_existing=True)
        )
    ).scalars().first()
    remaining = {str(item.need_id): item.units for item in members}
    remaining.update({str(key): value for key, value in request.proposed_units.items()})
    remaining_total = sum(remaining.values())
    moq = group_offer.min_total_units if group_offer else None
    if moq and remaining_total < moq:
        request.status = "applied_annulled"
        request.version_to = coalition.version + 1
        coalition.status = "recalculation_required"
        coalition.version += 1
        await release(db, company_id=group_offer.company_id, anchor_type="coalition", anchor_id=coalition.id)
        await db.execute(delete(ParticipantOrder).where(ParticipantOrder.coalition_id == coalition.id))
        for item in members:
            need = await db.get(Need, item.need_id)
            need.status = "waiting_for_match"
            need.no_match_reason = (
                "Состав группы изменился ниже MOQ: старые условия аннулированы, выполняется повторный подбор"
            )
        await append_audit_event(
            db, event_type="coalition_change_annulled", entity_type="coalition", entity_id=coalition.id,
            actor_user_id=user.id, actor_company_id=data.company_id,
            source_refs=[{"type": "coalition", "id": str(coalition.id)}],
            explanation="Выход участника опустил группу ниже MOQ: старые условия аннулированы без обязательств.",
            payload={"change_request_id": str(request.id), "remaining_total": remaining_total, "moq": moq},
        )
        await db.commit()
        return request
    request.status = "applied"
    request.version_to = coalition.version + 1
    coalition.version += 1
    live_needs = {}
    for item in members:
        need = await db.get(Need, item.need_id)
        live_needs[item.need_id] = need
        new_units = remaining[str(item.need_id)]
        if new_units == 0:
            need.status = "waiting_for_match"
            need.no_match_reason = "Участник вышел из подтверждённой группы; обязательства пересчитаны"
            await db.delete(item)
        else:
            item.units = new_units
            item.approval_status = "pending"
            need.status = "awaiting_approvals"
            need.no_match_reason = None
    await db.execute(delete(ParticipantOrder).where(ParticipantOrder.coalition_id == coalition.id))
    if group_offer is not None:
        lot = group_offer.lot_multiple or 1
        if remaining_total % lot != 0 or any(units % lot != 0 for units in remaining.values()):
            raise HTTPException(422, "Объём после изменения должен быть кратен партии")
        first_need = next(iter(live_needs.values()))
        from ..matching import order_unit
        await reserve(
            db, company_id=group_offer.company_id, anchor_type="coalition", anchor_id=coalition.id,
            units=remaining_total, start=group_offer.production_start, deadline=group_offer.production_end,
            category=coalition.category, subcategory=first_need.subcategory,
            unit=order_unit(first_need.characteristics),
        )
    await append_audit_event(
        db, event_type="coalition_changed", entity_type="coalition", entity_id=coalition.id,
        actor_user_id=user.id, actor_company_id=data.company_id,
        source_refs=[{"type": "coalition", "id": str(coalition.id)}],
        explanation="Состав подтверждённой группы изменён: обязательства пересчитаны единой записью.",
        payload={"change_request_id": str(request.id), "remaining": remaining, "version": coalition.version},
    )
    await db.commit()
    return request
