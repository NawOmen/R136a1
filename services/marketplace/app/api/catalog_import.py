"""Local CSV import with explicit preview approval. No external document processing."""
import csv
import hashlib
import io
import json
import uuid
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import ValidationError
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ..category_characteristics import count_user_characteristics
from ..category_profile_snapshot import profile_after_specification_change
from ..category_units import order_unit
from ..database import get_db
from ..deps import CurrentUser, get_current_user, require_company_admin, require_company_seller
from ..models import CatalogImport, Offer, Product, ResourceReservation
from ..money import decimal
from ..resources import lock_company, occupies, reservations
from ..schemas import ProductIn
from ..trust import append_audit_event, record_human_approval

router = APIRouter(tags=["catalog-import"])
MAX_BYTES = 2 * 1024 * 1024
HEADERS = {"Название", "Категория", "Подкатегория", "Цена", "Минимум", "Срок", "Остаток", "Внешний ID", "Ступени"}
REQUIRED = {"Название", "Категория", "Цена", "Минимум", "Срок"}

TIER_LABELS = {"min_units": "Объём ступени", "unit_price_rub": "Цена ступени"}
DIFF_LABELS = {"name": "Название", "category": "Категория", "subcategory": "Подкатегория",
               "price_rub": "Цена", "price_tiers": "Ступени", "moq_units": "Минимум",
               "lead_time_days": "Срок", "stock_units": "Остаток", "characteristics": "Характеристики",
               "sources": "Источники"}


def parse_tiers(cell: str) -> list[dict]:
    """Ступени вида «100:10;200:8,75»: минимальный объём и цена через двоеточие."""
    tiers = []
    for part in cell.split(";"):
        part = part.strip()
        if not part:
            continue
        if ":" not in part:
            raise ValueError("Ступень записывается как «объём:цена», части разделяются точкой с запятой")
        volume, _, price = part.partition(":")
        tiers.append({"min_units": int(volume.strip()), "unit_price_rub": str(Decimal(price.replace(",", ".").strip()))})
    return tiers


def _tier_key(tier: dict) -> tuple:
    return (int(tier.get("min_units")), decimal(tier.get("unit_price_rub")))


def _same_price(first, second) -> bool:
    try:
        return decimal(first) == decimal(second)
    except (TypeError, ValueError, ArithmeticError):
        return first == second


def product_diff(saved: Product, fresh: dict) -> list[dict]:
    """Различия сохранённой карточки и строки файла по значимым полям.
    Деньги сравниваются по значению: 12.0 из Numeric(24,12) равно 12."""
    saved_dump = {"name": saved.name, "category": saved.category, "subcategory": saved.subcategory,
                  "price_rub": saved.price_rub, "moq_units": saved.moq_units,
                  "lead_time_days": saved.lead_time_days, "stock_units": saved.stock_units,
                  "characteristics": saved.characteristics,
                  "price_tiers": [_tier_key(tier) for tier in (saved.price_tiers or [])]}
    fresh_dump = {"name": fresh["name"], "category": fresh["category"], "subcategory": fresh.get("subcategory"),
                  "price_rub": fresh["price_rub"], "moq_units": fresh["moq_units"],
                  "lead_time_days": fresh["lead_time_days"], "stock_units": fresh.get("stock_units"),
                  "characteristics": fresh["characteristics"],
                  "price_tiers": [_tier_key(tier) for tier in (fresh.get("price_tiers") or [])]}
    diff = []
    for field, label in DIFF_LABELS.items():
        if field == "sources":
            continue
        old, new = saved_dump[field], fresh_dump[field]
        same = _same_price(old, new) if field == "price_rub" else old == new
        if not same:
            diff.append({"field": label, "was": _dump(old), "now": _dump(new)})
    return diff


