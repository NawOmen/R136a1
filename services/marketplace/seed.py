"""Демо-данные маркетплейса для локальной разработки.

Создаёт адрес доставки для покупателя, а производственный профиль,
Capability Passport и товары — для отдельной компании-производителя.
"""

import asyncio
import os
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import select, text

from app.database import SessionLocal
from app.models import CapabilityPassport, DeliveryAddress, Document, Product, ProductionProfile

BUYER_COMPANY_NAME = "ООО «Демо-Кофе»"
SELLER_COMPANY_NAME = "ООО «СтаканОпт Демо»"
SELLER_USER_EMAIL = os.getenv("SEED_SELLER_EMAIL", "seller@demo.ru")


async def seed() -> None:
    async with SessionLocal() as db:
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
                text("SELECT id FROM auth.users WHERE email = :email"),
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
                        address="г. Москва, ул. Демонстрационная, д. 1",
                        city="Москва",
                        region="г. Москва",
                        is_default=True,
                    )
                )

        if await db.get(ProductionProfile, seller_company_id) is None:
            db.add(
                ProductionProfile(
                    company_id=seller_company_id,
                    production_site_address="Свердловская область, г. Екатеринбург, ул. Демонстрационная, д. 2",
                    region="Свердловская область",
                    about="Производство брендированных бумажных стаканов для горячих напитков.",
                )
            )

        if await db.get(CapabilityPassport, seller_company_id) is None:
            db.add(
                CapabilityPassport(
                    company_id=seller_company_id,
                    technologies=["высечка бумажных стаканов", "ламинирование PE-покрытием"],
                    details={
                        "business_kind": "both", "product_types": "Бумажные стаканы 150–600 мл",
                        "complexity": "Флексопечать, макет согласовывается до производства",
                        "material_grades": "Крафт-картон с PE-покрытием",
                        "limitations": "PLA и нестандартные формы требуют отдельного согласования",
                        "packaging": "Короба по 500 шт., паллетирование по запросу",
                        "delivery": "Самовывоз или перевозчик покупателя; доставка оплачивается отдельно",
                        "quality_control": "Выборочная проверка размеров и герметичности",
                        "trial_batch": "Непечатные образцы по запросу; цена и срок согласуются отдельно",
                    },
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
        if product is None:
            db.add(
                Product(
                    company_id=seller_company_id,
                    created_by_user_id=user_id,
                    name="Стакан 400 мл PE",
                    category="бумажные стаканы",
                    characteristics={"volume_ml": 400, "coating": "PE", "material": "крафт-картон 300 г/м²"},
                    price_rub=11.2,
                    moq_units=20000,
                    lead_time_days=9,
                    is_published=True,
                )
            )
            db.add(
                Product(
                    company_id=seller_company_id,
                    created_by_user_id=user_id,
                    name="Стакан 350 мл PE",
                    category="бумажные стаканы",
                    characteristics={"volume_ml": 350, "coating": "PE"},
                    price_rub=10.5,
                    moq_units=15000,
                    lead_time_days=8,
                    is_published=True,
                )
            )

        await _seed_category_documents(db, seller_company_id)

        await db.commit()


DEMO_DOCUMENTS = (
    {
        "name": "Декларация о соответствии ТР ТС 005/2011 (синтетический документ)",
        "document_type": "declaration",
        "verification_note": "Синтетический демонстрационный документ, проверен для стаканов 150–600 мл.",
    },
    {
        "name": "Протокол испытаний контакта с пищевой продукцией (синтетический документ)",
        "document_type": "test_report",
        "verification_note": "Синтетический демонстрационный документ: материал и PE-покрытие.",
    },
)


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
    for item in DEMO_DOCUMENTS:
        existing = (
            await db.execute(
                select(Document).where(
                    Document.company_id == seller_company_id, Document.name == item["name"]
                )
            )
        ).scalars().first()
        if existing is not None:
            continue
        db.add(
            Document(
                company_id=seller_company_id,
                created_by_user_id=admin_id,
                name=item["name"],
                document_type=item["document_type"],
                file_key=f"demo/synthetic/{uuid.uuid4()}",
                content_type="application/pdf",
                verification_status="verified",
                scope_category="Упаковка и тара",
                scope_subcategory="Бумажные стаканы",
                valid_until=valid_until,
                verified_by_user_id=admin_id,
                verified_at=datetime.now(timezone.utc),
                verification_note=item["verification_note"],
            )
        )


if __name__ == "__main__":
    asyncio.run(seed())
