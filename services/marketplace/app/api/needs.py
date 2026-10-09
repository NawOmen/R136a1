import uuid
import hashlib
import json
from datetime import date, datetime, timezone
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from fastapi.responses import Response
from sqlalchemy import or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from ..category_admission import catalog_scope
from ..category_characteristics import validate_profile_values
from ..category_profile_snapshot import profile_after_specification_change
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
from ..models import CapabilityPassport, DeliveryAddress, Need, NeedFile, Product
from ..matching import ACTIVE_NEED_STATUSES, need_is_current, order_unit, run_market_rematch
from ..matching import _need_parts, _passport_matches
from ..experience import notify_market_watchers
from ..schemas import NeedFeedOut, NeedFileOut, NeedIn, NeedOut, NeedEditIn
from ..storage import download_object, upload_object
from ..requirements import evidence_snapshot, evidence_is_current, require_current_evidence, revision_impact, invalidate_dependents, store_revision, lock_specification_edit
from ..models import NeedRevision

router = APIRouter(tags=["needs"])

MAX_SIZE = 25 * 1024 * 1024
ALLOWED_CONTENT_TYPES = {"application/pdf", "text/plain", "text/markdown"}


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
        revision=need.revision,
        requirements_evidence=need.requirements_evidence,
        company_id=need.company_id,
        created_by_user_id=need.created_by_user_id,
        category=need.category,
        subcategory=need.subcategory,
        characteristics=need.characteristics,
        category_profile=getattr(need, "category_profile", None),
        volume_units=need.volume_units,
        budget_rub=need.budget_rub,
        deadline_date=need.deadline_date,
        delivery_address_id=need.delivery_address_id,
        visibility=need.visibility,
        status=need.status,
        valid_until=need.valid_until,
        no_match_reason=need.no_match_reason,
        confirmed_at=need.confirmed_at,
        files=[NeedFileOut.model_validate(f) for f in (files or [])],
    )


def _normalize_region(value: str) -> str:
    return value.strip().lower().replace("г.", "").replace("город", "").strip(" .")


async def _region_allowed(db: AsyncSession, passport: CapabilityPassport, need: Need,
                          addresses: dict) -> bool:
    regions = [_normalize_region(str(item)) for item in (passport.delivery_regions or []) if str(item).strip()]
    if not regions or not need.delivery_address_id:
        return True
    address = addresses.get(need.delivery_address_id)
    if address is None or not address.region:
        return True
    return _normalize_region(address.region) in regions


