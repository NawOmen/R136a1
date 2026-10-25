"""Демо-данные маркетплейса для локальной разработки.

Создаёт адрес доставки для покупателя, а производственный профиль,
Capability Passport и товары — для отдельной компании-производителя.
"""

import asyncio
import io
from pypdf import PdfWriter
import os
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import select, text

from app.database import SessionLocal
from app.models import CapabilityPassport, DeliveryAddress, Document, Product, ProductImage, ProductionProfile

DETAILS = {
    "business_kind": "both",
    "product_types": "Бумажные стаканы 150–600 мл",
    "complexity": "Флексопечать, макет согласовывается до производства",
    "material_grades": "Крафт-картон с PE-покрытием",
    "limitations": "PLA и нестандартные формы требуют отдельного согласования",
    "packaging": "Короба по 500 шт., паллетирование по запросу",
    "delivery": "Самовывоз или перевозчик покупателя; доставка оплачивается отдельно",
    "quality_control": "Выборочная проверка размеров и герметичности",
    "trial_batch": "Непечатные образцы по запросу; цена и срок согласуются отдельно",
}

def synthetic_scopes():
    from app.category_registry import resolve_category
    leaf = resolve_category("Упаковка и тара", "Бумажные стаканы")
    return [{"category_id": leaf["id"], "profile_version": leaf["technical_profile"]["version"],
             "unit": "шт", "min_units": 5000, "max_units": 50000,
             "characteristics": {"material": ["крафт-картон 300 г/м²"], "coating": ["PE"],
                                 "volume_ml": [350,400], "food_contact": [True]}}]


BUYER_COMPANY_NAME = "ООО «Вектор Снабжения»"
SELLER_COMPANY_NAME = "ООО «Урал Комплект»"
SELLER_USER_EMAIL = os.getenv("SEED_SELLER_EMAIL", "seller@demo.ru")


