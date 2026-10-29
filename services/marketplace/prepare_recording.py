"""Начальные условия только выделенной синтетической базы porukam_recording."""
import asyncio
import os
from copy import deepcopy
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import select, text
from sqlalchemy.engine import make_url

from app.config import settings
from app.database import SessionLocal
from app.models import CapabilityPassport, Need, Product

NAME = "Болт М8×40, класс 8.8"


async def prepare():
    if make_url(settings.database_url).database != "porukam_recording" or os.getenv("ENABLE_DEMO_SEED") != "true":
        raise ValueError("Подготовка разрешена только в отдельной синтетической базе porukam_recording")
    from app.category_runtime import current_registry_context
    from app.category_registry import resolve_category
    from app.api.products import publish_product
    from app.deps import CurrentUser
    from app.schemas import PublishIn
    from seed_assortment import storefront_product_id
    async with SessionLocal() as db, current_registry_context(db):
        people = (await db.execute(text(
            "SELECT u.id, u.email, c.id, c.inn FROM auth.users u JOIN auth.company_members m ON m.user_id=u.id "
            "JOIN auth.companies c ON c.id=m.company_id WHERE u.email IN ('buyer@show.porukam.ru','seller@show.porukam.ru')"
        ))).all()
        if len(people) != 2 or any(not row[3].startswith("000") for row in people):
            raise ValueError("Нужны два отдельных синтетических аккаунта записи")
        buyer = next(row for row in people if row[1].startswith("buyer@"))
        seller = next(row for row in people if row[1].startswith("seller@"))
        await db.execute(text("UPDATE auth.company_members SET can_buy=true, can_sell=false WHERE user_id=:uid"), {"uid":buyer[0]})
        await db.execute(text("UPDATE auth.company_members SET can_buy=false, can_sell=true WHERE user_id=:uid"), {"uid":seller[0]})
        if await db.scalar(select(Need.id).where(Need.company_id == buyer[2]).limit(1)):
            raise ValueError("Репетиция уже началась. Восстановите baseline, не меняйте остатки поверх сделки")
        product = await db.get(Product, storefront_product_id(seller[2], "bolt"))
        if product is None:
            raise ValueError("Сначала запустите штатные миграции и синтетическое наполнение")
        duplicates = (await db.scalars(select(Product).where(
            Product.company_id == seller[2], Product.name == NAME, Product.id != product.id))).all()
        for old in duplicates:
            await publish_product(old.id, PublishIn(published=False), CurrentUser(seller[0]), db)
            old.name = "Болт М8×40 — архивная карточка"
        product.price_rub = Decimal("4")
        product.price_tiers = []
        product.stock_units = 40000
        product.stock_updated_at = datetime.now(timezone.utc)
        product.moq_units = 200
        product.lead_time_days = 2
        passport = await db.get(CapabilityPassport, seller[2])
        if passport is None:
            raise ValueError("Нет паспорта производителя")
        leaf = resolve_category("Строительство", "Крепёж")
        details = deepcopy(passport.details or {})
        scopes = details.get("category_scopes", [])
        for scope in scopes:
            if scope.get("category_id") == leaf["id"] and "болт" in scope.get("characteristics", {}).get("product_kind", []):
                scope["max_units"] = max(40000, scope.get("max_units") or 0)
        passport.details = {**details, "category_scopes": scopes}
        await db.flush()
        # Штатная публикация проверяет предметный допуск, компанию и аудит.
        await publish_product(product.id, PublishIn(published=True), CurrentUser(seller[0]), db)
        await db.commit()
        print(f"Готово: {NAME}; 4 ₽/шт.; свободный остаток 40 000 шт.; срок 2 дня.")
        print("Синтетическая цена для записи, не рыночное предложение. Потребность и заказ не созданы.")


if __name__ == "__main__":
    asyncio.run(prepare())
