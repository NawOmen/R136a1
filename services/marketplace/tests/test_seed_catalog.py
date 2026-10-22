"""Clean synthetic startup uses the same publication guards as the seller UI."""
import uuid
from decimal import Decimal

import pytest
from sqlalchemy import select, text

import seed
from app.assortment import ASSORTMENT
from app.models import Document, Product, ProductImage, ProductPriceObservation, ProductionProfile, TrustAuditEvent
from conftest import make_company, make_marketplace_admin, make_user, make_token
from seed_assortment import NAMESPACE, PRODUCT_PHOTO_KEYS, STOREFRONT_ADDITIONAL_KEYS, storefront_product_id


async def seller_fixture(db, monkeypatch, *, verified=True, admin=True):
    monkeypatch.setenv("ENABLE_DEMO_SEED", "true")
    monkeypatch.setattr(seed, "SELLER_USER_EMAIL", "seller@demo.ru")
    if admin:
        await make_marketplace_admin(db)
    user = await make_user(db, "seller@demo.ru")
    company = await make_company(db, user, can_buy=False, verified=verified)
    await db.execute(text("UPDATE auth.companies SET display_name=:name WHERE id=:id"),
                     {"name": seed.SELLER_COMPANY_NAME, "id": company})
    await db.commit()
    return company


async def test_clean_seed_publishes_admitted_cups_and_preserves_rerun(client, db_session, session_factory, monkeypatch):
    company = await seller_fixture(db_session, monkeypatch)
    monkeypatch.setattr(seed, "SessionLocal", session_factory)
    await seed.seed()
    response = await client.get("/api/v3/products")
    assert response.status_code == 200, response.text
    catalog = response.json()
    pictured = {row[4] for row in ASSORTMENT if row[0] in PRODUCT_PHOTO_KEYS}
    assert {item["name"] for item in catalog} == {"Стакан 400 мл PE", "Стакан 350 мл PE"} | pictured
    assert len(catalog) == 42
    assert len({item["category"] for item in catalog}) == 9
    assert all(item["category"] != "Продукты питания" for item in catalog)
    assert all(item["images"] and any(image["content_type"] == "image/webp" for image in item["images"]) for item in catalog)
    for key in STOREFRONT_ADDITIONAL_KEYS:
        item = next(item for item in catalog if item["id"] == str(storefront_product_id(company, key)))
        assert item["external_id"] == f"synthetic-storefront-v1:{key}"
        assert item["sources"] == [{"label": "Спецификация товара", "reference": f"synthetic_seed:storefront-v1:{key}"}]
    products = (await db_session.scalars(select(Product).where(Product.company_id == company))).all()
    assert len(products) == 2 + len(ASSORTMENT) + len(STOREFRONT_ADDITIONAL_KEYS)
    assert sum(product.is_published for product in products) == 42
    assert len((await db_session.scalars(select(ProductPriceObservation))).all()) == 42
    events = (await db_session.scalars(select(TrustAuditEvent).where(
        TrustAuditEvent.event_type == "product_published_with_admission"))).all()
    assert len(events) == 42

    # A seller's subsequent unpublication/stock/price edits survive repeat seed.
    cups = [product for product in products if product.is_published]
    for cup in cups:
        cup.is_published = False
        cup.price_rub = Decimal("12.34")
        cup.stock_units = 7
    await db_session.commit()
    await seed.seed()
    assert (await client.get("/api/v3/products")).json() == []
    await db_session.refresh(cups[0])
    assert cups[0].price_rub == Decimal("12.34") and cups[0].stock_units == 7
    assert len((await db_session.scalars(select(Product))).all()) == 2 + len(ASSORTMENT) + len(STOREFRONT_ADDITIONAL_KEYS)
    assert len((await db_session.scalars(select(ProductPriceObservation))).all()) == 42