async def seed() -> None:
    if os.getenv("ENABLE_DEMO_SEED", "false").lower() != "true":
        raise RuntimeError("Синтетическое наполнение требует ENABLE_DEMO_SEED=true")
    from app.category_runtime import current_registry_context
    async with SessionLocal() as db, current_registry_context(db):
        seller_row = (
            await db.execute(
                text("SELECT id FROM auth.companies WHERE display_name = :name"),
                {"name": SELLER_COMPANY_NAME},
            )
        ).first()
        if seller_row is None:
            return
        seller_company_id = seller_row[0]

        buyer_row = (
            await db.execute(
                text("SELECT id FROM auth.companies WHERE display_name = :name"),
                {"name": BUYER_COMPANY_NAME},
            )
        ).first()
        user_row = (
            await db.execute(
                text("SELECT id FROM auth.users WHERE email = :email AND account_status = 'active'"),
                {"email": SELLER_USER_EMAIL},
            )
        ).first()
        user_id = user_row[0] if user_row else None

        if buyer_row is not None:
            buyer_company_id = buyer_row[0]
            address = (
                await db.execute(
                    select(DeliveryAddress).where(
                        DeliveryAddress.company_id == buyer_company_id
                    )
                )
            ).scalars().first()
            if address is None:
                db.add(
                    DeliveryAddress(
                        company_id=buyer_company_id,
                        address="г. Москва, ул. Складская, д. 1",
                        city="Москва",
                        region="г. Москва",
                        is_default=True,
                    )
                )

        if await db.get(ProductionProfile, seller_company_id) is None:
            db.add(
                ProductionProfile(
                    company_id=seller_company_id,
                    production_site_address="Свердловская область, г. Екатеринбург, ул. Складская, д. 2",
                    region="Свердловская область",
                    about="Производство брендированных бумажных стаканов для горячих напитков.",
                )
            )

        passport = await db.get(CapabilityPassport, seller_company_id)
        if passport is None:
            db.add(
                CapabilityPassport(
                    company_id=seller_company_id,
                    technologies=["высечка бумажных стаканов", "ламинирование PE-покрытием"],
                    details={**DETAILS, "category_scopes": synthetic_scopes()},
                    equipment=["высекальный пресс", "флексопечатная машина"],
                    materials=["крафт-картон 260–320 г/м²"],
                    size_ranges={"cup_volume_ml": [150, 600]},
                    tolerances="±0,5 мм по диаметру",
                    certifications=["ТР ТС 005/2011"],
                    min_order_units=5000,
                    max_order_units=50000,
                    delivery_regions=["Центральный ФО"],
                    completed_order_types=["стаканы 300–450 мл"],
                )
            )

        product = (
            await db.execute(
                select(Product).where(Product.company_id == seller_company_id)
            )
        ).scalars().first()
        new_products = []
        if product is None:
            new_products.append(
                Product(
                    company_id=seller_company_id,
                    created_by_user_id=user_id,
                    name="Стакан 400 мл PE",
                    category="Упаковка и тара",
                    subcategory="Бумажные стаканы",
                    characteristics={"volume_ml": 400, "coating": "PE", "material": "крафт-картон 300 г/м²", "food_contact": True, "unit": "шт"},
                    price_rub=Decimal("11.2"),
                    moq_units=20000,
                    lead_time_days=9,
                    stock_units=12000,
                    is_published=False,
                )
            )
            new_products.append(
                Product(
                    company_id=seller_company_id,
                    created_by_user_id=user_id,
                    name="Стакан 350 мл PE",
                    category="Упаковка и тара",
                    subcategory="Бумажные стаканы",
                    characteristics={"volume_ml": 350, "coating": "PE", "material": "крафт-картон 300 г/м²", "food_contact": True, "unit": "шт"},
                    price_rub=Decimal("10.5"),
                    moq_units=15000,
                    lead_time_days=8,
                    is_published=False,
                )
            )
            db.add_all(new_products)

        await _seed_category_documents(db, seller_company_id)

        from seed_assortment import COMPARISON_STOREFRONT_KEYS, COMPARISON_UNAVAILABLE_KEYS, PRODUCT_PHOTO_KEYS, seed_assortment, seed_storefront_assortment, storefront_product_id
        created_assortment = await seed_assortment(db)
        created_assortment.extend(await seed_storefront_assortment(db))
        pictured_ids = {storefront_product_id(seller_company_id, key) for key in PRODUCT_PHOTO_KEYS}
        new_products.extend(product for product in created_assortment if product.id in pictured_ids)
        comparison_company_id = await db.scalar(text(
            "SELECT c.id FROM auth.companies c WHERE c.display_name = :name "
            "AND EXISTS (SELECT 1 FROM auth.company_members m WHERE m.company_id = c.id AND m.can_sell = true AND m.is_admin = true)"
        ), {"name": "ООО «Регион Поставка»"})
        if comparison_company_id is not None:
            await _seed_category_documents(db, comparison_company_id)
            new_products.extend(await seed_storefront_assortment(
                db, seller_name="ООО «Регион Поставка»", keys=COMPARISON_STOREFRONT_KEYS,
                price_factor=Decimal("1.04"), unavailable_keys=COMPARISON_UNAVAILABLE_KEYS))
        await _seed_cup_photos(db, seller_company_id, user_id)
        await db.flush()
        # Only newly created fixtures: reruns never republish a seller's draft.
        # The regular handler checks membership, company, specification and evidence,
        # and records the same audit/price event as an interactive publication.
        if user_id is not None:
            from fastapi import HTTPException
            from app.api.products import publish_product
            from app.deps import CurrentUser
            from app.schemas import PublishIn
            for created in new_products:
                # The storefront must not publish a blank card if its authored
                # illustration was not delivered. Existing rows are never promoted
                # on a later rerun, even after a temporary storage failure.
                if await db.scalar(select(ProductImage.id).where(
                    ProductImage.product_id == created.id, ProductImage.content_type == "image/webp",
                    ProductImage.file_name.startswith("Иллюстрация товара:")).limit(1)) is None:
                    continue
                try:
                    await publish_product(created.id, PublishIn(published=True), CurrentUser(created.created_by_user_id or user_id), db)
                except HTTPException as error:
                    if error.status_code not in (403, 409, 422):
                        raise
                    print(f"Карточка «{created.name}» осталась черновиком: {error.detail}")
            await _retire_storefront_food_products(db, seller_company_id, user_id)
        await _seed_production_photo(db, seller_company_id)
        from seed_assortment import seed_synthetic_price_history
        await seed_synthetic_price_history(db)
        await db.commit()


async def _retire_storefront_food_products(db, company_id, user_id) -> None:
    """Withdraw only the two unchanged food fixtures; retain their history."""
    from app.assortment import ASSORTMENT
    from app.api.products import publish_product
    from app.deps import CurrentUser
    from app.schemas import PublishIn
    from seed_assortment import LEGACY_PRODUCT_PHOTO_KEYS, RETIRED_STOREFRONT_KEYS, STOREFRONT_VERSION, storefront_product_id

    for key, _family, category, subcategory, name, attributes, *_ in ASSORTMENT:
        if key not in RETIRED_STOREFRONT_KEYS:
            continue
        product = await db.get(Product, storefront_product_id(company_id, key))
        if product is None or not product.is_published or product.company_id != company_id:
            continue
        if (product.name, product.category, product.subcategory, product.characteristics) != (name, category, subcategory, attributes):
            continue
        if key in LEGACY_PRODUCT_PHOTO_KEYS:
            if product.external_id or product.sources:
                continue
        elif (product.external_id, product.sources) != (
            f"synthetic-{STOREFRONT_VERSION}:{key}",
            [{"label": "Спецификация товара", "reference": f"synthetic_seed:{STOREFRONT_VERSION}:{key}"}],
        ):
            continue
        await publish_product(product.id, PublishIn(published=False), CurrentUser(user_id), db)


