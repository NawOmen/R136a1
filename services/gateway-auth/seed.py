"""Explicit, repeatable synthetic accounts for local development.

Passwords are supplied by the operator. Existing passwords and memberships are
never overwritten. See docs/synthetic-assortment.md for data provenance.
"""
import asyncio
import os
import uuid

from sqlalchemy import select

from app.database import SessionLocal
from app.models import Company, CompanyMember, User
from app.security import hash_password

NAMESPACE = uuid.UUID("63fbb020-7627-4b46-baa9-6cdd823cbe52")


async def seed() -> None:
    admin_password = os.environ["SEED_ADMIN_PASSWORD"]
    buyer_password = os.environ["SEED_DEMO_PASSWORD"]
    seller_password = os.environ["SEED_SELLER_PASSWORD"]
    second_password = os.getenv("SEED_SELLER2_PASSWORD", seller_password)
    if any(len(value) < 16 for value in (admin_password, buyer_password, seller_password, second_password)):
        raise ValueError("Пароли начальных аккаунтов должны содержать минимум 16 символов")
    async with SessionLocal() as db:
        async def account(email, password, first, last, *, admin=False):
            user = await db.scalar(select(User).where(User.email == email))
            if user is None:
                user = User(id=uuid.uuid5(NAMESPACE, f"user:{email}"), email=email,
                            password_hash=hash_password(password), first_name=first, last_name=last,
                            is_marketplace_admin=admin)
                db.add(user)
                await db.flush()
            return user

        await account(os.getenv("SEED_ADMIN_EMAIL", "admin@demo.ru"), admin_password, "Администратор", "Платформы", admin=True)
        buyer = await account(os.getenv("SEED_DEMO_EMAIL", "demo@demo.ru"), buyer_password, "Алексей", "Смирнов")
        seller = await account(os.getenv("SEED_SELLER_EMAIL", "seller@demo.ru"), seller_password, "Сергей", "Иванов")
        second = await account(os.getenv("SEED_SELLER2_EMAIL", "supplier@porukam.test"), second_password, "Мария", "Петрова")

        async def company(key, title, user, *, buy=False, sell=False, legacy=None):
            identity = uuid.uuid5(NAMESPACE, f"company:{key}")
            item = await db.get(Company, identity)
            if item is None and legacy:
                # Only recognize the exact old fixture owned by the configured seed account.
                item = await db.scalar(select(Company).join(CompanyMember).where(
                    Company.display_name.in_([legacy[0], f"ООО «{title}»"]), Company.inn == legacy[1], CompanyMember.user_id == user.id))
                if item is not None:
                    item.display_name = f"ООО «{title}»"
                    item.full_name = f"Общество с ограниченной ответственностью «{title}»"
            if item is None:
                item = Company(id=identity, display_name=f"ООО «{title}»",
                    full_name=f"Общество с ограниченной ответственностью «{title}»", legal_form="ООО",
                    inn={"buyer": "0000000001", "seller": "0000000002", "supplier": "0000000003"}[key],
                    legal_address="Россия, адрес уточняется", country="RU", verification_status="verified")
                db.add(item)
                await db.flush()
            member = await db.scalar(select(CompanyMember).where(CompanyMember.user_id == user.id, CompanyMember.company_id == item.id))
            if member is None:
                db.add(CompanyMember(user_id=user.id, company_id=item.id, can_buy=buy, can_sell=sell, is_admin=True))
        await company("buyer", "Вектор Снабжения", buyer, buy=True, sell=True, legacy=("ООО «Демо-Кофе»", "7712345678"))
        await company("seller", "Урал Комплект", seller, sell=True, legacy=("ООО «СтаканОпт Демо»", "6600000001"))
        await company("supplier", "Регион Поставка", second, sell=True)
        await db.commit()


if __name__ == "__main__":
    asyncio.run(seed())
