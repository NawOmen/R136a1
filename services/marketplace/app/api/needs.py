import uuid
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from fastapi.responses import Response
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_db
from ..deps import (
    CurrentUser,
    get_current_user,
    get_membership,
    require_company_admin,
    require_company_buyer,
    require_company_seller,
    require_verified_company,
)
from ..models import DeliveryAddress, Need, NeedFile, Product
from ..schemas import NeedFeedOut, NeedFileOut, NeedIn, NeedOut
from ..storage import download_object, upload_object

router = APIRouter(tags=["needs"])

MAX_SIZE = 25 * 1024 * 1024
ALLOWED_CONTENT_TYPES = {"application/pdf"}


def _is_allowed_content_type(content_type: str) -> bool:
    return (
        content_type in ALLOWED_CONTENT_TYPES
        or content_type.startswith("image/")
        or content_type.startswith("audio/")
    )


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


@router.get("/needs", response_model=list[NeedFeedOut])
async def list_needs(
    seller_company_id: uuid.UUID | None = None,
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    query = select(Need).where(
        Need.status == "open_for_offers", Need.visibility == "open_anonymized"
    )
    if seller_company_id is not None:
        await require_company_seller(seller_company_id, user, db)
        categories = (
            await db.execute(select(Product.category).where(Product.company_id == seller_company_id))
        ).scalars().all()
        # Если товары уже заведены, используем их категории как базовый фильтр.
        # Без товаров показываем открытую ленту: производитель по правилам MVP
        # вправе ответить на запрос на основании Capability Passport.
        if categories:
            query = query.where(Need.category.in_(set(categories)))
    result = await db.execute(query.order_by(Need.created_at.desc()))
    return result.scalars().all()


@router.get("/needs/mine", response_model=list[NeedOut])
async def list_my_needs(
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    company_ids = await _my_company_ids(db, user.id)
    if not company_ids:
        return []
    result = await db.execute(
        select(Need).where(Need.company_id.in_(company_ids)).order_by(Need.created_at.desc())
    )
    return [_need_out(need) for need in result.scalars().all()]


@router.post("/needs", response_model=NeedOut, status_code=status.HTTP_201_CREATED)
async def create_need(
    data: NeedIn,
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await require_company_buyer(data.company_id, user, db)
    await require_company_admin(data.company_id, user, db)
    if data.delivery_address_id is not None:
        address = await db.get(DeliveryAddress, data.delivery_address_id)
        if address is None or address.company_id != data.company_id:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Адрес доставки не принадлежит выбранной компании",
            )
    need = Need(created_by_user_id=user.id, status="draft", **data.model_dump())
    db.add(need)
    await db.commit()
    await db.refresh(need)
    return _need_out(need)


@router.post("/needs/{need_id}/publish", response_model=NeedOut)
async def publish_need(
    need_id: uuid.UUID,
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    need = await db.get(Need, need_id)
    if need is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Потребность не найдена")
    await require_company_buyer(need.company_id, user, db)
    await require_company_admin(need.company_id, user, db)
    await require_verified_company(need.company_id, user, db)
    if need.status != "draft":
        raise HTTPException(status.HTTP_409_CONFLICT, detail="Опубликовать можно только черновик")
    need.status = "open_for_offers"
    await db.commit()
    await db.refresh(need)
    return _need_out(need)


@router.get("/needs/{need_id}", response_model=NeedOut | NeedFeedOut)
async def get_need(
    need_id: uuid.UUID,
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    need = await db.get(Need, need_id)
    if need is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Потребность не найдена")
    membership = await get_membership(db, need.company_id, user.id)
    is_owner = bool(membership and membership["can_buy"])
    if not is_owner and not (
        need.status == "open_for_offers" and need.visibility == "open_anonymized"
    ):
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Потребность не найдена")
    if not is_owner:
        return NeedFeedOut.model_validate(need)
    files = []
    if is_owner:
        files = (
            await db.execute(select(NeedFile).where(NeedFile.need_id == need.id))
        ).scalars().all()
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
    await require_company_admin(need.company_id, user, db)
    if need.status != "draft":
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail="Файлы можно добавлять только в черновик потребности",
        )

    data = await file.read()
    if not data:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="Файл пуст")
    if len(data) > MAX_SIZE:
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail="Файл больше 25 МБ")
    content_type = file.content_type or "application/octet-stream"
    if not _is_allowed_content_type(content_type):
        raise HTTPException(
            status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail="Допустимы только изображения, PDF и аудиофайлы",
        )
    file_name = file.filename or "file"
    if len(file_name) > 255:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="Имя файла длиннее 255 символов")
    key = f"needs/{need.id}/{uuid.uuid4()}"
    upload_object(key, data, content_type)

    db.add(NeedFile(need_id=need.id, file_name=file_name, file_key=key, content_type=content_type))
    await db.commit()
    files = (await db.execute(select(NeedFile).where(NeedFile.need_id == need.id))).scalars().all()
    return _need_out(need, files)


@router.get("/need-files/{file_id}/download")
async def download_need_file(
    file_id: uuid.UUID,
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    need_file = await db.get(NeedFile, file_id)
    if need_file is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Файл не найден")
    need = await db.get(Need, need_file.need_id)
    if need is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Потребность не найдена")
    await require_company_buyer(need.company_id, user, db)
    data = download_object(need_file.file_key)
    encoded_name = quote(need_file.file_name)
    return Response(
        content=data,
        media_type=need_file.content_type,
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{encoded_name}"},
    )


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
    await require_company_admin(need.company_id, user, db)
    if need.status not in ("draft", "open_for_offers", "matched"):
        raise HTTPException(status.HTTP_409_CONFLICT, detail="Потребность уже закрыта")
    need.status = "cancelled"
    await db.commit()
    await db.refresh(need)
    return _need_out(need)