async def _seed_production_photo(db, company_id) -> None:
    """Fill only the intact synthetic profile; never replace a supplier image."""
    from pathlib import Path
    from app.storage import upload_object

    profile = await db.get(ProductionProfile, company_id)
    if profile is None:
        return
    key = f"production/{company_id}/synthetic-workshop-v1.webp"
    photo = (profile.photo_file_key, profile.photo_file_name, profile.photo_content_type)
    if any(photo) and photo != (key, "Синтетическое изображение производства.webp", "image/webp"):
        return
    if (profile.about, profile.production_site_address, profile.region) != (
        "Производство брендированных бумажных стаканов для горячих напитков.",
        "Свердловская область, г. Екатеринбург, ул. Складская, д. 2", "Свердловская область",
    ):
        return
    asset = Path(__file__).parent / "seed_media" / "production_workshop.webp"
    if not asset.is_file():
        return
    try:
        await asyncio.to_thread(upload_object, key, asset.read_bytes(), "image/webp")
    except Exception:
        return
    profile.photo_file_key = key
    profile.photo_file_name = "Синтетическое изображение производства.webp"
    profile.photo_content_type = "image/webp"


async def _seed_cup_photos(db, company_id, user_id) -> None:
    """Attach volume-specific illustrations only to intact, image-free legacy cups."""
    from pathlib import Path
    from app.storage import upload_object

    if user_id is None:
        return
    cups = (await db.scalars(select(Product).where(
        Product.company_id == company_id, Product.created_by_user_id == user_id,
        Product.category == "Упаковка и тара", Product.subcategory == "Бумажные стаканы"))).all()
    for volume, price, moq, lead, stock in ((400, "11.2", 20000, 9, 12000), (350, "10.5", 15000, 8, None)):
        name = f"Стакан {volume} мл PE"
        attributes = {"volume_ml": volume, "coating": "PE", "material": "крафт-картон 300 г/м²", "food_contact": True, "unit": "шт"}
        for cup in cups:
            if (cup.name, cup.characteristics, cup.price_rub, cup.moq_units, cup.lead_time_days, cup.stock_units) != (name, attributes, Decimal(price), moq, lead, stock):
                continue
            if await db.scalar(select(ProductImage.id).where(ProductImage.product_id == cup.id).limit(1)) is not None:
                continue
            asset = Path(__file__).parent / "seed_media" / f"paper_cup_{volume}.webp"
            if not asset.is_file():
                continue
            file_key = f"products/{cup.id}/seed-photo-paper-cup-{volume}.webp"
            try:
                await asyncio.to_thread(upload_object, file_key, asset.read_bytes(), "image/webp")
            except Exception:
                continue
            db.add(ProductImage(product_id=cup.id, position=0, file_name=f"Иллюстрация товара: {name}.webp",
                                file_key=file_key, content_type="image/webp"))
            await db.flush()


def storefront_documents():
    """Exact synthetic scopes, selected from the live admission rules; no blanket permit."""
    from app.assortment import ASSORTMENT
    from app.category_admission import match_profile
    from seed_assortment import STOREFRONT_ADDITIONAL_KEYS, STOREFRONT_VERSION

    documents = []
    for key, _family, category, subcategory, _name, attributes, *_ in ASSORTMENT:
        if key not in STOREFRONT_ADDITIONAL_KEYS:
            continue
        profile = match_profile(category, subcategory, attributes)
        if profile is None or not profile.supported:
            continue
        for requirement in profile.requirements:
            documents.append({
                "name": f"Витрина v1: {key} / {requirement.code} (синтетический документ)",
                "document_type": requirement.document_types[0],
                "scope_category": category, "scope_subcategory": subcategory,
                "verification_note": f"Синтетическая проверка точной спецификации. Юридической силы не имеет. synthetic_seed:{STOREFRONT_VERSION}:{key}",
                "confirms": {field: [value] for field, value in attributes.items() if field != "unit"},
                "synthetic_seed": f"{STOREFRONT_VERSION}:{key}",
            })
    return documents


