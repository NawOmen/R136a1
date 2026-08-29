import uuid

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_db
from ..deps import CurrentUser, get_current_user, require_company_admin, require_company_seller
from ..models import Document
from ..schemas import DocumentOut
from ..storage import delete_object, upload_object

router = APIRouter(tags=["documents"])

MAX_SIZE = 25 * 1024 * 1024


@router.get("/companies/{company_id}/documents", response_model=list[DocumentOut])
async def list_documents(
    company_id: uuid.UUID,
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await require_company_seller(company_id, user, db)
    result = await db.execute(
        select(Document).where(Document.company_id == company_id).order_by(Document.created_at.desc())
    )
    return result.scalars().all()


@router.post("/companies/{company_id}/documents", response_model=DocumentOut, status_code=status.HTTP_201_CREATED)
async def upload_document(
    company_id: uuid.UUID,
    name: str = Form(...),
    document_type: str = Form(...),
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
    )
    db.add(document)
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
    delete_object(document.file_key)
    await db.delete(document)
    await db.commit()
