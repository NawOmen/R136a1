"""Synthetic images may upgrade our pictograms, never a supplier's own data."""
import uuid
from decimal import Decimal

from sqlalchemy import select, text

from app.assortment import ASSORTMENT
from app.models import Product, ProductImage
from conftest import make_company, make_user
from seed_assortment import NAMESPACE, PRODUCT_PHOTO_KEYS, seed_product_photos


async def test_product_photos_upgrade_owned_pictogram_preserve_upload_and_edited_sku(db_session, stub_object_storage):
    user = await make_user(db_session)
    company = await make_company(db_session, user, can_buy=False, can_sell=True)
    await db_session.execute(text("UPDATE auth.companies SET display_name=:name WHERE id=:id"),
                             {"name": "ООО «Урал Комплект»", "id": company})
    products = {}
    for key, _family, category, subcategory, name, attributes, price, moq, stock, lead in ASSORTMENT:
        if key not in PRODUCT_PHOTO_KEYS:
            continue
        product = Product(id=uuid.uuid5(NAMESPACE, f"{company}:{key}"), company_id=company,
                          created_by_user_id=user, name=name, category=category, subcategory=subcategory,
                          characteristics=attributes, price_rub=Decimal(str(price)), moq_units=moq,
                          stock_units=stock, lead_time_days=lead, is_published=False)
        products[key] = product
        db_session.add(product)
    await db_session.flush()
    box = ProductImage(product_id=products["box"].id, file_name="Схематическая иллюстрация: Упаковка.png",
                       file_key=f"products/{products['box'].id}/seed-box.png", content_type="image/png", position=0)
    jacket = ProductImage(product_id=products["jacket"].id, file_name="Фото продавца.png",
                          file_key="supplier-upload.png", content_type="image/png", position=0)
    db_session.add_all([box, jacket])
    products["drinking_water"].name = "Товар изменён продавцом"
    await db_session.flush()
    box_image_id = box.id
    before = {key: (product.price_rub, product.stock_units, product.is_published) for key, product in products.items()}

    await seed_product_photos(db_session)
    await db_session.flush()
    images = list((await db_session.scalars(select(ProductImage))).all())
    assert len(images) == 3
    assert box.id == box_image_id and box.content_type == "image/webp"
    assert box.file_key.endswith("/seed-photo-box.webp")
    assert jacket.file_key == "supplier-upload.png" and jacket.content_type == "image/png"
    assert not any(image.product_id == products["drinking_water"].id for image in images)
    assert len(stub_object_storage) == 2
    assert all(data[:4] == b"RIFF" and data[8:12] == b"WEBP" for data in stub_object_storage.values())
    assert before == {key: (product.price_rub, product.stock_units, product.is_published) for key, product in products.items()}

    snapshot = {(image.id, image.file_key) for image in images}
    await seed_product_photos(db_session)
    assert snapshot == {(image.id, image.file_key) for image in (await db_session.scalars(select(ProductImage))).all()}
    assert len(stub_object_storage) == 2
