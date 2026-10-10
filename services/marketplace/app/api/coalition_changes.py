"""S08.04: изменение состава подтверждённой группы.

Решение производителя принимает новый состав, но не создаёт новых обязательств:
группа возвращается на до-согласование через штатные publish/decide, где
пересчитываются смета, бюджет, выгода, допуск и ресурс. Старая группа не
удаляется; подтверждённые заказы сохраняются со статусом superseded, исполненный
объём учитывается (consumed-строки не трогаем). Выход ниже MOQ аннулирует старые
условия. Повтор по тому же ключу возвращает сохранённую заявку.
"""
import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_db
from ..deps import (
    CurrentUser,
    get_current_user,
    require_company_admin,
    require_company_buyer,
    require_company_seller,
    require_membership,
    require_verified_company,
)
from ..matching import need_is_current
from ..models import (
    Coalition,
    CoalitionChangeRequest,
    CoalitionMember,
    GroupOffer,
    Need,
    ParticipantOrder,
)
from ..resources import release
from ..trust import append_audit_event
from .market import _lock_coalition_needs

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


async def _viewer_is_party(db: AsyncSession, coalition: Coalition, user: CurrentUser, company_id: uuid.UUID) -> None:
    """Доступ к заявке: участник-покупатель или производитель, с членством."""
    members = (
        await db.execute(select(CoalitionMember).where(CoalitionMember.coalition_id == coalition.id))
    ).scalars().all()
    buyer_companies = {item.buyer_company_id for item in members}
    if company_id != coalition.producer_company_id and company_id not in buyer_companies:
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="Компания не связана с коалицией")
    await require_membership(company_id, user, db)


