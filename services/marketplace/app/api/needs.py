import uuid

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_db
from ..deps import CurrentUser, get_current_user, require_company_buyer, require_verified_company
from ..models import Need, NeedFile
from ..schemas import NeedFileOut, NeedIn, NeedOut
from ..storage import upload_object

router = APIRouter(tags=["needs"])

MAX_SIZE = 25 * 1024 * 1024


async def _my_company_ids(db: AsyncSession, user_id: uuid.UUID) -> list[uuid.UUID]:
    result = await db.execute(
        text("SELECT company_id FROM auth.company_members WHERE user_id = :uid"), {"uid": user_id}
    )
    return [r[0] for r in result]


def _need_out(need: Need, files: list[NeedFile] | None = None) -> NeedOut:
    return NeedOut(
        id=need.id,
        company_id=need.company_id,
        created_by_user_id=need.created_by_user_id,
        category=need.category,
        characteristics=need.characteristics,
        volume_units=need.volume_units,
        budget_rub=need.budget_rub,
        deadline_date=need.deadline_date,
        delivery_address_id=need.delivery_address_id,
        visibility=need.visibility,
        status=need.status,
        files=[NeedFileOut.model_validate(f) for f in (files or [])],
    )


@router.get("/needs", response_model=list[NeedOut])
async def list_needs(
    mine: bool = False,
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    query = select(Need)
    if mine:
        company_ids = await _my_company_ids(db, user.id)
        if not company_ids:
            return []
        query = query.where(Need.company_id.in_(company_ids))
    else:
        query = query.where(Need.status == "open_for_offers", Need.visibility == "open_anonymized")
    result = await db.execute(query.order_by(Need.created_at.desc()))
    return [_need_out(n) for n in result.scalars().all()]


@router.post("/needs", response_model=NeedOut, status_code=status.HTTP_201_CREATED)
async def create_need(
    data: NeedIn,
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await require_company_buyer(data.company_id, user, db)
    await require_verified_company(data.company_id, user, db)
    need = Need(created_by_user_id=user.id, **data.model_dump())
    db.add(need)
    await db.commit()
    await db.refresh(need)
    return _need_out(need)


@router.get("/needs/{need_id}", response_model=NeedOut)
async def get_need(
    need_id: uuid.UUID,
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    need = await db.get(Need, need_id)
    if need is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Потребность не найдена")
    files = (await db.execute(select(NeedFile).where(NeedFile.need_id == need.id))).scalars().all()
    return _need_out(need, files)


@router.post("/needs/{need_id}/files", response_model=NeedOut, status_code=status.HTTP_201_CREATED)
async def attach_need_file(
    need_id: uuid.UUID,
    file: UploadFile = File(...),
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    need = await db.get(Need, need_id)
    if need is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Потребность не найдена")
    await require_company_buyer(need.company_id, user, db)

    data = await file.read()
    if len(data) > MAX_SIZE:
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail="Файл больше 25 МБ")
    content_type = file.content_type or "application/octet-stream"
    key = f"needs/{need.id}/{uuid.uuid4()}"
    upload_object(key, data, content_type)

    db.add(NeedFile(need_id=need.id, file_name=file.filename or "file", file_key=key, content_type=content_type))
    await db.commit()
    files = (await db.execute(select(NeedFile).where(NeedFile.need_id == need.id))).scalars().all()
    return _need_out(need, files)


@router.post("/needs/{need_id}/cancel", response_model=NeedOut)
async def cancel_need(
    need_id: uuid.UUID,
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    need = await db.get(Need, need_id)
    if need is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Потребность не найдена")
    await require_company_buyer(need.company_id, user, db)
    if need.status not in ("open_for_offers", "matched"):
        raise HTTPException(status.HTTP_409_CONFLICT, detail="Потребность уже закрыта")
    need.status = "cancelled"
    await db.commit()
    await db.refresh(need)
    return _need_out(need)