@pytest.mark.parametrize("comparison_verified", [True, False])
async def test_seed_publishes_independent_company_offers_and_preserves_edits(client, db_session, session_factory, monkeypatch, comparison_verified):
    from seed_assortment import COMPARISON_STOREFRONT_KEYS, COMPARISON_UNAVAILABLE_KEYS

    first_company = await seller_fixture(db_session, monkeypatch)
    comparison_user = await make_user(db_session, "comparison@demo.ru")
    comparison_company = await make_company(db_session, comparison_user, can_buy=False, verified=comparison_verified)
    await db_session.execute(text("UPDATE auth.companies SET display_name=:name WHERE id=:id"),
                             {"name": "ООО «Регион Поставка»", "id": comparison_company})
    await db_session.commit()
    monkeypatch.setattr(seed, "SessionLocal", session_factory)
    await seed.seed()
    catalog = (await client.get("/api/v3/products")).json()
    assert len(catalog) == (50 if comparison_verified else 42)
    assert all(item["category"] != "Продукты питания" and item["images"] for item in catalog)
    offers = []
    for key in COMPARISON_STOREFRONT_KEYS:
        original = await db_session.get(Product, storefront_product_id(first_company, key))
        offer = await db_session.get(Product, storefront_product_id(comparison_company, key))
        old_draft = await db_session.get(Product, uuid.uuid5(NAMESPACE, f"{comparison_company}:{key}"))
        assert offer.id != old_draft.id and offer.created_by_user_id == comparison_user
        assert (offer.name, offer.category, offer.subcategory, offer.characteristics) == (original.name, original.category, original.subcategory, original.characteristics)
        assert offer.price_rub == original.price_rub * Decimal("1.04")
        assert offer.is_published is comparison_verified
        assert offer.stock_units == (0 if key in COMPARISON_UNAVAILABLE_KEYS else original.stock_units)
        assert offer.stock_updated_at is not None
        offers.append(offer)
    for offer in offers:
        offer.price_rub, offer.stock_units = Decimal("321.45"), 19
    offers[0].is_published = False
    await db_session.commit()
    for _ in range(2):
        await seed.seed()
        for offer in offers:
            await db_session.refresh(offer)
            assert (offer.price_rub, offer.stock_units) == (Decimal("321.45"), 19)
        assert offers[0].is_published is False
        assert len((await client.get("/api/v3/products")).json()) == (49 if comparison_verified else 42)


async def test_seed_production_image_is_readable_repairable_and_never_replaces_supplier_upload(client, db_session, session_factory, monkeypatch, stub_object_storage):
    company = await seller_fixture(db_session, monkeypatch)
    monkeypatch.setattr(seed, "SessionLocal", session_factory)
    await seed.seed()
    profile = await db_session.get(ProductionProfile, company)
    assert profile.photo_file_key == f"production/{company}/synthetic-workshop-v1.webp"
    public = await client.get(f"/api/v3/producers/{company}")
    assert public.status_code == 200 and public.json()["has_photo"] is True
    photo = await client.get(f"/api/v3/producers/{company}/photo")
    assert photo.status_code == 200 and photo.headers["content-type"] == "image/webp"
    assert photo.content[:4] == b"RIFF" and photo.content[8:12] == b"WEBP"
    original_key = profile.photo_file_key
    stub_object_storage.pop(original_key)
    await seed.seed()
    assert stub_object_storage[original_key] == photo.content
    profile.photo_file_key, profile.photo_file_name, profile.photo_content_type = "supplier/factory.png", "Цех поставщика.png", "image/png"
    stub_object_storage[profile.photo_file_key] = b"supplier-factory"
    await db_session.commit()
    await seed.seed()
    await db_session.refresh(profile)
    assert (profile.photo_file_key, profile.photo_file_name, profile.photo_content_type) == ("supplier/factory.png", "Цех поставщика.png", "image/png")
    assert stub_object_storage[profile.photo_file_key] == b"supplier-factory"


async def test_production_image_does_not_fill_an_edited_company_profile(db_session, monkeypatch):
    company = await seller_fixture(db_session, monkeypatch)
    profile = ProductionProfile(company_id=company, about="Профиль производства изменён поставщиком",
                                production_site_address="Другой адрес", region="Другой регион")
    db_session.add(profile)
    await db_session.commit()
    await seed._seed_production_photo(db_session, company)
    assert profile.photo_file_key is None


@pytest.mark.parametrize("verified,admin", [(False, True), (True, False)])
async def test_seed_does_not_bypass_company_or_document_guard(client, db_session, session_factory, monkeypatch, verified, admin):
    await seller_fixture(db_session, monkeypatch, verified=verified, admin=admin)
    monkeypatch.setattr(seed, "SessionLocal", session_factory)
    await seed.seed()
    assert (await client.get("/api/v3/products")).json() == []
    assert len((await db_session.scalars(select(ProductPriceObservation))).all()) == 0
    if not admin:
        documents = (await db_session.scalars(select(Document))).all()
        assert documents and all(doc.verification_status == "unverified" for doc in documents)