def _dump(value) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)


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
    seen_external_ids = set()
    try:
        for index, row in enumerate(reader, start=2):
            if index > 501:
                raise HTTPException(422, "В одном файле допускается не более 500 товаров")
            try:
                if None in row or any(value is None for value in row.values()):
                    raise ValueError("Количество значений не соответствует заголовку")
                attrs = {key.removeprefix("Характеристика: ").strip(): value.strip()
                         for key, value in row.items() if key.startswith("Характеристика: ") and value.strip()}
                if "" in attrs or count_user_characteristics(
                        attrs, row["Категория"].strip(), (row.get("Подкатегория") or "").strip() or None) > 25:
                    raise ValueError("Допускается до 25 пользовательских характеристик сверх системных и обязательных")
                price = Decimal(row["Цена"].replace(",", ".").strip())
                if not price.is_finite() or price.as_tuple().exponent < -2:
                    raise ValueError("Цена должна быть конечной суммой с точностью до копейки")
                external_id = (row.get("Внешний ID") or "").strip() or None
                if external_id is not None:
                    if len(external_id) > 64:
                        raise ValueError("Внешний ID не длиннее 64 символов")
                    if external_id in seen_external_ids:
                        raise ValueError("Внешний ID повторяется в файле: оставьте одну строку на товар")
                    seen_external_ids.add(external_id)
                tiers = parse_tiers(row.get("Ступени") or "") if "Ступени" in headers else []
                value = ProductIn(name=row["Название"].strip(), category=row["Категория"].strip(),
                    subcategory=row.get("Подкатегория", "").strip() or None, characteristics=attrs,
                    price_rub=price, moq_units=int(row["Минимум"]), lead_time_days=int(row["Срок"]),
                    stock_units=int(row["Остаток"]) if row.get("Остаток", "").strip() else None,
                    price_tiers=tiers, external_id=external_id)
                rows.append({"line": index, "product": value.model_dump(mode="json")})
            except (ValidationError, ValueError, InvalidOperation) as exc:
                message = "; ".join(item["msg"] for item in exc.errors()) if isinstance(exc, ValidationError) else str(exc)
                errors.append({"line": index, "message": message})
    except csv.Error as exc:
        raise HTTPException(422, "Некорректное экранирование значений CSV") from exc
    if not rows and not errors:
        raise HTTPException(422, "Таблица не содержит товаров")
    return rows, errors


def _expected_binding(revisions: dict, product_id: str) -> tuple:
    """Ожидаемое состояние строки из предпросмотра: только полная форма
    {id: {revision, status}}. Неполная привязка отклоняется: иначе показанное
    решение можно обойти старым форматом."""
    entry = (revisions or {}).get(product_id)
    if not isinstance(entry, dict):
        return None, None
    revision = entry.get("revision")
    return (revision if type(revision) is int else None, entry.get("status"))


async def match_rows(db: AsyncSession, company_id: uuid.UUID, rows: list[dict]) -> list[dict]:
    """Сопоставить строки со своими карточками по стабильному внешнему ID.

    Опубликованные вручную условия никогда не перезаписываются автоматически:
    такие строки помечаются и пропускаются при подтверждении.
    """
    matched = []
    for row in rows:
        external_id = row["product"].get("external_id")
        status, note, diff, product_id, product_revision = "new", "", [], None, None
        if external_id:
            saved = await db.scalar(select(Product).where(
                Product.company_id == company_id, Product.external_id == external_id))
            if saved is not None:
                product_id, product_revision = str(saved.id), saved.revision
                if saved.is_published:
                    status, note = "published_skipped", "Карточка опубликована вручную и не перезаписывается импортом"
                else:
                    diff = product_diff(saved, row["product"])
                    if diff:
                        status, note = "changed", "Собственный черновик будет обновлён"
                    else:
                        status, note = "unchanged", "Без изменений: повтор не создаёт дубликат"
        matched.append({**row, "import_status": status, "diff": diff, "note": note,
                        "product_id": product_id, "product_revision": product_revision})
    return matched


