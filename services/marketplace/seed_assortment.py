"""Additive fixture loader; existing catalogue entries and stock are never reset."""
import uuid
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import select, text

from app.assortment import ASSORTMENT
from app.category_admission import evaluate_admission
from app.models import CapabilityPassport, Product, ProductPriceObservation
from app.commerce import product_specification_hash

NAMESPACE = uuid.UUID("76fba05a-d0fb-4eeb-9b0f-90afeb845a32")


async def seed_assortment(db):
    for seller_index, title in enumerate(("ООО «Урал Комплект»", "ООО «Регион Поставка»")):
        row = (await db.execute(text(
            "SELECT c.id, m.user_id FROM auth.companies c JOIN auth.company_members m ON m.company_id = c.id "
            "WHERE c.display_name = :title AND m.can_sell = true AND m.is_admin = true ORDER BY m.user_id LIMIT 1"
        ), {"title": title})).first()
        if row is None:
            continue
        company_id, user_id = row
        if await db.get(CapabilityPassport, company_id) is None:
            db.add(CapabilityPassport(company_id=company_id, details={
                "business_kind": "stock_supplier", "product_types": "Товары для снабжения бизнеса",
                "delivery": "Самовывоз; стоимость перевозчика согласовывается отдельно",
                "limitations": "Точные характеристики и доступность указаны в карточке товара",
            }, technologies=[], materials=[], equipment=[], certifications=[], size_ranges={},
                delivery_regions=["Россия"], completed_order_types=[], min_order_units=1))
        # Eighteen distinct positions plus three comparable SKUs from another company.
        items = ASSORTMENT if seller_index == 0 else [ASSORTMENT[i] for i in (3, 9, 16)]
        for key, family, category, subcategory, name, attributes, price, moq, stock, lead in items:
            product_id = uuid.uuid5(NAMESPACE, f"{company_id}:{key}")
            if await db.get(Product, product_id) is not None:
                continue
            # No fabricated verification: regulated products stay in seller drafts
            # until their own documents have been checked through the normal workflow.
            report = evaluate_admission(category=category, subcategory=subcategory,
                                        characteristics=attributes, moq_units=moq, documents=[])
            product = Product(id=product_id, company_id=company_id, created_by_user_id=user_id,
                name=name, category=category, subcategory=subcategory, characteristics=attributes,
                price_rub=float(Decimal(str(price)) * (Decimal("1.04") if seller_index else Decimal(1))),
                price_tiers=[], moq_units=moq, lead_time_days=lead + seller_index,
                stock_units=stock // (seller_index + 1), stock_updated_at=datetime.now(timezone.utc),
                is_published=report.blocking_open == 0)
            db.add(product)
            await db.flush()
            if product.is_published:
                db.add(ProductPriceObservation(product_id=product.id, category=category,
                    unit_price_rub=product.price_rub, specification_hash=product_specification_hash(product)))