async def test_seed_requires_explicit_synthetic_flag(monkeypatch):
    monkeypatch.delenv("ENABLE_DEMO_SEED", raising=False)
    with pytest.raises(RuntimeError, match="ENABLE_DEMO_SEED=true"):
        await seed.seed()


async def test_storefront_upgrade_preserves_old_drafts_custom_photos_and_documents(client, db_session, session_factory, monkeypatch):
    import seed_assortment

    company = await seller_fixture(db_session, monkeypatch)
    monkeypatch.setattr(seed, "SessionLocal", session_factory)
    # Reproduce an installation before storefront-v1 without publishing its old
    # assortment drafts. The upgrade must add distinct products, not promote them.
    with monkeypatch.context() as legacy:
        legacy.setattr(seed_assortment, "STOREFRONT_ADDITIONAL_KEYS", ())
        await seed.seed()
    assert len((await client.get("/api/v3/products")).json()) == 5
    old_bag_id = uuid.uuid5(NAMESPACE, f"{company}:bag")
    old_bag = await db_session.get(Product, old_bag_id)
    old_bag.name = "Пакет по условиям поставщика"
    old_bag.price_rub = Decimal("37.25")
    old_bag.stock_units = 17
    old_image = ProductImage(product_id=old_bag.id, file_name="Фото поставщика.webp",
                             file_key="supplier/bag.webp", content_type="image/webp", position=0)
    db_session.add(old_image)
    # Even a colliding fixture name must not replace a supplier's document or
    # treat its upload as a verification. Use the only canister document so no
    # separately verified size variant can legitimately cover the same scope.
    canister_document = next(item for item in seed.storefront_documents() if item["synthetic_seed"] == "storefront-v1:canister_5")
    own_document = Document(company_id=company, name=canister_document["name"], document_type=canister_document["document_type"],
                            file_key="supplier/canister-document.pdf", content_type="application/pdf", verification_status="unverified",
                            scope_category="Упаковка и тара", scope_subcategory="Бутылки и канистры", confirms={"material": ["материал поставщика"]})
    db_session.add(own_document)
    await db_session.commit()
    image_id, document_id = old_image.id, own_document.id

    await seed.seed()
    await db_session.refresh(old_bag)
    await db_session.refresh(old_image)
    await db_session.refresh(own_document)
    assert (old_bag.name, old_bag.price_rub, old_bag.stock_units, old_bag.is_published) == ("Пакет по условиям поставщика", Decimal("37.25"), 17, False)
    assert (old_image.id, old_image.file_key, old_image.file_name) == (image_id, "supplier/bag.webp", "Фото поставщика.webp")
    assert (own_document.id, own_document.file_key, own_document.verification_status, own_document.confirms) == (document_id, "supplier/canister-document.pdf", "unverified", {"material": ["материал поставщика"]})
    new_bag = await db_session.get(Product, storefront_product_id(company, "bag"))
    assert new_bag.id != old_bag.id and new_bag.is_published is True
    assert new_bag.price_rub == Decimal("24") and new_bag.stock_units == 8000
    new_canister = await db_session.get(Product, storefront_product_id(company, "canister_5"))
    assert new_canister.is_published is False
    assert len((await client.get("/api/v3/products")).json()) == 41
    products_before = set((await db_session.scalars(select(Product.id))).all())
    images_before = {(image.id, image.file_key) for image in (await db_session.scalars(select(ProductImage))).all()}
    await seed.seed()
    assert set((await db_session.scalars(select(Product.id))).all()) == products_before
    assert {(image.id, image.file_key) for image in (await db_session.scalars(select(ProductImage))).all()} == images_before
    assert len((await client.get("/api/v3/products")).json()) == 41