DEMO_DOCUMENTS = (
    {
        "name": "Декларация о соответствии ТР ТС 005/2011 (синтетический документ)",
        "document_type": "declaration",
        "verification_note": "Синтетический демонстрационный документ, проверен для стаканов 150–600 мл.",
        "confirms": {},
    },
    {
        "name": "Протокол испытаний контакта с пищевой продукцией (синтетический документ)",
        "document_type": "test_report",
        "verification_note": "Синтетический демонстрационный документ: материал и PE-покрытие.",
        "confirms": {"material": ["крафт-картон"], "coating": ["PE"]},
    },
    {
        "name": "Декларация упаковки — коробки (синтетический документ)",
        "document_type": "declaration", "scope_category": "Упаковка и тара", "scope_subcategory": "Коробки",
        "verification_note": "Синтетический документ локальной витрины. Юридической силы не имеет.", "confirms": {},
    },
    {
        "name": "Проверка спецификации рабочей куртки (синтетический документ)",
        "document_type": "specification_review", "scope_category": "Товары для бизнеса", "scope_subcategory": "Спецодежда",
        "verification_note": "Синтетическая проверка спецификации. Защитные свойства не заявлены.",
        "confirms": {"composition": ["65% полиэстер, 35% хлопок"], "size": ["52"], "purpose": ["общая рабочая одежда, без защитных свойств"]},
    },
    {
        "name": "Декларация компонентов — кабель (синтетический документ)",
        "document_type": "declaration", "scope_category": "Электроника", "scope_subcategory": "Компоненты",
        "verification_note": "Синтетический документ локальной витрины. Юридической силы не имеет.", "confirms": {},
    },
    {
        "name": "Декларация напитков — вода (синтетический документ)",
        "document_type": "declaration", "scope_category": "Продукты питания", "scope_subcategory": "Напитки",
        "verification_note": "Синтетический документ локальной витрины. Юридической силы не имеет.", "confirms": {},
    },
)


def synthetic_document_pdf(item) -> bytes:
    """A readable local fixture, never a signed certificate or real company file."""
    writer = PdfWriter()
    writer.add_blank_page(width=300, height=200)
    provenance = item.get("synthetic_seed", "legacy-category-document")
    writer.add_metadata({"/Title": item["name"], "/Subject": f"Synthetic local fixture; no legal force; synthetic_seed:{provenance}"})
    stream = io.BytesIO()
    writer.write(stream)
    return stream.getvalue()


async def _seed_category_documents(db, seller_company_id) -> None:
    """Доказательства допуска демо-производителя.

    Загрузка файла сама по себе не даёт допуск: документы отмечены как проверенные
    человеком и имеют область действия, иначе публикация товаров была бы заблокирована.
    """
    admin_row = (
        await db.execute(
            text(
                "SELECT id FROM auth.users WHERE is_marketplace_admin = true "
                "AND account_status = 'active' ORDER BY created_at LIMIT 1"
            )
        )
    ).first()
    admin_id = admin_row[0] if admin_row else None
    valid_until = datetime.now(timezone.utc).date() + timedelta(days=730)
    from app.storage import upload_object
    for item in (*DEMO_DOCUMENTS, *storefront_documents()):
        existing = (
            await db.execute(
                select(Document).where(
                    Document.company_id == seller_company_id, Document.name == item["name"]
                )
            )
        ).scalars().first()
        if existing is not None:
            # Repair only this loader's synthetic fixture objects. Never overwrite
            # an uploaded user document that happens to have the same display name.
            if existing.file_key.startswith("demo/synthetic/"):
                await asyncio.to_thread(upload_object, existing.file_key, synthetic_document_pdf(item), "application/pdf")
            # Демо-документ мог быть загружен до появления подтверждённых
            # характеристик: обновляем их, чтобы чек-лист соответствовал данным.
            if "synthetic_seed" not in item and existing.file_key.startswith("demo/synthetic/") and existing.verification_status == "verified" and existing.confirms != item["confirms"]:
                existing.confirms = item["confirms"]
            continue
        file_key = f"demo/synthetic/{uuid.uuid4()}"
        await asyncio.to_thread(upload_object, file_key, synthetic_document_pdf(item), "application/pdf")
        db.add(
            Document(
                company_id=seller_company_id,
                created_by_user_id=admin_id,
                name=item["name"],
                document_type=item["document_type"],
                file_key=file_key,
                content_type="application/pdf",
                verification_status="verified" if admin_id else "unverified",
                scope_category=item.get("scope_category", "Упаковка и тара"),
                scope_subcategory=item.get("scope_subcategory", "Бумажные стаканы"),
                valid_until=valid_until,
                confirms=item["confirms"],
                verified_by_user_id=admin_id,
                verified_at=datetime.now(timezone.utc) if admin_id else None,
                verification_note=item["verification_note"],
            )
        )


if __name__ == "__main__":
    asyncio.run(seed())
