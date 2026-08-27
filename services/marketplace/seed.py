"""Демо-данные маркетплейса для локальной разработки.

Создаёт адрес доставки, производственный профиль, Capability Passport и
опубликованные товары для проверенной демо-компании из gateway-auth.
"""

import asyncio
import os

from sqlalchemy import select, text

from app.database import SessionLocal
from app.models import CapabilityPassport, DeliveryAddress, Product, ProductionProfile

DEMO_COMPANY_NAME = "ООО «Демо-Кофе»"
DEMO_USER_EMAIL = os.getenv("SEED_DEMO_EMAIL", "demo@demo.ru")


async def seed() -> None:
    async with SessionLocal() as db:
        row = (await db.execute(text("SELECT id FROM auth.companies WHERE display_name = :n"), {"n": DEMO_COMPANY_NAME})).first()
        if row is None:
            return
        company_id = row[0]

        user_row = (await db.execute(text("SELECT id FROM auth.users WHERE email = :e"), {"e": DEMO_USER_EMAIL})).first()
        user_id = user_row[0] if user_row else None

        addr = (await db.execute(select(DeliveryAddress).where(DeliveryAddress.company_id == company_id))).scalar_one_or_none()
        if addr is None:
            db.add(
                DeliveryAddress(
                    company_id=company_id,
                    address="г. Москва, ул. Демонстрационная, д. 1",
                    city="Москва",
                    region="г. Москва",
                    is_default=True,
                )
            )

        if await db.get(ProductionProfile, company_id) is None:
            db.add(
                ProductionProfile(
                    company_id=company_id,
                    production_site_address="г. Москва, ул. Демонстрационная, д. 1",
                    region="г. Москва",
                    about="Производство брендированных бумажных стаканов для горячих напитков.",
                )
            )

        if await db.get(CapabilityPassport, company_id) is None:
            db.add(
                CapabilityPassport(
                    company_id=company_id,
                    technologies=["высечка бумажных стаканов", "ламинирование PE-покрытием"],
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

        product = (await db.execute(select(Product).where(Product.company_id == company_id))).scalar_one_or_none()
        if product is None:
            db.add(
                Product(
                    company_id=company_id,
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
                    company_id=company_id,
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

        await db.commit()


if __name__ == "__main__":
    asyncio.run(seed())