async def test_storefront_upgrade_withdraws_old_foods_without_deleting_history(client, db_session, session_factory, monkeypatch):
    import seed_assortment

    company = await seller_fixture(db_session, monkeypatch)
    monkeypatch.setattr(seed, "SessionLocal", session_factory)
    previous_keys = (
        "box", "bag", "film", "cardboard_sheet", "steel_plate_2", "fabric",
        "retail_display", "warehouse_trolley", "tile", "bolt", "drinking_water",
        "rice_pack", "jacket", "office_paper_a4", "cleaning_bucket_10", "cable",
        "office_keyboard", "shipping_cage", "label_50", "laser_part_2",
    )

    async def keep_previous_foods(*_args):
        pass

    with monkeypatch.context() as previous:
        previous.setattr(seed_assortment, "PRODUCT_PHOTO_KEYS", previous_keys)
        previous.setattr(seed_assortment, "STOREFRONT_ADDITIONAL_KEYS", tuple(
            key for key in previous_keys if key not in seed_assortment.LEGACY_PRODUCT_PHOTO_KEYS))
        previous.setattr(seed, "_retire_storefront_food_products", keep_previous_foods)
        await seed.seed()
    old_catalog = (await client.get("/api/v3/products")).json()
    assert len(old_catalog) == 22
    assert sum(item["category"] == "Продукты питания" for item in old_catalog) == 2
    foods = [await db_session.get(Product, storefront_product_id(company, key))
             for key in seed_assortment.RETIRED_STOREFRONT_KEYS]
    for product in foods:
        product.price_rub = Decimal("91.23")
        product.stock_units = 7
    await db_session.commit()
    old_images = {(image.id, image.product_id, image.file_key)
                  for image in (await db_session.scalars(select(ProductImage))).all()}
    old_documents = set((await db_session.scalars(select(Document.id))).all())
    old_observations = set((await db_session.scalars(select(ProductPriceObservation.id))).all())

    for _ in range(2):
        await seed.seed()
        catalog = (await client.get("/api/v3/products")).json()
        assert len(catalog) == 42
        assert all(item["category"] != "Продукты питания" and item["images"] for item in catalog)
        for product in foods:
            await db_session.refresh(product)
            assert (product.is_published, product.price_rub, product.stock_units) == (False, Decimal("91.23"), 7)
        assert old_images <= {(image.id, image.product_id, image.file_key)
                              for image in (await db_session.scalars(select(ProductImage))).all()}
        assert old_documents <= set((await db_session.scalars(select(Document.id))).all())
        assert old_observations <= set((await db_session.scalars(select(ProductPriceObservation.id))).all())


@pytest.mark.parametrize("changed_field", ["name", "characteristics", "external_id", "sources"])
async def test_retirement_preserves_repurposed_food_fixture(db_session, monkeypatch, changed_field):
    company = await seller_fixture(db_session, monkeypatch)
    user = (await db_session.execute(text("SELECT id FROM auth.users WHERE email='seller@demo.ru'"))).scalar_one()
    key, _family, category, subcategory, name, attributes, price, moq, stock, lead = next(row for row in ASSORTMENT if row[0] == "rice_pack")
    product = Product(id=storefront_product_id(company, key), company_id=company, created_by_user_id=user,
                      external_id="synthetic-storefront-v1:rice_pack",
                      sources=[{"label": "Спецификация товара", "reference": "synthetic_seed:storefront-v1:rice_pack"}],
                      name=name, category=category, subcategory=subcategory, characteristics=dict(attributes),
                      price_rub=Decimal(str(price)), moq_units=moq, stock_units=stock,
                      lead_time_days=lead, is_published=True)
    replacement = {"name": "Товар продавца", "characteristics": {**attributes, "seller_note": "Условия поставщика"},
                   "external_id": "supplier-001", "sources": [{"label": "Источник поставщика", "reference": "supplier:001"}]}[changed_field]
    setattr(product, changed_field, replacement)
    db_session.add(product)
    await db_session.commit()
    await seed._retire_storefront_food_products(db_session, company, user)
    await db_session.refresh(product)
    assert product.is_published is True
    assert getattr(product, changed_field) == replacement