@router.post("/coalitions/{coalition_id}/change-requests", response_model=ChangeRequestOut, status_code=201)
async def create_change_request(
    coalition_id: uuid.UUID,
    data: ChangeRequestIn,
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    coalition = (
        await db.execute(select(Coalition).where(Coalition.id == coalition_id))
    ).scalar_one_or_none()
    if coalition is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Коалиция не найдена")
    # Идемпотентный повтор возвращает сохранённую заявку даже после перехода группы.
    existing = (
        await db.execute(
            select(CoalitionChangeRequest).where(
                CoalitionChangeRequest.coalition_id == coalition.id,
                CoalitionChangeRequest.idempotency_key == data.idempotency_key,
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        await _viewer_is_party(db, coalition, user, data.company_id)
        if (
            existing.requested_by_company_id != data.company_id
            or existing.reason != data.reason
            or {str(key): value for key, value in existing.proposed_units.items()} !=
            {str(key): value for key, value in data.proposed_units.items()}
        ):
            raise HTTPException(409, "Ключ запроса уже использован для других данных")
        return existing
    if coalition.status != "confirmed":
        raise HTTPException(409, "Изменение состава доступно только подтверждённой группе")
    # Порядок блокировок как в основном потоке: сначала потребности, затем коалиция.
    await _lock_coalition_needs(db, coalition_id)
    coalition = (
        await db.execute(
            select(Coalition).where(Coalition.id == coalition_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    ).scalar_one_or_none()
    if coalition is None or coalition.status != "confirmed":
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
    if not data.proposed_units:
        raise HTTPException(422, "Запрос без изменения состава: укажите новые объёмы участников")
    if any(units < 0 for units in data.proposed_units.values()):
        raise HTTPException(422, "Объём участника не может быть отрицательным")
    current = {str(item.need_id): item.units for item in members}
    if all(data.proposed_units.get(key, current[key]) == current[key] for key in current):
        raise HTTPException(422, "Новый состав совпадает с действующим: изменений нет")
    if data.resource_policy not in {"release_and_rereserve"}:
        raise HTTPException(422, "Неизвестная политика ресурса")
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
    stored = await db.get(CoalitionChangeRequest, request_id)
    if stored is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Запрос изменения не найден")
    # Порядок блокировок как в основном потоке: сначала потребности, затем коалиция,
    # затем актуальная заявка под блокировкой.
    await _lock_coalition_needs(db, stored.coalition_id)
    coalition = (
        await db.execute(
            select(Coalition).where(Coalition.id == stored.coalition_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    ).scalar_one_or_none()
    if coalition is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Коалиция не найдена")
    request = (
        await db.execute(
            select(CoalitionChangeRequest).where(CoalitionChangeRequest.id == request_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    ).scalar_one_or_none()
    # Проверки доступа действуют и при повторе завершённого решения.
    await _viewer_is_party(db, coalition, user, data.company_id)
    if request.status != "pending":
        return request
    if coalition.status != "confirmed":
        raise HTTPException(409, "Группа уже не подтверждена: запрос изменения не применим")
    if coalition.version != request.version_from or coalition.version != data.expected_revision:
        raise HTTPException(409, "Условия группы изменились. Запросите изменение заново")
    if data.company_id != coalition.producer_company_id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="Изменение подтверждает производитель")
    await require_company_seller(data.company_id, user, db)
    await require_company_admin(data.company_id, user, db)
    await require_verified_company(data.company_id, user, db)
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
    member_needs = {
        item.need_id: await db.get(Need, item.need_id) for item in members
    }
    if not member_needs or any(
        need is None or need.status != "matched" or not need_is_current(need)
        for need in member_needs.values()
    ):
        raise HTTPException(409, "Потребность участника закрыта или её срок истёк")
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
    max_total = group_offer.max_total_units if group_offer else None
    if max_total is not None and remaining_total > max_total:
        raise HTTPException(422, "Новый объём превышает максимум партии")
    old_orders = (
        await db.execute(select(ParticipantOrder).where(ParticipantOrder.coalition_id == coalition.id))
    ).scalars().all()
    for order in old_orders:
        if order.status == "created":
            order.status = "superseded"
    if moq and remaining_total < moq:
        # Выход ниже MOQ: старые условия аннулированы, состав отражает остаток.
        request.status = "applied_annulled"
        request.version_to = coalition.version + 1
        coalition.version += 1
        coalition.combined_volume_units = remaining_total
        for item in members:
            item.units = remaining[str(item.need_id)]
            if remaining[str(item.need_id)] == 0:
                await db.delete(item)
        if group_offer is not None and group_offer.company_id:
            await release(db, company_id=group_offer.company_id, anchor_type="coalition", anchor_id=coalition.id)
        coalition.status = "recalculation_required"
        if group_offer is not None:
            group_offer.status = "recalculation_required"
        for item in members:
            need = member_needs[item.need_id]
            need.status = "waiting_for_match"
            if remaining[str(item.need_id)] == 0:
                need.no_match_reason = "Участник вышел из группы; обязательство аннулировано ниже MOQ"
            else:
                need.no_match_reason = (
                    "Состав группы изменился ниже MOQ: старые условия аннулированы, выполняется повторный подбор"
                )
        await append_audit_event(
            db, event_type="coalition_change_annulled", entity_type="coalition", entity_id=coalition.id,
            actor_user_id=user.id, actor_company_id=data.company_id,
            source_refs=[{"type": "coalition", "id": str(coalition.id)}],
            explanation="Выход участника опустил группу ниже MOQ: старые условия аннулированы, заказы сохранены.",
            payload={"change_request_id": str(request.id), "remaining_total": remaining_total, "moq": moq},
        )
        await db.commit()
        return request
    # Состав принят: группа возвращается на до-согласование, экономика будет
    # пересчитана штатной публикацией, обязательства — штатным согласием.
    request.status = "applied"
    request.version_to = coalition.version + 1
    coalition.version += 1
    coalition.combined_volume_units = remaining_total
    coalition.status = "recalculation_required"
    if group_offer is not None:
        group_offer.status = "draft"
        group_offer.seller_approval_status = "pending"
    for item in members:
        need = member_needs[item.need_id]
        new_units = remaining[str(item.need_id)]
        if new_units == 0:
            need.status = "waiting_for_match"
            need.no_match_reason = "Участник вышел из подтверждённой группы; обязательства пересчитаны"
            await db.delete(item)
        else:
            if need.volume_units != new_units:
                need.volume_units = new_units
                need.revision += 1
            need.status = "coalition_candidate"
            need.no_match_reason = None
            item.units = new_units
            item.approval_status = "pending"
    await append_audit_event(
        db, event_type="coalition_changed", entity_type="coalition", entity_id=coalition.id,
        actor_user_id=user.id, actor_company_id=data.company_id,
        source_refs=[{"type": "coalition", "id": str(coalition.id)}],
        explanation="Состав подтверждённой группы принят: смета и обязательства будут пересчитаны до-согласованием.",
        payload={"change_request_id": str(request.id), "remaining": remaining, "version": coalition.version},
    )
    await db.commit()
    return request
