import uuid
from typing import Literal
from datetime import date, datetime, timedelta, timezone

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from ..admission import BUYER_CHECKLIST_NOTE, company_admission, company_documents
from ..category_admission import STATE_LABELS, canonical_scope, classification_hint, match_profile
from ..database import get_db
from ..deps import (
    CurrentUser,
    get_current_user,
    notify,
    require_company_admin,
    require_company_seller,
    require_category_editor,
)
from ..models import Document, Product
from ..schemas import (
    CategoryAdmissionOut,
    CategoryRequirementsOut,
    DocumentOut,
    DocumentVerificationIn,
    DocumentDecisionIn,
    PendingDocumentOut,
)
from ..storage import delete_object, upload_object
from ..trust import append_audit_event, record_human_approval

router = APIRouter(tags=["documents"])

MAX_SIZE = 25 * 1024 * 1024

async def _notify_company(db: AsyncSession, company_id: uuid.UUID, message: str) -> None:
    """Сообщить участникам компании, что доказательство допуска изменилось."""
    user_ids = (
        await db.execute(
            text("SELECT user_id FROM auth.company_members WHERE company_id = :cid"), {"cid": company_id}
        )
    ).scalars().all()
    for user_id in user_ids:
        await notify(db, user_id, message, "document_verification_changed")


async def _notify_affected_deals(
    db: AsyncSession,
    company_id: uuid.UUID,
    document_name: str,
    scope_category: str | None,
    scope_subcategory: str | None,
) -> int:
    """Действующие сделки: изменение допуска требует ручного решения, а не отмены договорённостей."""
    document_scope = canonical_scope(scope_category, scope_subcategory)
    # A legacy subtype below a known leaf must not suppress its change alert.
    # This affects notifications only; verified legal scope is never broadened.
    from ..category_registry import resolve_category
    if scope_subcategory and resolve_category(scope_category, scope_subcategory) is None and resolve_category(scope_category, None):
        document_scope = canonical_scope(scope_category, None)
    rows = (
        await db.execute(
            text(
                "SELECT DISTINCT d.id, d.buyer_company_id, n.category, n.subcategory "
                "FROM marketplace.deals d "
                "JOIN marketplace.needs n ON n.id = d.need_id "
                "WHERE d.seller_company_id = :cid"
            ),
            {"cid": company_id},
        )
    ).mappings().all()
    affected = 0
    targets: set[uuid.UUID] = set()
    for row in rows:
        need_scope = canonical_scope(row["category"], row["subcategory"])
        if need_scope[0] != document_scope[0]:
            continue
        # An older need may record only the parent category. Its exact
        # subcategory is unknown, so notify conservatively rather than miss it.
        if document_scope[1] and need_scope[1] and need_scope[1] != document_scope[1]:
            continue
        affected += 1
        targets.update({row["buyer_company_id"], company_id})
    scope_label = scope_category or "категория не указана"
    for target in targets:
        await _notify_company(
            db,
            target,
            f"Допуск по документу «{document_name}» для «{scope_label}» изменился. "
            "Действующие договорённости не отменяются автоматически: проверьте сделку и примите решение.",
        )
    return affected


async def _reevaluate_products(
    db: AsyncSession, company_id: uuid.UUID, scope_category: str | None, scope_subcategory: str | None
) -> list[str]:
    """Опубликованные товары, потерявшие допуск после изменения документов.

    Только переоценка и ответственное решение: товары не снимаются автоматически,
    имена возвращаются для уведомления и журнала.
    """
    scope = canonical_scope(scope_category, scope_subcategory)
    products = (
        await db.execute(
            select(Product).where(Product.company_id == company_id, Product.is_published.is_(True))
        )
    ).scalars().all()
    lost: list[str] = []
    for product in products:
        need_scope = canonical_scope(product.category, product.subcategory)
        if need_scope[0] != scope[0]:
            continue
        if scope[1] and need_scope[1] and need_scope[1] != scope[1]:
            continue
        admission = await company_admission(
            db, company_id, product.category, product.subcategory,
            characteristics=product.characteristics, moq_units=product.moq_units)
        if admission.blocking_open:
            lost.append(product.name)
    return lost