@router.post("/companies/{company_id}/catalog-import")
async def import_catalog(company_id: uuid.UUID, file: UploadFile = File(...),
    commit: bool = Form(False), expected_hash: str | None = Form(None), request_key: uuid.UUID | None = Form(None),
    expected_revisions: str | None = Form(None), source_system: str | None = Form(None),
    human_approved: bool = Form(False), user: CurrentUser = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    await require_company_seller(company_id, user, db)
    await require_company_admin(company_id, user, db)
    source_system = (source_system or "").strip()[:64] or None
    content = await file.read(MAX_BYTES + 1)
    if len(content) > MAX_BYTES:
        raise HTTPException(413, "Размер таблицы не должен превышать 2 МБ")
    digest = hashlib.sha256(content).hexdigest()
    try:
        rows, errors = parse_catalog(content)
    except csv.Error as exc:
        raise HTTPException(422, "Не удалось прочитать заголовок CSV") from exc
    if not commit:
        matched = await match_rows(db, company_id, rows)
        return {"content_hash": digest, "rows": matched, "errors": errors, "created_ids": [], "updated_ids": [],
                "source_system": source_system}
    if not human_approved or not request_key or expected_hash != digest:
        raise HTTPException(428, "Подтвердите предпросмотр именно этой версии файла")
    if errors:
        raise HTTPException(422, "Исправьте ошибки всех строк перед импортом")
    await lock_company(db, company_id)
    await db.execute(text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
                     {"key": f"catalog-import:{company_id}:{request_key}"})
    previous = await db.scalar(select(CatalogImport).where(CatalogImport.company_id == company_id, CatalogImport.request_key == request_key))
    if previous:
        if previous.content_hash != digest:
            raise HTTPException(409, "Этот запрос уже использован для другого файла")
        if source_system != (previous.source_system or None):
            raise HTTPException(409, "Этот запрос уже использован с другим источником")
        matched = await match_rows(db, company_id, rows)
        return {"content_hash": digest, "rows": matched, "errors": [], "created_ids": previous.product_ids,
                "updated_ids": previous.updated_ids or [], "import_id": str(previous.id),
                "source_system": previous.source_system}
    try:
        revisions = json.loads(expected_revisions) if expected_revisions else {}
        if not isinstance(revisions, dict):
            raise ValueError("Ожидались привязки вида {id: {revision, status}}")
    except (ValueError, TypeError) as exc:
        raise HTTPException(422, "Некорректные ожидаемые ревизии предпросмотра") from exc
    matched = await match_rows(db, company_id, rows)
    ids, updated, snapshots = [], [], []
    try:
        for row in matched:
            if row["import_status"] in ("unchanged", "published_skipped"):
                continue
            if row["import_status"] == "changed":
                saved = await db.get(Product, uuid.UUID(row["product_id"]), with_for_update=True)
                if saved is None or saved.company_id != company_id or saved.is_published:
                    continue
                exp_revision, exp_status = _expected_binding(revisions, str(saved.id))
                if exp_status != "changed":
                    raise HTTPException(409, "Показанное решение для строки изменилось. Запросите новый preview")
                if exp_revision != saved.revision:
                    raise HTTPException(409, "Карточка изменилась после предпросмотра. Запросите новый preview")
                fresh = row["product"]
                held = sum(item.units for item in await reservations(db, company_id)
                           if item.product_id == saved.id and occupies(item, stock=True))
                if held and (fresh.get("stock_units") is None or fresh["stock_units"] < held):
                    raise HTTPException(409, f"На складе зарезервировано {held} единиц. Сначала согласуйте отмену обязательств")
                if order_unit(fresh["characteristics"]) != order_unit(saved.characteristics):
                    if any(item.product_id == saved.id and occupies(item, stock=True)
                           for item in await reservations(db, company_id)):
                        raise HTTPException(409, "Нельзя менять единицу товара с действующим резервом")
                snapshots.append({"product_id": str(saved.id), "revision": saved.revision,
                                  "profile": saved.category_profile,
                                  "conversion": saved.quantity_conversion,
                                  "stock_updated_at": saved.stock_updated_at.isoformat() if saved.stock_updated_at else None,
                                  "fields": {"name": saved.name, "category": saved.category,
                                             "subcategory": saved.subcategory,
                                             "characteristics": saved.characteristics,
                                             "price_rub": str(saved.price_rub), "price_tiers": saved.price_tiers,
                                             "moq_units": saved.moq_units, "lead_time_days": saved.lead_time_days,
                                             "stock_units": saved.stock_units}})
                fresh_profile = profile_after_specification_change(
                    saved, fresh["category"], fresh.get("subcategory"), fresh["characteristics"])
                saved.name = fresh["name"]
                saved.category = fresh["category"]
                saved.subcategory = fresh.get("subcategory")
                saved.characteristics = fresh["characteristics"]
                saved.price_rub = decimal(fresh["price_rub"])
                saved.price_tiers = fresh.get("price_tiers", [])
                saved.moq_units = fresh["moq_units"]
                saved.lead_time_days = fresh["lead_time_days"]
                saved.stock_units = fresh.get("stock_units")
                if saved.stock_units is not None:
                    saved.stock_updated_at = datetime.now(timezone.utc)
                saved.category_profile = fresh_profile
                saved.quantity_conversion = None
                saved.revision += 1
                updated.append(str(saved.id))
                continue
            product = Product(id=uuid.uuid4(), company_id=company_id, created_by_user_id=user.id,
                is_published=False, **row["product"])
            if product.stock_units is not None:
                product.stock_updated_at = datetime.now(timezone.utc)
            db.add(product)
            ids.append(str(product.id))
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(409, "Карточка с таким внешним ID уже создана параллельным запросом") from exc
    record = CatalogImport(company_id=company_id, request_key=request_key, content_hash=digest,
                           product_ids=ids, updated_ids=updated, updated_snapshots=snapshots,
                           source_system=source_system)
    db.add(record)
    await db.flush()
    await record_human_approval(db, action="catalog_import", entity_type="company", entity_id=company_id,
        actor_user_id=user.id, actor_company_id=company_id, permission="company_admin+seller", decision="approved",
        payload={"content_hash": digest, "count": len(ids), "updated": updated, "source_system": source_system}, explanation="Продавец подтвердил предпросмотр импорта каталога")
    await db.commit()
    return {"content_hash": digest, "rows": matched, "errors": [], "created_ids": ids,
            "updated_ids": updated, "import_id": str(record.id), "source_system": source_system}


@router.post("/companies/{company_id}/catalog-imports/{import_id}/rollback")
async def rollback_catalog_import(company_id: uuid.UUID, import_id: uuid.UUID,
    user: CurrentUser = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """Безопасный откат импорта: удаляет только собственные черновики этого
    импорта и восстанавливает обновлённые черновики из снимков. Опубликованные
    карточки и чужие данные не трогает; при последующих изменениях — 409."""
    await require_company_seller(company_id, user, db)
    await require_company_admin(company_id, user, db)
    await lock_company(db, company_id)
    record = await db.get(CatalogImport, import_id)
    if record is None or record.company_id != company_id:
        raise HTTPException(404, "Импорт не найден")
    conflicted = []
    for snapshot in record.updated_snapshots or []:
        product = await db.get(Product, uuid.UUID(str(snapshot["product_id"])), with_for_update=True)
        if product is None or product.company_id != company_id:
            continue
        if product.is_published or product.revision != snapshot["revision"] + 1:
            conflicted.append(str(snapshot["product_id"]))
    for raw_id in list(record.product_ids or []) + [s["product_id"] for s in record.updated_snapshots or []]:
        product = await db.get(Product, uuid.UUID(str(raw_id)), with_for_update=True)
        if product is None or product.company_id != company_id:
            continue
        held = sum(item.units for item in await reservations(db, company_id)
                   if item.product_id == product.id and occupies(item, stock=True))
        if held:
            conflicted.append(str(product.id))
            continue
        if str(raw_id) in list(record.product_ids or []):
            referenced = await db.scalar(select(ResourceReservation.id).where(
                ResourceReservation.product_id == product.id).limit(1))
            offer_reference = await db.scalar(select(Offer.id).where(
                Offer.product_id == product.id).limit(1))
            if referenced is not None or offer_reference is not None:
                # Исторические ссылки (в т.ч. released) сохраняются: удаление
                # нарушило бы FK и потеряло историю вместо отката.
                conflicted.append(str(product.id))
    if conflicted:
        raise HTTPException(409, f"Откат невозможен: действуют обязательства или последующие изменения: {', '.join(sorted(set(conflicted)))}")
    deleted, skipped_published, restored = [], [], []
    for raw_id in record.product_ids or []:
        product = await db.get(Product, uuid.UUID(str(raw_id)), with_for_update=True)
        if product is None or product.company_id != company_id:
            continue
        if product.is_published:
            skipped_published.append(str(product.id))
            continue
        await db.delete(product)
        deleted.append(str(product.id))
    for snapshot in record.updated_snapshots or []:
        product = await db.get(Product, uuid.UUID(str(snapshot["product_id"])), with_for_update=True)
        if product is None or product.company_id != company_id or product.is_published:
            continue
        fields = snapshot["fields"]
        product.name = fields["name"]
        product.category = fields["category"]
        product.subcategory = fields.get("subcategory")
        product.characteristics = fields["characteristics"]
        product.price_rub = decimal(fields["price_rub"])
        product.price_tiers = fields.get("price_tiers", [])
        product.moq_units = fields["moq_units"]
        product.lead_time_days = fields["lead_time_days"]
        product.stock_units = fields.get("stock_units")
        product.stock_updated_at = (datetime.fromisoformat(snapshot["stock_updated_at"])
                                    if snapshot.get("stock_updated_at") else None)
        product.category_profile = snapshot.get("profile")
        product.quantity_conversion = snapshot.get("conversion")
        product.revision += 1
        restored.append(str(product.id))
    await append_audit_event(db, event_type="catalog_import_rolled_back", entity_type="company", entity_id=company_id,
        actor_user_id=user.id, actor_company_id=company_id,
        payload={"import_id": str(record.id), "deleted": deleted, "restored": restored},
        explanation="Продавец откатил собственный импорт: удалены черновики, обновлённые карточки восстановлены из снимков.")
    await db.commit()
    return {"import_id": str(record.id), "deleted_ids": deleted, "restored_ids": restored,
            "skipped_published_ids": skipped_published}
