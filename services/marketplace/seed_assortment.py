"""Additive fixture loader; existing catalogue entries and stock are never reset.

Synthetic demo data only: assortment, group pictograms drawn by the team
(no licensed assets) and linked deal stories with event-derived statuses.
"""
import struct
import uuid
import zlib
from pathlib import Path
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import select, text

from app.assortment import ASSORTMENT
from app.category_admission import evaluate_admission
from app.models import CapabilityPassport, Deal, DealExecutionEvent, Need, Offer, Product, ProductImage, ProductPriceObservation
from app.commerce import product_specification_hash

NAMESPACE = uuid.UUID("76fba05a-d0fb-4eeb-9b0f-90afeb845a32")

GROUP_COLORS = {
    "Упаковка и тара": (196, 132, 62),
    "Сырьё и материалы": (96, 140, 120),
    "Оборудование": (110, 120, 135),
    "Строительство": (150, 110, 90),
    "Продукты питания": (160, 135, 70),
    "Товары для бизнеса": (140, 100, 80),
    "Электроника": (90, 120, 170),
    "Транспорт и логистика": (80, 140, 160),
    "Полиграфия и реклама": (150, 95, 140),
    "Услуги производства": (120, 130, 100),
    "Медицина и гигиена": (100, 150, 155),
    "Другое": (120, 120, 120),
}

LEGACY_COMPARISON_KEYS = ("box", "bolt", "jacket", "desk", "tile", "cable", "lamp")
LEGACY_PRODUCT_PHOTO_KEYS = ("box", "jacket", "cable", "drinking_water")
PRODUCT_PHOTO_KEYS = (
    "box", "bag", "film", "cardboard_sheet", "steel_plate_2", "fabric",
    "retail_display", "warehouse_trolley", "tile", "bolt", "drinking_water",
    "rice_pack", "jacket", "office_paper_a4", "cleaning_bucket_10", "cable",
    "office_keyboard", "shipping_cage", "label_50", "laser_part_2",
)
STOREFRONT_VERSION = "storefront-v1"
STOREFRONT_ADDITIONAL_KEYS = tuple(key for key in PRODUCT_PHOTO_KEYS if key not in LEGACY_PRODUCT_PHOTO_KEYS)


def storefront_product_id(company_id, key):
    """Keep the four published fixture IDs; never reuse an older seller draft."""
    suffix = key if key in LEGACY_PRODUCT_PHOTO_KEYS else f"{STOREFRONT_VERSION}:{key}"
    return uuid.uuid5(NAMESPACE, f"{company_id}:{suffix}")


def comparison_assortment():
    """Preserve the second seller's old IDs, then cover every remaining leaf."""
    items = [row for row in ASSORTMENT if row[0] in LEGACY_COMPARISON_KEYS]
    covered = {(row[2], row[3]) for row in items}
    for row in ASSORTMENT:
        leaf = (row[2], row[3])
        if leaf not in covered:
            items.append(row)
            covered.add(leaf)
    return items


def assortment_scope(row, seller_index=0):
    from app.category_registry import resolve_category
    from app.category_units import order_unit
    _, _, category, subcategory, _, attributes, _, moq, stock, _ = row
    leaf = resolve_category(category, subcategory)
    return {"category_id": leaf["id"], "profile_version": leaf["technical_profile"]["version"],
            "unit": order_unit(attributes), "min_units": moq,
            "max_units": stock // (seller_index + 1),
            "characteristics": {key: [value] for key, value in attributes.items() if key != "unit"}}


def _png_chunk(chunk_type: bytes, data: bytes) -> bytes:
    chunk = chunk_type + data
    return struct.pack(">I", len(data)) + chunk + struct.pack(">I", zlib.crc32(chunk) & 0xFFFFFFFF)