@router.get("/companies/{company_id}/documents/expiring", response_model=list[DocumentOut])
async def expiring_documents(
    company_id: uuid.UUID,
    within_days: int = Query(default=30, ge=1, le=365),
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Подтверждённые документы со сроком до горизонта: продлить до блокировки новых обязательств."""
    await require_company_seller(company_id, user, db)
    horizon = date.today() + timedelta(days=within_days)
    return [
        document
        for document in await company_documents(db, company_id)
        if document.verification_status == "verified"
        and document.valid_until is not None
        and document.valid_until <= horizon
    ]


@router.get("/companies/{company_id}/documents", response_model=list[DocumentOut])
async def list_documents(
    company_id: uuid.UUID,
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await require_company_seller(company_id, user, db)
    return await company_documents(db, company_id)


@router.post("/companies/{company_id}/documents", response_model=DocumentOut, status_code=status.HTTP_201_CREATED)
async def upload_document(
    company_id: uuid.UUID,
    name: str = Form(...),
    document_type: str = Form(...),
    scope_category: str | None = Form(default=None),
    scope_subcategory: str | None = Form(default=None),
    valid_until: date | None = Form(default=None),
    file: UploadFile = File(...),
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await require_company_seller(company_id, user, db)
    await require_company_admin(company_id, user, db)
    data = await file.read()
    if len(data) > MAX_SIZE:
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail="Файл больше 25 МБ")

    content_type = file.content_type or "application/octet-stream"
    try:
        from ..file_safety import check_upload
        content_type = check_upload(data, content_type)
    except ValueError as exc:
        raise HTTPException(status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, detail=str(exc)) from None
    key = f"companies/{company_id}/{uuid.uuid4()}"
    upload_object(key, data, content_type)

    document = Document(
        company_id=company_id,
        created_by_user_id=user.id,
        name=name,
        document_type=document_type,
        file_key=key,
        content_type=content_type,
        # Загрузка не подтверждает подлинность и применимость документа.
        verification_status="unverified",
        scope_category=(scope_category or "").strip() or None,
        scope_subcategory=(scope_subcategory or "").strip() or None,
        valid_until=valid_until,
    )
    db.add(document)
    await db.flush()
    await append_audit_event(
        db,
        event_type="document_uploaded",
        entity_type="document",
        entity_id=document.id,
        actor_user_id=user.id,
        actor_company_id=company_id,
        source_refs=[{"type": "document", "id": str(document.id)}],
        explanation="Компания загрузила документ. До решения проверяющего он не является доказательством допуска.",
        payload={"document_type": document_type, "scope_category": document.scope_category},
    )
    await db.commit()
    await db.refresh(document)
    return document


@router.delete("/documents/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_document(
    document_id: uuid.UUID,
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    document = await db.get(Document, document_id)
    if document is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Документ не найден")
    await require_company_admin(document.company_id, user, db)
    was_verified = document.verification_status == "verified"
    document_name = document.name
    scope = document.scope_category or "категории без указанной области действия"
    company_id = document.company_id
    scope_category = document.scope_category
    scope_subcategory = document.scope_subcategory
    delete_object(document.file_key)
    await db.delete(document)
    await db.flush()
    if was_verified:
        # Доказательство исчезло: опубликованные товары нужно проверить заново.
        rechecked = await _reevaluate_products(db, company_id, scope_category, scope_subcategory)
        products_note = f" Допуск потеряли: {', '.join(rechecked[:5])}." if rechecked else ""
        await _notify_company(
            db,
            company_id,
            f"Документ «{document_name}» удалён и больше не подтверждает допуск для «{scope}». "
            f"Проверьте опубликованные товары: публикация может быть отклонена.{products_note}",
        )
        await _notify_affected_deals(db, company_id, document_name, scope_category, scope_subcategory)
        if rechecked:
            await append_audit_event(
                db,
                event_type="document_status_reevaluated",
                entity_type="document",
                entity_id=document.id,
                actor_user_id=user.id,
                actor_company_id=company_id,
                source_refs=[{"type": "document", "id": str(document.id)}],
                explanation="После удаления документа переоценены опубликованные товары; товары не сняты автоматически, решение за ответственным.",
                payload={"products_without_admission": rechecked},
            )
    await db.commit()


@router.post("/documents/{document_id}/verification", response_model=DocumentOut)
async def verify_document(
    document_id: uuid.UUID,
    data: DocumentVerificationIn,
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Решение по документу принимает проверяющий площадки, а не продавец."""
    await require_category_editor(user, db)
    document = await db.get(Document, document_id)
    if document is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Документ не найден")
    if data.decision == "verified":
        profile = match_profile(data.scope_category or "", data.scope_subcategory)
        if profile is not None and not profile.supported:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                detail="Для категории не настроена проверка: подтверждение допуска невозможно",
            )

    previous_status = document.verification_status
    previous_scope = (document.scope_category, document.scope_subcategory)
    repeat_confirms = (data.confirms or {}) if data.decision == "verified" else {}
    if (document.verified_by_user_id == user.id and document.verification_status == data.decision
            and document.verification_note == data.note
            and (data.valid_until is None or document.valid_until == data.valid_until)
            and document.scope_category == (data.scope_category or document.scope_category or None)
            and document.scope_subcategory == (data.scope_subcategory or document.scope_subcategory or None)
            and document.confirms == repeat_confirms):
        # Повтор того же решения не пишет новый approval/аудит/уведомления.
        return document
    document.verification_status = data.decision
    document.scope_category = (data.scope_category or document.scope_category or None)
    document.scope_subcategory = (data.scope_subcategory or document.scope_subcategory or None)
    # Срок из загрузки сохраняется, пока проверяющий явно не задал новый.
    if data.valid_until is not None:
        document.valid_until = data.valid_until
    if data.decision == "verified":
        # Проверяющий фиксирует, какие материал и покрытие подтверждены документом.
        document.confirms = data.confirms if data.confirms is not None else {}
    else:
        document.confirms = {}
    document.verification_note = data.note
    document.verified_by_user_id = user.id
    document.verified_at = datetime.now(timezone.utc)

    await record_human_approval(
        db,
        action="verify_document",
        entity_type="document",
        entity_id=document.id,
        actor_user_id=user.id,
        actor_company_id=document.company_id,
        permission="category_editor_or_marketplace_admin",
        decision="approved" if data.decision == "verified" else "rejected",
        payload={
            "document_id": str(document.id),
            "decision": data.decision,
            "previous_status": previous_status,
            "scope_category": document.scope_category,
            "scope_subcategory": document.scope_subcategory,
            "valid_until": document.valid_until.isoformat() if document.valid_until else None,
            "confirms": document.confirms,
        },
        source_refs=[{"type": "document", "id": str(document.id)}],
        explanation="Проверяющий площадки принял решение по документу допуска.",
        reason=data.note,
    )
    await append_audit_event(
        db,
        event_type="document_verification_changed",
        entity_type="document",
        entity_id=document.id,
        actor_user_id=user.id,
        actor_company_id=document.company_id,
        source_refs=[{"type": "document", "id": str(document.id)}],
        explanation="Статус документа изменён человеком с правами администратора площадки.",
        payload={
            "from": previous_status,
            "to": data.decision,
            "scope_category": document.scope_category,
            "state_label": STATE_LABELS["satisfied"] if data.decision == "verified" else "",
        },
    )
    rechecked: list[str] = []
    if data.decision != "verified":
        scope = document.scope_category or "категории без указанной области действия"
        decision_label = "Не соответствует" if data.decision == "rejected" else "Проверка снята"
        if previous_status == "verified":
            rechecked = await _reevaluate_products(
                db, document.company_id,
                *(previous_scope if any(previous_scope) else (document.scope_category, document.scope_subcategory)))
        products_note = f" Перепроверьте товары: {', '.join(rechecked[:5])}." if rechecked else ""
        await _notify_company(
            db,
            document.company_id,
            f"Документ «{document.name}»: статус «{decision_label}». Он больше не подтверждает допуск "
            f"для «{scope}». Загрузите документ заново или уточните область действия.{products_note}",
        )
        await _notify_affected_deals(
            db, document.company_id, document.name,
            *(previous_scope if previous_status == "verified" else (document.scope_category, document.scope_subcategory))
        )
    elif previous_status == "verified" and previous_scope != (document.scope_category, document.scope_subcategory):
        # A narrower verified scope can stop covering existing products/deals.
        rechecked = await _reevaluate_products(db, document.company_id, *previous_scope)
        products_note = f" Допуск потеряли: {', '.join(rechecked[:5])}." if rechecked else ""
        await _notify_company(db, document.company_id,
            f"Область действия документа «{document.name}» изменилась. Проверьте опубликованные товары и действующие сделки.{products_note}")
        await _notify_affected_deals(db, document.company_id, document.name, *previous_scope)
    if rechecked:
        await append_audit_event(
            db,
            event_type="document_status_reevaluated",
            entity_type="document",
            entity_id=document.id,
            actor_user_id=user.id,
            actor_company_id=document.company_id,
            source_refs=[{"type": "document", "id": str(document.id)}],
            explanation="После изменения документа переоценены опубликованные товары; товары не сняты автоматически, решение за ответственным.",
            payload={"products_without_admission": rechecked},
        )
    await db.commit()
    await db.refresh(document)
    return document