def test_storefront_documents_have_exact_scopes_and_characteristic_coverage():
    from datetime import date, timedelta
    from app.category_admission import evaluate_admission

    items = seed.storefront_documents()
    assert {item["synthetic_seed"].split(":", 1)[1] for item in items} == set(STOREFRONT_ADDITIONAL_KEYS)
    for key, _family, category, subcategory, _name, attributes, _price, moq, *_ in ASSORTMENT:
        if key not in STOREFRONT_ADDITIONAL_KEYS:
            continue
        documents = [Document(company_id=uuid.uuid4(), id=uuid.uuid4(), name=item["name"], document_type=item["document_type"],
                              file_key="demo/synthetic/specification", content_type="application/pdf", verification_status="verified",
                              scope_category=item["scope_category"], scope_subcategory=item["scope_subcategory"],
                              valid_until=date.today() + timedelta(days=1), confirms=item["confirms"])
                     for item in items if item["synthetic_seed"] == f"storefront-v1:{key}"]
        assert documents and all((document.scope_category, document.scope_subcategory) == (category, subcategory) for document in documents)
        report = evaluate_admission(category=category, subcategory=subcategory, characteristics=attributes, moq_units=moq, documents=documents)
        assert report.supported and report.blocking_open == 0, (key, report.blocking_message)
        if key == "steel_plate_2":
            changed = evaluate_admission(category=category, subcategory=subcategory, characteristics={**attributes, "material": "дерево"}, moq_units=moq, documents=documents)
            assert changed.blocking_open and any(requirement.state == "attribute_mismatch" for requirement in changed.requirements)


async def test_seeded_capability_scopes_are_readable_and_stable(client, db_session, session_factory, monkeypatch):
    company = await seller_fixture(db_session, monkeypatch)
    monkeypatch.setattr(seed, "SessionLocal", session_factory)
    await seed.seed()
    user = (await db_session.execute(text("SELECT id FROM auth.users WHERE email='seller@demo.ru'"))).scalar_one()
    headers = {"Authorization": f"Bearer {make_token(user)}"}
    for _ in range(2):
        private = await client.get(f"/api/v3/companies/{company}/capability-passport", headers=headers)
        public = await client.get(f"/api/v3/producers/{company}")
        assert private.status_code == 200, private.text
        assert public.status_code == 200, public.text
        scopes = private.json()["details"]["category_scopes"]
        assert len(scopes) == 1 + len(ASSORTMENT)
        assert public.json()["capability_details"]["category_scopes"] == scopes
        await seed.seed()


def test_capability_scopes_remain_bounded():
    from app.schemas import CapabilityDetails
    from pydantic import ValidationError
    scope = {"category_id": "construction.fasteners", "unit": "шт"}
    assert len(CapabilityDetails(category_scopes=[scope] * 128).category_scopes) == 128
    with pytest.raises(ValidationError):
        CapabilityDetails(category_scopes=[scope] * 129)


async def test_seeded_seller_feed_includes_moscow_but_not_outside_district(client, db_session, session_factory, monkeypatch):
    from datetime import date, timedelta
    from app.models import DeliveryAddress
    company = await seller_fixture(db_session, monkeypatch)
    monkeypatch.setattr(seed, "SessionLocal", session_factory)
    await seed.seed()
    seller = (await db_session.execute(text("SELECT id FROM auth.users WHERE email='seller@demo.ru'"))).scalar_one()
    buyer = await make_user(db_session)
    buyer_company = await make_company(db_session, buyer, can_buy=True, can_sell=False)
    buyer_headers = {"Authorization": f"Bearer {make_token(buyer)}"}
    ids = []
    for region in ("г. Москва", "Свердловская область"):
        address = DeliveryAddress(company_id=buyer_company, address="ул. Синтетическая, д. 1", city="Синтетический город", region=region)
        db_session.add(address)
        await db_session.commit()
        created = await client.post("/api/v3/needs", headers=buyer_headers, json={
            "company_id": str(buyer_company), "category": "Строительство", "subcategory": "Крепёж",
            "characteristics": {"unit": "шт", "thread": "М8"}, "volume_units": 200,
            "budget_rub": "5000", "deadline_date": str(date.today() + timedelta(days=30)),
            "delivery_address_id": str(address.id), "visibility": "open_anonymized",
        })
        assert created.status_code == 201, created.text
        need_id = created.json()["id"]
        published = await client.post(f"/api/v3/needs/{need_id}/publish", headers=buyer_headers)
        assert published.status_code == 200, published.text
        ids.append(need_id)
    feed = await client.get(f"/api/v3/needs?seller_company_id={company}", headers={"Authorization": f"Bearer {make_token(seller)}"})
    assert feed.status_code == 200, feed.text
    visible = {item["id"] for item in feed.json()}
    assert ids[0] in visible
    assert ids[1] not in visible
