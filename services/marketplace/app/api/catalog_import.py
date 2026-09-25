"""Local CSV import with explicit preview approval. No external document processing."""
import csv
import hashlib
import io
import uuid
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import ValidationError
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_db
from ..deps import CurrentUser, get_current_user, require_company_admin, require_company_seller
from ..models import CatalogImport, Product
from ..schemas import ProductIn
from ..trust import record_human_approval

router = APIRouter(tags=["catalog-import"])
MAX_BYTES = 2 * 1024 * 1024
HEADERS = {"Название", "Категория", "Подкатегория", "Цена", "Минимум", "Срок", "Остаток"}
REQUIRED = {"Название", "Категория", "Цена", "Минимум", "Срок"}


def parse_catalog(content: bytes):
    try:
        source = content.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise HTTPException(422, "Сохраните таблицу как CSV UTF-8") from exc
    reader = csv.DictReader(io.StringIO(source, newline=""), delimiter=";", strict=True)
    headers = reader.fieldnames or []
    if len(set(headers)) != len(headers) or not REQUIRED.issubset(headers):
        raise HTTPException(422, "Нужны уникальные колонки: Название;Категория;Цена;Минимум;Срок")
    if any(header not in HEADERS and not header.startswith("Характеристика: ") for header in headers):
        raise HTTPException(422, "Неизвестная колонка. Для характеристик используйте заголовок «Характеристика: название»")
    rows, errors = [], []
    try:
        for index, row in enumerate(reader, start=2):
            if index > 501:
                raise HTTPException(422, "В одном файле допускается не более 500 товаров")
            try:
                if None in row or any(value is None for value in row.values()):
                    raise ValueError("Количество значений не соответствует заголовку")
                attrs = {key.removeprefix("Характеристика: ").strip(): value.strip()
                         for key, value in row.items() if key.startswith("Характеристика: ") and value.strip()}
                if "" in attrs or len(attrs) > 25:
                    raise ValueError("Допускается до 25 характеристик с непустыми названиями")
                price = Decimal(row["Цена"].replace(",", ".").strip())
                if not price.is_finite() or price.as_tuple().exponent < -2:
                    raise ValueError("Цена должна быть конечной суммой с точностью до копейки")
                value = ProductIn(name=row["Название"].strip(), category=row["Категория"].strip(),
                    subcategory=row.get("Подкатегория", "").strip() or None, characteristics=attrs,
                    price_rub=price, moq_units=int(row["Минимум"]), lead_time_days=int(row["Срок"]),
                    stock_units=int(row["Остаток"]) if row.get("Остаток", "").strip() else None)
                rows.append({"line": index, "product": value.model_dump()})
            except (ValidationError, ValueError, InvalidOperation) as exc:
                message = "; ".join(item["msg"] for item in exc.errors()) if isinstance(exc, ValidationError) else str(exc)
                errors.append({"line": index, "message": message})
    except csv.Error as exc:
        raise HTTPException(422, "Некорректное экранирование значений CSV") from exc
    if not rows and not errors:
        raise HTTPException(422, "Таблица не содержит товаров")
    return rows, errors


@router.post("/companies/{company_id}/catalog-import")
async def import_catalog(company_id: uuid.UUID, file: UploadFile = File(...),
    commit: bool = Form(False), expected_hash: str | None = Form(None), request_key: uuid.UUID | None = Form(None),
    human_approved: bool = Form(False), user: CurrentUser = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    await require_company_seller(company_id, user, db)
    await require_company_admin(company_id, user, db)
    content = await file.read(MAX_BYTES + 1)
    if len(content) > MAX_BYTES:
        raise HTTPException(413, "Размер таблицы не должен превышать 2 МБ")
    digest = hashlib.sha256(content).hexdigest()
    try:
        rows, errors = parse_catalog(content)
    except csv.Error as exc:
        raise HTTPException(422, "Не удалось прочитать заголовок CSV") from exc
    if not commit:
        return {"content_hash": digest, "rows": rows, "errors": errors, "created_ids": []}
    if not human_approved or not request_key or expected_hash != digest:
        raise HTTPException(428, "Подтвердите предпросмотр именно этой версии файла")
    if errors:
        raise HTTPException(422, "Исправьте ошибки всех строк перед импортом")
    await db.execute(text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
                     {"key": f"catalog-import:{company_id}:{request_key}"})
    previous = await db.scalar(select(CatalogImport).where(CatalogImport.company_id == company_id, CatalogImport.request_key == request_key))
    if previous:
        if previous.content_hash != digest:
            raise HTTPException(409, "Этот запрос уже использован для другого файла")
        return {"content_hash": digest, "rows": rows, "errors": [], "created_ids": previous.product_ids}
    ids = []
    for row in rows:
        product = Product(id=uuid.uuid4(), company_id=company_id, created_by_user_id=user.id,
            is_published=False, **row["product"])
        if product.stock_units is not None:
            product.stock_updated_at = datetime.now(timezone.utc)
        db.add(product)
        ids.append(str(product.id))
    db.add(CatalogImport(company_id=company_id, request_key=request_key, content_hash=digest, product_ids=ids))
    await record_human_approval(db, action="catalog_import", entity_type="company", entity_id=company_id,
        actor_user_id=user.id, actor_company_id=company_id, permission="company_admin+seller", decision="approved",
        payload={"content_hash": digest, "count": len(ids)}, explanation="Продавец подтвердил предпросмотр импорта каталога")
    await db.commit()
    return {"content_hash": digest, "rows": rows, "errors": [], "created_ids": ids}