@router.get("/editor/documents", response_model=list[PendingDocumentOut])
@router.get("/admin/documents/pending", response_model=list[PendingDocumentOut])
async def pending_documents(
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    limit: int = Query(default=50, ge=1, le=200),
    verification_status: Literal["unverified","verified","rejected"] = "unverified",
):
    """Очередь проверки документов для администратора площадки."""
    await require_category_editor(user, db)
    rows = (
        await db.execute(
            text(
                "SELECT d.id, d.company_id, d.name, d.document_type, d.file_key, d.content_type, "
                "d.verification_status, d.scope_category, d.scope_subcategory, d.valid_until, d.confirms, "
                "d.verified_by_user_id, d.verified_at, d.verification_note, d.created_at, "
                "c.display_name AS company_display_name "
                "FROM marketplace.documents d "
                "JOIN auth.companies c ON c.id = d.company_id "
                "WHERE d.verification_status = :verification_status "
                "ORDER BY d.created_at DESC LIMIT :limit"
            ),
            {"limit": limit,"verification_status":verification_status},
        )
    ).mappings().all()
    return [PendingDocumentOut(**row) for row in rows]


@router.get("/companies/{company_id}/category-admission", response_model=CategoryAdmissionOut)
async def company_category_admission(
    company_id: uuid.UUID,
    category: str = Query(min_length=2, max_length=120),
    subcategory: str | None = Query(default=None, max_length=120),
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Отчёт продавцу: какие доказательства уже подтверждены, а какие нужно приложить."""
    await require_company_seller(company_id, user, db)
    return await company_admission(db, company_id, category, subcategory)


@router.get("/category-requirements", response_model=CategoryRequirementsOut)
async def category_requirements(
    category: str = Query(min_length=2, max_length=120),
    subcategory: str | None = Query(default=None, max_length=120),
    db: AsyncSession = Depends(get_db),
):
    """Публичный чек-лист покупателя. Без авторизации и без данных о компании."""
    profile = match_profile(category, subcategory)
    if profile is None:
        hint = classification_hint(category)
        if hint is not None:
            # Правила зависят от подкатегории: без классификации чек-лист неполный.
            return CategoryRequirementsOut(
                category=category,
                subcategory=subcategory,
                profile_title=None,
                supported=True,
                summary=hint,
                checklist=[],
                advisories=[
                    "Уточните подкатегорию товара: до классификации нельзя определить применимые документы.",
                ],
                note=BUYER_CHECKLIST_NOTE,
            )
        return CategoryRequirementsOut(
            category=category,
            subcategory=subcategory,
            profile_title=None,
            supported=False,
            summary="Категория не определена. Выберите известную подкатегорию: без классификации публикация и обязательства заблокированы.",
            checklist=[],
            advisories=["Неизвестная категория не означает отсутствие обязательных требований"],
            note=BUYER_CHECKLIST_NOTE,
        )
    if not profile.supported:
        return CategoryRequirementsOut(
            category=category,
            subcategory=subcategory,
            profile_title=profile.title,
            supported=False,
            summary=profile.summary,
            checklist=[],
            advisories=list(profile.advisories),
            note=BUYER_CHECKLIST_NOTE,
        )
    return CategoryRequirementsOut(
        category=category,
        subcategory=subcategory,
        profile_title=profile.title,
        supported=True,
        summary=profile.summary,
        checklist=[
            {
                "code": requirement.code,
                "title": requirement.title,
                "legal_reference": requirement.legal_reference,
                "blocking": requirement.blocking,
                "state": "required",
                "state_label": "Требуется подтверждение",
                "seller_hint": requirement.seller_hint,
                "buyer_note": requirement.buyer_note,
                "document_ids": [],
            }
            for requirement in profile.requirements
        ],
        advisories=list(profile.advisories),
        note=BUYER_CHECKLIST_NOTE,
    )


@router.get("/editor/documents/{document_id}/download")
async def editor_document_file(document_id: uuid.UUID,user:CurrentUser=Depends(get_current_user),db:AsyncSession=Depends(get_db)):
    await require_category_editor(user,db)
    document=await db.get(Document,document_id)
    if document is None:raise HTTPException(404,"Документ не найден")
    from fastapi.responses import Response
    from ..storage import download_object
    return Response(download_object(document.file_key),media_type="application/octet-stream",
                    headers={"Content-Disposition":f'attachment; filename="document-{document.id}"',"X-Content-Type-Options":"nosniff"})


@router.post("/documents/{document_id}/decision", response_model=DocumentOut)
async def decide_document(document_id: uuid.UUID, data: DocumentDecisionIn,
                          user: CurrentUser = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    await require_category_editor(user, db)
    document = await db.scalar(select(Document).where(Document.id == document_id)
                               .with_for_update().execution_options(populate_existing=True))
    if document is None:
        raise HTTPException(404, "Документ не найден")
    confirms = (data.confirms or {}) if data.decision == "verified" else {}
    if (document.verified_by_user_id == user.id and document.verification_status == data.decision
            and document.verification_note == data.note
            and (data.valid_until is None or document.valid_until == data.valid_until)
            and document.scope_category == (data.scope_category or document.scope_category or None)
            and document.scope_subcategory == (data.scope_subcategory or document.scope_subcategory or None)
            and document.confirms == confirms):
        return document
    return await verify_document(document_id, data, user, db)