def group_pictogram(family: str, size: int = 96) -> bytes:
    """Схематическая иллюстрация группы товаров собственного изготовления:
    цветное поле с рамкой. Не фотография и не лицензированный актив."""
    rgb = GROUP_COLORS.get(family, (120, 120, 120))
    light = tuple(min(255, channel + 45) for channel in rgb)
    raw = bytearray()
    for y in range(size):
        raw.append(0)
        for x in range(size):
            if x < 4 or y < 4 or x >= size - 4 or y >= size - 4:
                raw.extend((255, 255, 255))
            elif ((x // 12) + (y // 12)) % 2 == 0:
                raw.extend(rgb)
            else:
                raw.extend(light)
    header = struct.pack(">IIBBBBB", size, size, 8, 2, 0, 0, 0)
    return (b"\x89PNG\r\n\x1a\n" + _png_chunk(b"IHDR", header)
            + _png_chunk(b"IDAT", zlib.compress(bytes(raw))) + _png_chunk(b"IEND", b""))


async def seed_assortment(db):
    created = []
    for seller_index, title in enumerate(("ООО «Урал Комплект»", "ООО «Регион Поставка»")):
        row = (await db.execute(text(
            "SELECT c.id, m.user_id FROM auth.companies c JOIN auth.company_members m ON m.company_id = c.id "
            "WHERE c.display_name = :title AND m.can_sell = true AND m.is_admin = true ORDER BY m.user_id LIMIT 1"
        ), {"title": title})).first()
        if row is None:
            continue
        company_id, user_id = row
        items = ASSORTMENT if seller_index == 0 else comparison_assortment()
        passport = await db.get(CapabilityPassport, company_id)
        if passport is None:
            passport = CapabilityPassport(company_id=company_id, details={
                "category_scopes": [assortment_scope(row, seller_index) for row in items],
                "business_kind": "both", "product_types": "Товары и услуги для снабжения бизнеса",
                "delivery": "Самовывоз; стоимость перевозчика согласовывается отдельно",
                "limitations": "Точные характеристики и доступность указаны в карточке товара",
            }, technologies=[], materials=[], equipment=[], certifications=[], size_ranges={},
                delivery_regions=["Россия"], completed_order_types=[], min_order_units=1)
            db.add(passport)
        for row in items:
            key, family, category, subcategory, name, attributes, price, moq, stock, lead = row
            product_id = uuid.uuid5(NAMESPACE, f"{company_id}:{key}")
            if await db.get(Product, product_id) is not None:
                continue
            # No fabricated verification: regulated products stay in seller drafts
            # until their own documents have been checked through the normal workflow.
            report = evaluate_admission(category=category, subcategory=subcategory,
                                        characteristics=attributes, moq_units=moq, documents=[])
            product = Product(id=product_id, company_id=company_id, created_by_user_id=user_id,
                name=name, category=category, subcategory=subcategory, characteristics=attributes,
                price_rub=Decimal(str(price)) * (Decimal("1.04") if seller_index else Decimal(1)),
                price_tiers=[], moq_units=moq, lead_time_days=lead + seller_index,
                stock_units=stock // (seller_index + 1), stock_updated_at=datetime.now(timezone.utc),
                is_published=report.blocking_open == 0)
            db.add(product)
            created.append(product)
            # Extend scope only for this newly inserted fixture. Existing scope edits
            # and deliberately removed scope entries survive subsequent seed runs.
            details = passport.details or {}
            existing_scopes = list(details.get("category_scopes", []))
            scope = assortment_scope(row, seller_index)
            if scope not in existing_scopes:
                passport.details = {**details, "category_scopes": [*existing_scopes, scope]}
            await db.flush()
            if product.is_published:
                db.add(ProductPriceObservation(product_id=product.id, category=category,
                    unit_price_rub=product.price_rub, specification_hash=product_specification_hash(product)))
    await seed_product_images(db)
    await seed_seller_stories(db)
    return created


async def seed_storefront_assortment(db):
    """Create the separately versioned public fixtures after the base assortment."""
    row = (await db.execute(text(
        "SELECT c.id, m.user_id FROM auth.companies c JOIN auth.company_members m ON m.company_id = c.id "
        "WHERE c.display_name = 'ООО «Урал Комплект»' AND m.can_sell = true AND m.is_admin = true "
        "ORDER BY m.user_id LIMIT 1"
    ))).first()
    if row is None:
        return []
    company_id, user_id = row
    created = []
    for row in ASSORTMENT:
        key, _family, category, subcategory, name, attributes, price, moq, stock, lead = row
        if key not in STOREFRONT_ADDITIONAL_KEYS:
            continue
        product_id = storefront_product_id(company_id, key)
        if await db.get(Product, product_id) is not None:
            continue
        # This separate, versioned fixture does not promote an existing
        # assortment draft: deliberate unpublication is not distinguishable
        # from an old unpublished seed entry and must survive every rerun.
        product = Product(id=product_id, company_id=company_id, created_by_user_id=user_id,
            external_id=f"synthetic-{STOREFRONT_VERSION}:{key}",
            sources=[{"label": "Спецификация товара", "reference": f"synthetic_seed:{STOREFRONT_VERSION}:{key}"}],
            name=name, category=category, subcategory=subcategory, characteristics=dict(attributes),
            price_rub=Decimal(str(price)), price_tiers=[], moq_units=moq, lead_time_days=lead,
            stock_units=stock, stock_updated_at=datetime.now(timezone.utc), is_published=False)
        db.add(product)
        created.append(product)
        await db.flush()
    await seed_product_photos(db)
    return created


async def seed_product_images(db):
    """По одной схематической иллюстрации на группу первому товару продавца №1.

    Пропускается мягко, если файловое хранилище недоступно: каталог важнее картинок.
    """
    from app.storage import upload_object

    await seed_product_photos(db)
    pictured = set()
    for key, family, _category, _subcategory, _name, _attributes, _price, _moq, _stock, _lead in ASSORTMENT:
        if family in pictured:
            continue
        pictured.add(family)
        product_id = uuid.uuid5(NAMESPACE, f"{await _first_seller_id(db)}:{key}")
        product = await db.get(Product, product_id)
        if product is None:
            continue
        existing = await db.scalar(select(ProductImage.id).where(
            ProductImage.product_id == product.id, ProductImage.position == 0))
        if existing is not None:
            continue
        try:
            file_key = f"products/{product.id}/seed-{key}.png"
            upload_object(file_key, group_pictogram(family), "image/png")
        except Exception:
            continue
        db.add(ProductImage(product_id=product.id, file_name=f"Схематическая иллюстрация: {family}.png",
                            file_key=file_key, content_type="image/png", position=0))
        await db.flush()


async def seed_product_photos(db):
    """Attach authored product illustrations only to unchanged synthetic SKUs.

    Upgrade our own old pictograms; preserve supplier uploads, edited products,
    existing image IDs and all commercial data. A storage failure is retryable.
    """
    from app.storage import upload_object

    seller_id = await _first_seller_id(db)
    if seller_id == "missing-seller":
        return
    for key, _family, category, subcategory, name, attributes, *_ in ASSORTMENT:
        if key not in PRODUCT_PHOTO_KEYS:
            continue
        product_id = storefront_product_id(seller_id, key)
        product = await db.get(Product, product_id)
        if product is None or (product.name, product.category, product.subcategory, product.characteristics) != (name, category, subcategory, attributes):
            continue
        images = list((await db.scalars(select(ProductImage).where(
            ProductImage.product_id == product_id))).all())
        photo_key = f"products/{product_id}/seed-photo-{key}.webp"
        if any(image.file_key == photo_key for image in images):
            continue
        old_key = f"products/{product_id}/seed-{key}.png"
        if any(not (image.file_key == old_key and image.file_name.startswith("Схематическая иллюстрация:")) for image in images):
            continue
        asset = Path(__file__).parent / "seed_media" / f"{key}.webp"
        if not asset.is_file():
            continue
        try:
            upload_object(photo_key, asset.read_bytes(), "image/webp")
        except Exception:
            continue
        image = images[0] if images else ProductImage(product_id=product_id, position=0)
        image.file_name = f"Иллюстрация товара: {name}.webp"
        image.file_key = photo_key
        image.content_type = "image/webp"
        if not images:
            db.add(image)
        await db.flush()


async def _first_seller_id(db):
    row = (await db.execute(text(
        "SELECT c.id FROM auth.companies c JOIN auth.company_members m ON m.company_id = c.id "
        "WHERE c.display_name = 'ООО «Урал Комплект»' AND m.can_sell = true AND m.is_admin = true "
        "ORDER BY m.user_id LIMIT 1"
    ))).first()
    return row[0] if row else "missing-seller"


async def seed_seller_stories(db):
    """Связанные истории: открытая потребность, исполненная и отменённая сделки.

    Суммы посчитаны из цен каталога, статусы выставлены событиями исполнения,
    идентификаторы детерминированы — повторный seed ничего не дублирует.
    """
    seller_id = await _first_seller_id(db)
    if seller_id == "missing-seller":
        return
    buyer_row = (await db.execute(text(
        "SELECT c.id, m.user_id FROM auth.companies c JOIN auth.company_members m ON m.company_id = c.id "
        "WHERE c.display_name = 'ООО «Вектор Снабжения»' AND m.can_buy = true ORDER BY m.user_id LIMIT 1"
    ))).first()
    if buyer_row is None:
        return
    buyer_id, buyer_user_id = buyer_row
    seller_user_row = (await db.execute(text(
        "SELECT m.user_id FROM auth.company_members m WHERE m.company_id = :cid AND m.can_sell = true "
        "AND m.is_admin = true ORDER BY m.user_id LIMIT 1"
    ), {"cid": uuid.UUID(str(seller_id))})).first()
    seller_user_id = seller_user_row[0] if seller_user_row else None
    deadline = date.today() + timedelta(days=30)

    open_id = uuid.uuid5(NAMESPACE, "story:open-need")
    if await db.get(Need, open_id) is None:
        db.add(Need(id=open_id, company_id=buyer_id, created_by_user_id=buyer_user_id,
                    category="Строительство", subcategory="Крепёж",
                    characteristics={"unit": "шт", "product_kind": "болт", "material": "сталь"},
                    volume_units=100, budget_rub=Decimal("2000"), deadline_date=deadline,
                    visibility="open_anonymized", status="waiting_for_match",
                    no_match_reason="Не достигнут минимальный объём производителя"))
        await db.flush()

    for key, units, unit_price, deal_status, need_status, offer_status in (
        ("story-fulfilled", 1000, Decimal("12"), "fulfilled", "matched", "selected"),
        ("story-cancelled", 2000, Decimal("5"), "cancelled", "waiting_for_match", "selected"),
    ):
        need_id = uuid.uuid5(NAMESPACE, f"{key}-need")
        need = await db.get(Need, need_id)
        if need is None:
            need = Need(id=need_id, company_id=buyer_id, created_by_user_id=buyer_user_id,
                        category="Строительство", subcategory="Крепёж",
                        characteristics={"unit": "шт", "material": "сталь"},
                        volume_units=units, budget_rub=unit_price * units, deadline_date=deadline,
                        visibility="open_anonymized", status=need_status,
                        no_match_reason=None if need_status == "matched" else "Сделка отменена покупателем")
            db.add(need)
            await db.flush()
        offer_id = uuid.uuid5(NAMESPACE, f"{key}-offer")
        offer = await db.get(Offer, offer_id)
        if offer is None:
            offer = Offer(id=offer_id, need_id=need.id, company_id=uuid.UUID(str(seller_id)),
                          created_by_user_id=seller_user_id, price_rub=unit_price,
                          available_units=units, lead_time_days=2, delivery_cost_rub=Decimal("500"),
                          moq_units=100, price_tiers=[], status=offer_status)
            db.add(offer)
            await db.flush()
        deal_id = uuid.uuid5(NAMESPACE, f"{key}-deal")
        if await db.get(Deal, deal_id) is None:
            db.add(Deal(id=deal_id, offer_id=offer.id, need_id=need.id,
                        buyer_company_id=buyer_id, seller_company_id=uuid.UUID(str(seller_id)),
                        performed_by_user_id=buyer_user_id, units=units, unit_price_rub=unit_price,
                        delivery_price_rub=Decimal("500"),
                        total_price_rub=unit_price * units + Decimal("500"), status=deal_status))
            await db.flush()
        # События исполнения: аналитика считает суммы из них, а не из статуса.
        event_kind, event_note = (("acceptance", "Покупатель принял поставку полностью")
                                  if deal_status == "fulfilled"
                                  else ("cancellation", "Покупатель отменил заказ до отгрузки"))
        event_id = uuid.uuid5(NAMESPACE, f"{key}-execution")
        if await db.get(DealExecutionEvent, event_id) is None:
            db.add(DealExecutionEvent(id=event_id, deal_id=deal_id, actor_company_id=buyer_id,
                                      actor_user_id=buyer_user_id,
                                      idempotency_key=uuid.uuid5(NAMESPACE, f"{key}-execution-key"),
                                      kind=event_kind, units=units,
                                      note=event_note, status="confirmed",
                                      decided_by_user_id=buyer_user_id,
                                      decided_at=datetime.now(timezone.utc)))
            await db.flush()
