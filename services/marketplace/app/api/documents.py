import uuid
from datetime import date, datetime, timezone

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from ..category_admission import STATE_LABELS, evaluate_admission, match_profile
from ..database import get_db
from ..deps import (
    CurrentUser,
    get_current_user,
    notify,
    require_company_admin,
    require_company_seller,
    require_marketplace_admin,
)
from ..models import Document
from ..schemas import (
    CategoryAdmissionOut,
    CategoryRequirementsOut,
    DocumentOut,
    DocumentVerificationIn,
    PendingDocumentOut,
)
from ..storage import delete_object, upload_object
from ..trust import append_audit_event, record_human_approval

router = APIRouter(tags=["documents"])

MAX_SIZE = 25 * 1024 * 1024

BUYER_CHECKLIST_NOTE = (
    "Чек-лист показывает, какие обязательные доказательства проверены у продавца. "
    "Он не заменяет проверку конкретной партии при приёмке и не является юридическим заключением."
)


async def _company_documents(db: AsyncSession, company_id: uuid.UUID) -> list[Document]:
    result = await db.execute(
        select(Document).where(Document.company_id == company_id).order_by(Document.created_at.desc())
    )
    return list(result.scalars().all())


async def company_admission(
    db: AsyncSession,
    company_id: uuid.UUID,
    category: str,
    subcategory: str | None,
    *,
    characteristics: dict | None = None,
    moq_units: int = 1,
) -> CategoryAdmissionOut:
    """Отчёт о допуске по документам компании. Используется публикацией товара."""
    documents = await _company_documents(db, company_id)
    report = evaluate_admission(
        category=category,
        subcategory=subcategory,
        characteristics=characteristics or {},
        documents=documents,
        moq_units=moq_units,
    )
    return CategoryAdmissionOut(
        category=report.category,
        subcategory=report.subcategory,
        state=report.state,
        state_label=report.state_label,
        supported=report.supported,
        profile_title=report.profile_title,
        summary=report.summary,
        requirements=[
            {
                "code": item.code,
                "title": item.title,
                "legal_reference": item.legal_reference,
                "blocking": item.blocking,
                "state": item.state,
                "state_label": item.state_label,
                "seller_hint": item.seller_hint,
                "buyer_note": item.buyer_note,
                "document_ids": item.document_ids,
            }
            for item in report.requirements
        ],
        advisories=report.advisories,
        blocking_open=report.blocking_open,
        blocking_message=report.blocking_message,
        checked_at=report.checked_at,
    )


async def _notify_company(db: AsyncSession, company_id: uuid.UUID, message: str) -> None:
    """Сообщить участникам компании, что доказательство допуска изменилось."""
    user_ids = (
        await db.execute(
            text("SELECT user_id FROM auth.company_members WHERE company_id = :cid"), {"cid": company_id}
        )
    ).scalars().all()
    for user_id in user_ids:
        await notify(db, user_id, message, "document_verification_changed")


def admission_audit_payload(admission: CategoryAdmissionOut) -> dict:
    """Снимок допуска для журнала: какие доказательства учтены при публикации."""
    return {
        "state": admission.state,
        "supported": admission.supported,
        "profile": admission.profile_title,
        "blocking_open": admission.blocking_open,
        "requirements": [
            {"code": item.code, "state": item.state, "documents": [str(doc) for doc in item.document_ids]}
            for item in admission.requirements
        ],
    }


@router.get("/companies/{company_id}/documents", response_model=list[DocumentOut])
async def list_documents(
    company_id: uuid.UUID,
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await require_company_seller(company_id, user, db)
    return await _company_documents(db, company_id)


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
    delete_object(document.file_key)
    await db.delete(document)
    if was_verified:
        # Доказательство исчезло: опубликованные товары нужно проверить заново.
        await _notify_company(
            db,
            company_id,
            f"Документ «{document_name}» удалён и больше не подтверждает допуск для «{scope}». "
            "Проверьте опубликованные товары: публикация может быть отклонена.",
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
    await require_marketplace_admin(user, db)
    document = await db.get(Document, document_id)
    if document is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Документ не найден")
    if data.decision == "verified":
        profile = match_profile(data.scope_category or "", data.scope_subcategory)
        if profile is not None and not profile.supported:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                detail="Категория не поддерживается прототипом: подтверждение допуска невозможно",
            )

    previous_status = document.verification_status
    document.verification_status = data.decision
    document.scope_category = (data.scope_category or document.scope_category or None)
    document.scope_subcategory = (data.scope_subcategory or document.scope_subcategory or None)
    document.valid_until = data.valid_until
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
        permission="marketplace_admin",
        decision="approved" if data.decision == "verified" else "rejected",
        payload={
            "document_id": str(document.id),
            "decision": data.decision,
            "previous_status": previous_status,
            "scope_category": document.scope_category,
            "scope_subcategory": document.scope_subcategory,
            "valid_until": document.valid_until.isoformat() if document.valid_until else None,
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
    if data.decision != "verified":
        scope = document.scope_category or "категории без указанной области действия"
        decision_label = "Не соответствует" if data.decision == "rejected" else "Проверка снята"
        await _notify_company(
            db,
            document.company_id,
            f"Документ «{document.name}»: статус «{decision_label}». Он больше не подтверждает допуск "
            f"для «{scope}». Загрузите документ заново или уточните область действия.",
        )
    await db.commit()
    await db.refresh(document)
    return document


@router.get("/admin/documents/pending", response_model=list[PendingDocumentOut])
async def pending_documents(
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    limit: int = Query(default=50, ge=1, le=200),
):
    """Очередь проверки документов для администратора площадки."""
    await require_marketplace_admin(user, db)
    rows = (
        await db.execute(
            text(
                "SELECT d.id, d.company_id, d.name, d.document_type, d.file_key, d.content_type, "
                "d.verification_status, d.scope_category, d.scope_subcategory, d.valid_until, "
                "d.verified_by_user_id, d.verified_at, d.verification_note, d.created_at, "
                "c.display_name AS company_display_name "
                "FROM marketplace.documents d "
                "JOIN auth.companies c ON c.id = d.company_id "
                "WHERE d.verification_status = 'unverified' "
                "ORDER BY d.created_at DESC LIMIT :limit"
            ),
            {"limit": limit},
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
        return CategoryRequirementsOut(
            category=category,
            subcategory=subcategory,
            profile_title=None,
            supported=True,
            summary="Для этой категории обязательные доказательства в прототипе не заданы.",
            checklist=[],
            advisories=[],
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
