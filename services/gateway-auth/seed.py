"""Синтетические демо-аккаунты и проверенная компания для локальной разработки.

Запуск (после миграций): python seed.py
Пароли берутся из переменных окружения SEED_ADMIN_PASSWORD / SEED_DEMO_PASSWORD
(по умолчанию admin123 / demo123 — только для локальной демонстрации).
"""

import asyncio
import os

from sqlalchemy import select, text

from app.database import SessionLocal
from app.models import Company, CompanyMember, User
from app.security import hash_password


async def seed() -> None:
    admin_email = os.getenv("SEED_ADMIN_EMAIL", "admin@demo.ru")
    admin_password = os.getenv("SEED_ADMIN_PASSWORD", "admin123")
    demo_email = os.getenv("SEED_DEMO_EMAIL", "demo@demo.ru")
    demo_password = os.getenv("SEED_DEMO_PASSWORD", "demo123")

    async with SessionLocal() as db:
        await db.execute(text("CREATE SCHEMA IF NOT EXISTS auth"))
        await db.commit()

        admin = (await db.execute(select(User).where(User.email == admin_email))).scalar_one_or_none()
        if admin is None:
            db.add(
                User(
                    last_name="Админ",
                    first_name="Администратор",
                    middle_name=None,
                    email=admin_email,
                    password_hash=hash_password(admin_password),
                    is_marketplace_admin=True,
                )
            )

        demo = (await db.execute(select(User).where(User.email == demo_email))).scalar_one_or_none()
        if demo is None:
            demo = User(
                last_name="Смирнов",
                first_name="Алексей",
                middle_name="Петрович",
                email=demo_email,
                password_hash=hash_password(demo_password),
                phone="+7 900 000-00-00",
            )
            db.add(demo)
            await db.flush()

            company = Company(
                full_name="Общество с ограниченной ответственностью «Демо-Кофе»",
                display_name="ООО «Демо-Кофе»",
                legal_form="ООО",
                inn="7712345678",
                ogrn="1167746123456",
                kpp="770101001",
                legal_address="г. Москва, ул. Демонстрационная, д. 1",
                country="RU",
                verification_status="verified",
            )
            db.add(company)
            await db.flush()

            db.add(
                CompanyMember(
                    user_id=demo.id,
                    company_id=company.id,
                    can_buy=True,
                    can_sell=True,
                    is_admin=True,
                )
            )

        await db.commit()


if __name__ == "__main__":
    asyncio.run(seed())