@router.get("/needs", response_model=list[NeedFeedOut])
async def list_needs(
    seller_company_id: uuid.UUID | None = None,
    subcategory: str | None = None,
    unit: str | None = None,
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    query = select(Need).where(
        Need.status.in_(ACTIVE_NEED_STATUSES), Need.visibility == "open_anonymized",
        Need.deadline_date >= date.today(),
        or_(Need.valid_until.is_(None), Need.valid_until >= date.today()),
    )
    seller_scopes = None
    if seller_company_id is not None:
        await require_company_seller(seller_company_id, user, db)
        products = (await db.execute(
            select(Product.category, Product.subcategory).where(Product.company_id == seller_company_id)
        )).all()
        # Без товаров производитель может ответить по паспорту возможностей.
        if products:
            seller_scopes = {catalog_scope(category, subcategory) for category, subcategory in products}
    result = await db.execute(query.order_by(Need.created_at.desc()))
    needs = list(result.scalars().all())
    if seller_company_id is not None:
        # Паспорт ограничивает и совпадения каталога: карточка даёт готовое
        # предложение сейчас, но за пределы возможностей паспорта подбор не идёт.
        # Без карточек производство без готовой позиции сохраняется через паспорт.
        passport = await db.get(CapabilityPassport, seller_company_id)
        if passport is not None:
            address_rows = await db.execute(select(DeliveryAddress).where(
                DeliveryAddress.id.in_([need.delivery_address_id for need in needs if need.delivery_address_id])))
            addresses = {address.id: address for address in address_rows.scalars().all()}
            compatible = []
            for need in needs:
                parts = _need_parts(need)
                if not _passport_matches(passport, need.category, {**parts[0], **parts[1]},
                                         need.subcategory, need.volume_units,
                                         category_profile=need.category_profile):
                    continue
                if not await _region_allowed(db, passport, need, addresses):
                    continue
                compatible.append(need)
            needs = compatible
        elif seller_scopes is not None:
            def relevant(need):
                parent, child = catalog_scope(need.category, need.subcategory)
                return any(parent == p and (child is None or child == c) for p, c in seller_scopes)
            needs = [need for need in needs if relevant(need)]
    if subcategory is not None:
        needs = [need for need in needs if (need.subcategory or "").strip().lower() == subcategory.strip().lower()]
    if unit is not None:
        needs = [need for need in needs if order_unit(need.characteristics) == unit.strip().lower()]
    return needs


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
    hash_payload = data.model_dump(mode="json", exclude={"request_key"})
    for key in ("agent_run_id", "agent_run_revision"):
        if hash_payload.get(key) is None:
            hash_payload.pop(key, None)
    # Optional classification must not change idempotency hashes of old v1 clients.
    if data.subcategory is None:
        hash_payload.pop("subcategory", None)
    request_hash = hashlib.sha256(json.dumps(hash_payload, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    if data.request_key:
        await db.execute(text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"), {"key": f"need-request:{data.company_id}:{data.request_key}"})
        existing = await db.scalar(select(Need).where(Need.company_id == data.company_id, Need.request_key == data.request_key))
        if existing:
            if existing.request_hash != request_hash:
                raise HTTPException(409, "Ключ запроса уже использован для другой потребности")
            files = (await db.scalars(select(NeedFile).where(NeedFile.need_id == existing.id))).all()
            return _need_out(existing, files)
    if data.delivery_address_id is not None:
        address = await db.get(DeliveryAddress, data.delivery_address_id)
        if address is None or address.company_id != data.company_id:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Адрес доставки не принадлежит выбранной компании",
            )
    values = data.model_dump()
    values.pop("agent_run_id", None)
    values.pop("agent_run_revision", None)
    proof = await evidence_snapshot(db, data, user)
    valid_until = values.pop("valid_until") or data.deadline_date
    if data.deadline_date < date.today():
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Срок поставки потребности не может быть в прошлом",
        )
    if valid_until < date.today():
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Срок актуальности потребности не может быть в прошлом",
        )
    need = Need(
        created_by_user_id=user.id,
        status="draft",
        request_hash=request_hash,
        requirements_evidence=proof,
        valid_until=valid_until,
        **values,
    )
    db.add(need)
    await db.flush()
    store_revision(db, need, user, {"created": True})
    await db.commit()
    await db.refresh(need)
    return _need_out(need)


@router.put("/needs/{need_id}", response_model=NeedOut)
async def edit_need(need_id: uuid.UUID, data: NeedEditIn,
                    user: CurrentUser = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    # Rematch can update any active need, including another participant's row.
    # Serialize specification edits BEFORE taking a Need lock so competing
    # editors cannot hold different needs while waiting for the same coalition.
    # This transaction lock covers ordinary and physical edits; invalidation,
    # history and rematch remain atomic. Other marketplace actions retain their
    # own locks; this is deliberately a specification-edit boundary.
    await lock_specification_edit(db)
    need = await db.scalar(select(Need).where(Need.id == need_id).with_for_update()
                           .execution_options(populate_existing=True))
    if need is None:
        raise HTTPException(404, "Потребность не найдена")
    await require_company_buyer(need.company_id, user, db)
    await require_company_admin(need.company_id, user, db)
    if data.company_id != need.company_id:
        raise HTTPException(422, "Нельзя изменить компанию потребности")
    if need.revision != data.expected_revision:
        raise HTTPException(409, "Потребность изменена в другой вкладке. Обновите страницу")
    if need.status not in ({"draft"} | ACTIVE_NEED_STATUSES):
        raise HTTPException(409, "Закрытую потребность или созданное обязательство нельзя переписать")
    impact, dependents = await revision_impact(db, need, data)
    if impact["changes"] and not impact["editable"]:
        raise HTTPException(409, "По этой версии уже есть обязательства. Используйте согласованный процесс изменения сделки")
    if impact["requires_confirmation"] and data.impact_hash != impact["impact_hash"]:
        raise HTTPException(409, "Просмотрите актуальные последствия изменения и подтвердите их")
    if data.delivery_address_id:
        address = await db.get(DeliveryAddress, data.delivery_address_id)
        if address is None or address.company_id != need.company_id:
            raise HTTPException(422, "Адрес доставки не принадлежит компании")
    valid_until = data.valid_until or data.deadline_date
    if min(data.deadline_date, valid_until) < date.today():
        raise HTTPException(422, "Срок поставки и актуальности не может быть в прошлом")
    values = data.model_dump(exclude={"expected_revision", "request_key", "company_id", "impact_hash", "agent_run_id", "agent_run_revision"})
    values["valid_until"] = valid_until
    changed = bool(impact["changes"])
    was_published = need.status != "draft"
    if changed:
        if not await db.scalar(select(NeedRevision.id).where(NeedRevision.need_id == need.id, NeedRevision.revision == need.revision)):
            store_revision(db, need, user, {"legacy_snapshot": True})
        proof = await evidence_snapshot(db, data, user)
        previous = need.requirements_evidence or {}
        if data.agent_run_id is None:
            current = await evidence_is_current(db, need)
            for key, old in previous.get("fields", {}).items():
                if key not in proof["fields"]:
                    continue
                field = proof["fields"][key]
                if current and str(old.get("value")) == str(field["value"]):
                    proof["fields"][key] = old
                else:
                    field["previous_evidence"] = old
                    field["origin"] = "manual_override"
            if current:
                proof["run"] = previous.get("run")
            proof["resolved_conflicts"] = previous.get("resolved_conflicts", [])
        need.requirements_evidence = proof
    need.category_profile = profile_after_specification_change(
        need, data.category, data.subcategory, data.characteristics,
    )
    for key, value in values.items():
        setattr(need, key, value)
    if changed:
        need.revision += 1
        if was_published:
            await invalidate_dependents(db, need, dependents, user, impact)
            need.status = "open_for_offers"
            need.confirmed_at = datetime.now(timezone.utc)
            await run_market_rematch(db, "need_specification_changed", need.id)
        store_revision(db, need, user, impact)
    from ..trust import append_audit_event
    await append_audit_event(db, event_type="need_draft_updated" if not was_published else "need_updated", entity_type="need", entity_id=need.id,
        actor_user_id=user.id, actor_company_id=need.company_id,
        explanation="Покупатель сохранил изменения потребности", payload={"revision": need.revision})
    files = list((await db.scalars(select(NeedFile).where(NeedFile.need_id == need.id))).all())
    await db.commit()
    await db.refresh(need)
    return _need_out(need, files)


@router.post("/needs/{need_id}/edit-preview")
async def preview_need_edit(need_id: uuid.UUID, data: NeedEditIn,
                            user: CurrentUser = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    need = await db.get(Need, need_id)
    if need is None:
        raise HTTPException(404, "Потребность не найдена")
    await require_company_buyer(need.company_id, user, db)
    await require_company_admin(need.company_id, user, db)
    if data.company_id != need.company_id or data.expected_revision != need.revision:
        raise HTTPException(409, "Компания или версия потребности изменилась")
    impact, _ = await revision_impact(db, need, data)
    return impact


@router.get("/needs/{need_id}/revisions")
async def need_revisions(need_id: uuid.UUID, user: CurrentUser = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    need = await db.get(Need, need_id)
    if need is None:
        raise HTTPException(404, "Потребность не найдена")
    await require_company_buyer(need.company_id, user, db)
    records = (await db.scalars(select(NeedRevision).where(NeedRevision.need_id == need_id).order_by(NeedRevision.revision.desc()))).all()
    return [{"revision": row.revision, "snapshot": row.snapshot, "impact": row.impact,
             "actor_user_id": row.actor_user_id, "created_at": row.created_at} for row in records]


@router.post("/needs/{need_id}/publish", response_model=NeedOut)
async def publish_need(
    need_id: uuid.UUID,
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    need = await db.scalar(select(Need).where(Need.id == need_id).with_for_update())
    if need is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Потребность не найдена")
    await require_company_buyer(need.company_id, user, db)
    await require_company_admin(need.company_id, user, db)
    await require_verified_company(need.company_id, user, db)
    await require_current_evidence(db, need)
    if not need_is_current(need):
        raise HTTPException(409, "Срок потребности истёк. Создайте новый черновик с актуальными условиями")
    if need.status in ACTIVE_NEED_STATUSES:
        return _need_out(need)
    if need.status != "draft":
        raise HTTPException(status.HTTP_409_CONFLICT, detail="Опубликовать можно только черновик")
    errors = validate_profile_values(need.category, need.subcategory, need.characteristics)
    if errors:
        raise HTTPException(422, "; ".join(errors))
    need.status = "open_for_offers"
    need.confirmed_at = datetime.now(timezone.utc)
    need.no_match_reason = None
    await run_market_rematch(db, "need_confirmed", need.id)
    await notify_market_watchers(db, need.category, "demand", exclude_user_id=user.id)
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
        need.status in ACTIVE_NEED_STATUSES and need.visibility == "open_anonymized"
        and need_is_current(need)
    ):
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Потребность не найдена")
    if not is_owner:
        decisions = []
        evidence = need.requirements_evidence or {}
        for key, field in evidence.get("fields", {}).items():
            if key in need.characteristics and (field.get("previous_evidence") or any(item.get("key") == key for item in evidence.get("resolved_conflicts", []))):
                decisions.append({"field": key, "confirmed_value": need.characteristics[key]})
        return NeedFeedOut.model_validate(need).model_copy(update={"requirement_decisions": decisions})
    files = []
    if is_owner:
        files = (
            await db.execute(select(NeedFile).where(NeedFile.need_id == need.id))
        ).scalars().all()
    out = _need_out(need, files)
    if need.requirements_evidence:
        out = out.model_copy(update={"requirements_evidence": {**need.requirements_evidence, "stale": not await evidence_is_current(db, need)}})
    return out


@router.post("/needs/{need_id}/files", response_model=NeedOut, status_code=status.HTTP_201_CREATED)
async def attach_need_file(
    need_id: uuid.UUID,
    file: UploadFile = File(...),
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    need = await db.scalar(select(Need).where(Need.id == need_id).with_for_update())
    if need is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Потребность не найдена")
    await require_company_buyer(need.company_id, user, db)
    await require_company_admin(need.company_id, user, db)
    if need.status != "draft":
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail="Файлы можно добавлять только в черновик потребности",
        )

    data = await file.read(MAX_SIZE + 1)
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
    digest = hashlib.sha256(data).hexdigest()
    existing_files = (await db.scalars(select(NeedFile).where(NeedFile.need_id == need.id))).all()
    if any(item.content_hash == digest and item.file_name == file_name for item in existing_files):
        return _need_out(need, existing_files)
    key = f"needs/{need.id}/{uuid.uuid4()}"
    upload_object(key, data, content_type)

    db.add(NeedFile(need_id=need.id, file_name=file_name, file_key=key, content_type=content_type, content_hash=digest))
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
    if need.status not in ({"draft", "matched"} | ACTIVE_NEED_STATUSES):
        raise HTTPException(status.HTTP_409_CONFLICT, detail="Потребность уже закрыта")
    was_public = need.status != "draft"
    need.status = "cancelled"
    need.no_match_reason = "Потребность отозвана покупателем"
    await run_market_rematch(db, "need_cancelled", need.id)
    if was_public:
        await notify_market_watchers(db, need.category, "demand", exclude_user_id=user.id)
    await db.commit()
    await db.refresh(need)
    return _need_out(need)
