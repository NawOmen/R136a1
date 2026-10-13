"""Этап S05: поставщик — редактор, КП, лента, импорт, наполнение.

Проверяем приёмку S05.01–S05.05: ступени и версии карточек, идемпотентность КП,
фильтры и отклонения ленты, diff/откат импорта, идемпотентность сида.
"""
from synthetic_files import PNG, PDF

import uuid
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import func, select, text

from app.matching import offer_unit_price
from app.models import Deal, Need, Offer, Product
from conftest import confirmed_quote_terms, make_company, make_token, make_user

from test_category_admission import _auth
from test_offer_draft_and_scorecard import _buyer_with_published_need, _seller_company


async def _product(client, token, company, **override):
    payload = {
        "name": "Болт М8×40",
        "category": "Строительство",
        "subcategory": "Крепёж",
        "characteristics": {"material": "сталь", "unit": "шт"},
        "price_rub": 12,
        "price_tiers": [{"min_units": 100, "unit_price_rub": 10}, {"min_units": 200, "unit_price_rub": 8.75}],
        "moq_units": 100,
        "lead_time_days": 2,
        "stock_units": 5000,
    }
    payload.update(override)
    response = await client.post(f"/api/v1/companies/{company}/products", json=payload, headers=_auth(token))
    assert response.status_code == 201, response.text
    return response.json()


def test_tier_volumes_price_exact_line_totals():
    offer = Offer(price_rub=Decimal(10), price_tiers=[
        {"min_units": 100, "unit_price_rub": "10"},
        {"min_units": 200, "unit_price_rub": "8.75"},
    ])
    assert offer_unit_price(offer, 100) * 100 == Decimal(1000)
    assert offer_unit_price(offer, 200) * 200 == Decimal(1750)


async def test_product_revision_conflict_and_external_id_stability(client, db_session):
    user, company, token = await _seller_company(db_session)
    created = await _product(client, token, company, **{"external_id": "bolt-m8"})
    assert created["revision"] == 1
    stale = await client.patch(f"/api/v1/products/{created['id']}",
                               json={"price_rub": 13, "expected_revision": 2}, headers=_auth(token))
    assert stale.status_code == 409
    changed_id = await client.patch(f"/api/v1/products/{created['id']}",
                                    json={"external_id": "other"}, headers=_auth(token))
    assert changed_id.status_code == 409
    dup = await client.post(f"/api/v1/companies/{company}/products",
                            json={"name": "Гайка", "category": "Строительство", "subcategory": "Крепёж",
                                  "characteristics": {"unit": "шт"}, "price_rub": 5,
                                  "moq_units": 10, "lead_time_days": 1, "external_id": "bolt-m8"},
                            headers=_auth(token))
    assert dup.status_code == 409
    updated = await client.patch(f"/api/v1/products/{created['id']}",
                                 json={"price_rub": 13, "expected_revision": 1,
                                       "sources": [{"label": "Прайс", "reference": "прайс-2026-10"}]},
                                 headers=_auth(token))
    assert updated.status_code == 200, updated.text
    assert updated.json()["revision"] == 2
    assert updated.json()["sources"] == [{"label": "Прайс", "reference": "прайс-2026-10"}]


async def test_product_characteristics_limit_and_photo_bounds(client, db_session):
    user, company, token = await _seller_company(db_session)
    too_many = await client.post(f"/api/v1/companies/{company}/products",
                                 json={"name": "X", "category": "Строительство", "subcategory": "Крепёж",
                                       "characteristics": {f"p{i}": "v" for i in range(26)} | {"unit": "шт"},
                                       "price_rub": 5, "moq_units": 10, "lead_time_days": 1},
                                 headers=_auth(token))
    assert too_many.status_code == 422
    created = await _product(client, token, company)
    bad_type = await client.post(f"/api/v1/products/{created['id']}/images",
                                 files={"file": ("doc.txt", b"nope", "text/plain")}, headers=_auth(token))
    assert bad_type.status_code == 415
    for position in range(5):
        uploaded = await client.post(f"/api/v1/products/{created['id']}/images",
                                     files={"file": (f"p{position}.png", PNG, "image/png")},
                                     headers=_auth(token))
        assert uploaded.status_code == 201, uploaded.text
    sixth = await client.post(f"/api/v1/products/{created['id']}/images",
                              files={"file": ("p5.png", PNG, "image/png")},
                              headers=_auth(token))
    assert sixth.status_code == 409


async def test_offer_request_key_retry_returns_same_or_conflict(client, db_session):
    user, company, token = await _seller_company(db_session)
    _, _, _, need_id = await _buyer_with_published_need(client, db_session, volume=5_000)
    key = str(uuid.uuid4())
    payload = {"commercial_terms": confirmed_quote_terms(), "company_id": str(company),
               "price_rub": 11.5, "available_units": 5_000, "moq_units": 1_000,
               "delivery_cost_rub": 3_000, "lead_time_days": 9, "request_key": key}
    first = await client.post(f"/api/v1/needs/{need_id}/offers", json=payload, headers=_auth(token))
    assert first.status_code == 201, first.text
    retry = await client.post(f"/api/v1/needs/{need_id}/offers", json=payload, headers=_auth(token))
    assert retry.status_code == 200
    assert retry.json()["id"] == first.json()["id"]
    changed = await client.post(f"/api/v1/needs/{need_id}/offers",
                                json={**payload, "price_rub": 12.5}, headers=_auth(token))
    assert changed.status_code == 409
    nokey = await client.post(f"/api/v1/needs/{need_id}/offers",
                              json={k: v for k, v in payload.items() if k != "request_key"},
                              headers=_auth(token))
    assert nokey.status_code == 409


async def test_unknown_delivery_is_not_zero_and_blocks_select(client, db_session):
    user, company, token = await _seller_company(db_session)
    _, _, _, need_id = await _buyer_with_published_need(client, db_session, volume=5_000)
    offer = await client.post(f"/api/v1/needs/{need_id}/offers",
                              json={"commercial_terms": confirmed_quote_terms(), "company_id": str(company),
                                    "price_rub": 11.5, "available_units": 5_000, "moq_units": 1_000,
                                    "delivery_cost_rub": None, "lead_time_days": 9},
                              headers=_auth(token))
    assert offer.status_code == 201, offer.text
    assert offer.json()["commercial_quote"]["estimate"]["total_rub"] is None
    buyer = await make_user(db_session)
    buyer_company = await make_company(db_session, buyer, can_buy=True, can_sell=False)
    need_row = await db_session.get(Need, uuid.UUID(need_id))
    need_row.company_id = buyer_company
    await db_session.commit()
    selected = await client.post(f"/api/v1/offers/{offer.json()['id']}/select",
                                 json={"human_approved": True, "expected_revision": 1},
                                 headers=_auth(make_token(buyer)))
    assert selected.status_code == 409


async def test_needs_feed_filters_and_dismissal(client, db_session):
    from test_offer_draft_and_scorecard import _passport

    user, company, token = await _seller_company(db_session)
    await _passport(client, token, company)
    await _buyer_with_published_need(client, db_session, volume=5_000)
    feed = await client.get(f"/api/v1/needs?seller_company_id={company}", headers=_auth(token))
    assert feed.status_code == 200 and feed.json()
    filtered = await client.get(f"/api/v1/needs?seller_company_id={company}&subcategory=Несуществующая",
                                headers=_auth(token))
    assert filtered.json() == []
    unit_filtered = await client.get(f"/api/v1/needs?seller_company_id={company}&unit=рулон", headers=_auth(token))
    assert unit_filtered.json() == []
    opportunities = await client.get(f"/api/v1/companies/{company}/market-opportunities", headers=_auth(token))
    assert opportunities.status_code == 200 and opportunities.json()
    target = opportunities.json()[0]
    short = await client.post(f"/api/v1/opportunities/{target['id']}/dismiss", json={"reason": "ab"},
                              headers=_auth(token))
    assert short.status_code == 422
    dismissed = await client.post(f"/api/v1/opportunities/{target['id']}/dismiss",
                                  json={"reason": "Нерелевантно: нет такой оснастки"}, headers=_auth(token))
    assert dismissed.status_code == 200
    assert dismissed.json()["status"] == "dismissed"
    assert dismissed.json()["dismissal_reason"] == "Нерелевантно: нет такой оснастки"
    remaining = await client.get(f"/api/v1/companies/{company}/market-opportunities", headers=_auth(token))
    assert all(item["id"] != target["id"] for item in remaining.json())
    await client.post("/api/v1/market/rematch", headers=_auth(token))
    again = await client.get(f"/api/v1/companies/{company}/market-opportunities", headers=_auth(token))
    assert all(item["id"] != target["id"] for item in again.json())
    revived = await client.get(f"/api/v1/companies/{company}/market-opportunities", headers=_auth(token))
    assert all(item["status"] == "active" for item in revived.json())


async def test_catalog_import_tiers_external_id_diff_and_rollback(client, db_session):
    user, company, token = await _seller_company(db_session)
    headers = _auth(token)
    path = f"/api/v1/companies/{company}/catalog-import"
    csv_text = ("Название;Категория;Подкатегория;Цена;Минимум;Срок;Остаток;Внешний ID;Ступени\n"
                "Болт М8;Строительство;Крепёж;12;100;2;5000;bolt-m8;\"100:10;200:8,75\"\n").encode()
    preview = await client.post(path, files={"file": ("c.csv", csv_text, "text/csv")}, headers=headers)
    assert preview.status_code == 200, preview.text
    assert preview.json()["rows"][0]["import_status"] == "new"
    consent = {"commit": "true", "human_approved": "true", "request_key": str(uuid.uuid4()),
               "expected_hash": preview.json()["content_hash"]}
    created = await client.post(path, files={"file": ("c.csv", csv_text, "text/csv")}, data=consent, headers=headers)
    assert created.status_code == 200, created.text
    assert len(created.json()["created_ids"]) == 1
    import_id = created.json()["import_id"]
    product = await db_session.scalar(select(Product).where(Product.company_id == company))
    assert product.external_id == "bolt-m8"
    assert [(tier["min_units"], Decimal(str(tier["unit_price_rub"]))) for tier in product.price_tiers] == [
        (100, Decimal("10")), (200, Decimal("8.75"))]
    republish = await client.post(f"/api/v1/products/{product.id}/publish", json={"published": True}, headers=headers)
    assert republish.status_code in (200, 409, 422)

    changed_csv = ("Название;Категория;Подкатегория;Цена;Минимум;Срок;Остаток;Внешний ID;Ступени\n"
                   "Болт М8;Строительство;Крепёж;13;100;2;5000;bolt-m8;\"100:10;200:8,75\"\n").encode()
    second = await client.post(path, files={"file": ("c2.csv", changed_csv, "text/csv")}, headers=headers)
    assert second.status_code == 200, second.text
    row = second.json()["rows"][0]
    published_now = (await db_session.get(Product, product.id)).is_published
    assert row["import_status"] == ("published_skipped" if published_now else "changed"), row
    if not published_now:
        assert any(item["field"] == "Цена" for item in row["diff"])

    dup_csv = ("Название;Категория;Цена;Минимум;Срок;Внешний ID\n"
               "A;Строительство;10;5;2;x1\nB;Строительство;11;5;2;x1\n").encode()
    dup = await client.post(path, files={"file": ("d.csv", dup_csv, "text/csv")}, headers=headers)
    assert dup.status_code == 200
    assert any("повторяется" in item["message"] for item in dup.json()["errors"])

    bad_tiers = ("Название;Категория;Цена;Минимум;Срок;Ступени\n"
                 "A;Строительство;10;5;2;100:12\n").encode()
    bad = await client.post(path, files={"file": ("t.csv", bad_tiers, "text/csv")}, headers=headers)
    assert bad.status_code == 200
    assert bad.json()["errors"], "ступень выше базовой цены обязана отклоняться"

    repeat = await client.post(path, files={"file": ("c.csv", csv_text, "text/csv")}, headers=headers)
    repeat_consent = {"commit": "true", "human_approved": "true", "request_key": str(uuid.uuid4()),
                      "expected_hash": repeat.json()["content_hash"]}
    recommitted = await client.post(path, files={"file": ("c.csv", csv_text, "text/csv")},
                                    data=repeat_consent, headers=headers)
    assert recommitted.status_code == 200, recommitted.text
    assert recommitted.json()["created_ids"] == []
    assert recommitted.json()["updated_ids"] == []

    rolled = await client.post(f"/api/v1/companies/{company}/catalog-imports/{import_id}/rollback", headers=headers)
    assert rolled.status_code == 200, rolled.text
    if published_now:
        assert rolled.json()["skipped_published_ids"] == created.json()["created_ids"]
        assert rolled.json()["deleted_ids"] == []
    else:
        assert rolled.json()["deleted_ids"] == created.json()["created_ids"]


async def test_assortment_scope_and_seed_stories(client, db_session):
    from app.assortment import ASSORTMENT
    from app.models import CapabilityPassport
    from app.category_registry import resolve_category
    from seed_assortment import comparison_assortment
    from seed_assortment import group_pictogram, seed_assortment

    assert len(ASSORTMENT) == 101
    keys = [item[0] for item in ASSORTMENT]
    assert len(set(keys)) == len(keys)
    families = {item[1] for item in ASSORTMENT}
    assert len(families) == 12
    for family in families:
        assert sum(1 for item in ASSORTMENT if item[1] == family) >= 2
    assert group_pictogram("Крепёж")[:8] == PNG[:8]

    seller_tokens = {}
    for index, (title, can_sell) in enumerate((("ООО «Урал Комплект»", True), ("ООО «Регион Поставка»", True))):
        user = await make_user(db_session, email=f"seed-seller-{index}@demo.ru")
        company = await make_company(db_session, user, can_buy=False, can_sell=can_sell)
        await db_session.execute(
            text("UPDATE auth.companies SET display_name = :title WHERE id = :id"),
            {"title": title, "id": company},
        )
        await db_session.commit()
        seller_tokens[title] = (company, make_token(user))
    buyer_user = await make_user(db_session, email="seed-buyer@demo.ru")
    buyer_company = await make_company(db_session, buyer_user, can_buy=True, can_sell=False)
    await db_session.execute(
        text("UPDATE auth.companies SET display_name = 'ООО «Вектор Снабжения»' WHERE id = :id"),
        {"id": buyer_company},
    )
    await db_session.commit()
    before_products = await db_session.scalar(select(func.count()).select_from(Product))
    await seed_assortment(db_session)
    await db_session.commit()
    first_products = await db_session.scalar(select(func.count()).select_from(Product))
    assert first_products - before_products == len(ASSORTMENT) + len(comparison_assortment())
    expected_leaves = {resolve_category(row[2], row[3])["id"] for row in ASSORTMENT}
    for title, (company, _) in seller_tokens.items():
        products = (await db_session.scalars(select(Product).where(Product.company_id == company))).all()
        assert {resolve_category(product.category, product.subcategory)["id"] for product in products} == expected_leaves
        assert all(not product.is_published for product in products)
        passport = await db_session.get(CapabilityPassport, company)
        assert {scope["category_id"] for scope in passport.details["category_scopes"]} == expected_leaves
    await seed_assortment(db_session)
    await db_session.commit()
    after_products = await db_session.scalar(select(func.count()).select_from(Product))
    assert after_products == first_products
    deals = (await db_session.execute(select(Deal))).scalars().all()
    assert {deal.status for deal in deals} >= {"fulfilled", "cancelled"}
    for deal in deals:
        assert deal.total_price_rub == deal.unit_price_rub * deal.units + deal.delivery_price_rub
    open_need = await db_session.scalar(
        select(Need).where(Need.status == "waiting_for_match", Need.no_match_reason.is_not(None)))
    assert open_need is not None
    from app.models import DealExecutionEvent, ProductImage
    events = (await db_session.execute(select(DealExecutionEvent))).scalars().all()
    assert {(event.kind, event.status) for event in events} >= {("acceptance", "confirmed"),
                                                                ("cancellation", "confirmed")}
    assert sum(event.units for event in events if event.kind == "acceptance") == 1000
    images = (await db_session.execute(select(ProductImage))).scalars().all()
    assert len(images) == 12
    assert all(image.content_type == "image/png" for image in images)
    assert len({image.product_id for image in images}) == 12
    ural_id, ural_token = seller_tokens["ООО «Урал Комплект»"]
    analytics = await client.get(f"/api/v1/companies/{ural_id}/seller-analytics",
                                 headers=_auth(ural_token))
    assert analytics.status_code == 200, analytics.text
    assert analytics.json()["sold_units"] == 1000
    assert Decimal(str(analytics.json()["revenue_rub"])) == Decimal("12000")
    assert analytics.json()["deals_total"] == 2


async def test_assortment_upgrade_preserves_old_ids_prices_and_passport_edits(db_session, monkeypatch):
    import seed_assortment as loader
    from app.assortment import ASSORTMENT
    from app.models import CapabilityPassport
    from app.category_registry import resolve_category
    from copy import deepcopy
    import uuid

    companies = []
    for index, title in enumerate(("ООО «Урал Комплект»", "ООО «Регион Поставка»")):
        user = await make_user(db_session, email=f"upgrade-{index}@demo.ru")
        company = await make_company(db_session, user, can_buy=False)
        await db_session.execute(text("UPDATE auth.companies SET display_name=:title WHERE id=:id"),
                                 {"title": title, "id": company})
        companies.append(company)
    await db_session.commit()
    # Reproduce the preceding catalogue: 24 first-seller and 7 second-seller SKUs.
    legacy = ASSORTMENT[:24]
    legacy_second = [row for row in legacy if row[0] in loader.LEGACY_COMPARISON_KEYS]
    with monkeypatch.context() as old:
        old.setattr(loader, "ASSORTMENT", legacy)
        old.setattr(loader, "comparison_assortment", lambda: legacy_second)
        await loader.seed_assortment(db_session)
    await db_session.commit()
    old_ids = set((await db_session.scalars(select(Product.id))).all())
    assert len(old_ids) == 31
    box_id = uuid.uuid5(loader.NAMESPACE, f"{companies[0]}:box")
    box = await db_session.get(Product, box_id)
    box.price_rub = Decimal("123.45")
    box.stock_units = 777
    passport = await db_session.get(CapabilityPassport, companies[0])
    details = deepcopy(passport.details)
    details["delivery"] = "Условия доставки изменены продавцом"
    details["category_scopes"][0]["max_units"] = 700
    retained_scope = deepcopy(details["category_scopes"][0])
    passport.details = details
    await db_session.commit()

    await loader.seed_assortment(db_session)
    await db_session.commit()
    all_ids = set((await db_session.scalars(select(Product.id))).all())
    assert old_ids <= all_ids
    assert len(all_ids) == len(ASSORTMENT) + len(loader.comparison_assortment())
    await db_session.refresh(box)
    await db_session.refresh(passport)
    assert box.price_rub == Decimal("123.45") and box.stock_units == 777
    assert passport.details["delivery"] == details["delivery"]
    assert retained_scope in passport.details["category_scopes"]
    expected = {resolve_category(row[2], row[3])["id"] for row in ASSORTMENT}
    assert {scope["category_id"] for scope in passport.details["category_scopes"]} == expected
    # A deliberately removed scope for an existing SKU stays removed on replay.
    passport.details = {**passport.details, "category_scopes": [scope for scope in
                       passport.details["category_scopes"] if scope != retained_scope]}
    await db_session.commit()
    await loader.seed_assortment(db_session)
    await db_session.commit()
    await db_session.refresh(passport)
    assert retained_scope not in passport.details["category_scopes"]
    assert set((await db_session.scalars(select(Product.id))).all()) == all_ids


async def test_import_respects_held_stock_like_editor(client, db_session):
    from datetime import date as _date
    from datetime import timedelta as _td

    from app.resources import reserve

    user, company, token = await _seller_company(db_session)
    created = await _product(client, token, company, **{"external_id": "held-stock"})
    await reserve(db_session, company_id=company, anchor_type="test-hold", anchor_id=uuid.uuid4(),
                  units=4000, deadline=_date.today() + _td(days=30),
                  resource_kind="stock", product_id=uuid.UUID(created["id"]))
    await db_session.commit()
    editor = await client.patch(f"/api/v1/products/{created['id']}",
                                json={"stock_units": 1000, "expected_revision": 1}, headers=_auth(token))
    assert editor.status_code == 409
    csv_text = ("Название;Категория;Подкатегория;Цена;Минимум;Срок;Остаток;Внешний ID\n"
                "Болт М8;Строительство;Крепёж;12;100;2;1000;held-stock\n").encode()
    path = f"/api/v1/companies/{company}/catalog-import"
    preview = await client.post(path, files={"file": ("c.csv", csv_text, "text/csv")}, headers=_auth(token))
    assert preview.status_code == 200, preview.text
    row = preview.json()["rows"][0]
    assert row["import_status"] == "changed"
    revisions = {row["product_id"]: {"revision": 1, "status": row["import_status"]}}
    consent = {"commit": "true", "human_approved": "true", "request_key": str(uuid.uuid4()),
               "expected_hash": preview.json()["content_hash"],
               "expected_revisions": json_dumps(revisions)}
    rejected = await client.post(path, files={"file": ("c.csv", csv_text, "text/csv")},
                                 data=consent, headers=_auth(token))
    assert rejected.status_code == 409


async def test_import_preview_bound_to_revisions(client, db_session):
    user, company, token = await _seller_company(db_session)
    created = await _product(client, token, company, **{"external_id": "rev-bound"})
    path = f"/api/v1/companies/{company}/catalog-import"
    csv_text = ("Название;Категория;Подкатегория;Цена;Минимум;Срок;Остаток;Внешний ID\n"
                "Болт М8;Строительство;Крепёж;13;100;2;5000;rev-bound\n").encode()
    preview = await client.post(path, files={"file": ("c.csv", csv_text, "text/csv")}, headers=_auth(token))
    assert preview.json()["rows"][0]["import_status"] == "changed"
    moved = await client.patch(f"/api/v1/products/{created['id']}",
                               json={"price_rub": 20, "expected_revision": 1}, headers=_auth(token))
    assert moved.status_code == 200
    stale_consent = {"commit": "true", "human_approved": "true", "request_key": str(uuid.uuid4()),
                     "expected_hash": preview.json()["content_hash"],
                     "expected_revisions": json_dumps({created["id"]: {"revision": 1, "status": "changed"}})}
    stale = await client.post(path, files={"file": ("c.csv", csv_text, "text/csv")},
                              data=stale_consent, headers=_auth(token))
    assert stale.status_code == 409


async def test_external_id_cannot_be_cleared(client, db_session):
    user, company, token = await _seller_company(db_session)
    created = await _product(client, token, company, **{"external_id": "keep-me"})
    cleared = await client.patch(f"/api/v1/products/{created['id']}", json={"external_id": None},
                                 headers=_auth(token))
    assert cleared.status_code == 409


async def test_rollback_restores_updated_drafts_and_conflicts(client, db_session):
    user, company, token = await _seller_company(db_session)
    headers = _auth(token)
    path = f"/api/v1/companies/{company}/catalog-import"
    csv_text = ("Название;Категория;Цена;Минимум;Срок;Внешний ID\n"
                "Болт М8;Строительство;12;100;2;rb-1\n").encode()
    preview = await client.post(path, files={"file": ("c.csv", csv_text, "text/csv")}, headers=headers)
    consent = {"commit": "true", "human_approved": "true", "request_key": str(uuid.uuid4()),
               "expected_hash": preview.json()["content_hash"], "expected_revisions": "{}"}
    created = await client.post(path, files={"file": ("c.csv", csv_text, "text/csv")},
                                data=consent, headers=headers)
    product_id = created.json()["created_ids"][0]
    changed_csv = ("Название;Категория;Цена;Минимум;Срок;Внешний ID\n"
                   "Болт М8;Строительство;13;100;2;rb-1\n").encode()
    second_preview = await client.post(path, files={"file": ("c2.csv", changed_csv, "text/csv")}, headers=headers)
    row = second_preview.json()["rows"][0]
    assert row["import_status"] == "changed"
    second_consent = {"commit": "true", "human_approved": "true", "request_key": str(uuid.uuid4()),
                      "expected_hash": second_preview.json()["content_hash"],
                      "expected_revisions": json_dumps({product_id: {"revision": 1, "status": "changed"}})}
    second = await client.post(path, files={"file": ("c2.csv", changed_csv, "text/csv")},
                               data=second_consent, headers=headers)
    assert second.json()["updated_ids"] == [product_id]
    import_id = second.json()["import_id"]
    rolled = await client.post(f"/api/v1/companies/{company}/catalog-imports/{import_id}/rollback",
                               headers=headers)
    assert rolled.status_code == 200, rolled.text
    assert rolled.json()["restored_ids"] == [product_id]
    restored = await db_session.get(Product, uuid.UUID(product_id))
    assert restored.price_rub == Decimal("12")
    assert restored.revision == 3
    third_preview = await client.post(path, files={"file": ("c2.csv", changed_csv, "text/csv")}, headers=headers)
    third_consent = {"commit": "true", "human_approved": "true", "request_key": str(uuid.uuid4()),
                     "expected_hash": third_preview.json()["content_hash"],
                     "expected_revisions": json_dumps({product_id: {"revision": restored.revision, "status": "changed"}})}
    third = await client.post(path, files={"file": ("c2.csv", changed_csv, "text/csv")},
                              data=third_consent, headers=headers)
    assert third.json()["updated_ids"] == [product_id]
    await client.patch(f"/api/v1/products/{product_id}", json={"price_rub": 99}, headers=headers)
    conflicted = await client.post(f"/api/v1/companies/{company}/catalog-imports/{third.json()['import_id']}/rollback",
                                   headers=headers)
    assert conflicted.status_code == 409


async def test_repeat_import_returns_full_result(client, db_session):
    user, company, token = await _seller_company(db_session)
    headers = _auth(token)
    path = f"/api/v1/companies/{company}/catalog-import"
    csv_text = ("Название;Категория;Цена;Минимум;Срок;Внешний ID\n"
                "Болт М8;Строительство;12;100;2;repeat-1\n").encode()
    preview = await client.post(path, files={"file": ("c.csv", csv_text, "text/csv")}, headers=headers)
    key = str(uuid.uuid4())
    consent = {"commit": "true", "human_approved": "true", "request_key": key,
               "expected_hash": preview.json()["content_hash"], "expected_revisions": "{}"}
    first = await client.post(path, files={"file": ("c.csv", csv_text, "text/csv")},
                              data=consent, headers=headers)
    assert first.status_code == 200
    repeat = await client.post(path, files={"file": ("c.csv", csv_text, "text/csv")},
                               data=consent, headers=headers)
    assert repeat.status_code == 200
    assert repeat.json()["created_ids"] == first.json()["created_ids"]
    assert repeat.json()["import_id"] == first.json()["import_id"]
    assert repeat.json()["rows"][0]["import_status"] == "unchanged"


async def test_offer_retry_checks_terms_validity_and_included(client, db_session):
    user, company, token = await _seller_company(db_session)
    _, _, _, need_id = await _buyer_with_published_need(client, db_session, volume=5_000)
    key = str(uuid.uuid4())
    base = {"company_id": str(company), "price_rub": 11.5, "available_units": 5_000,
            "moq_units": 1_000, "lead_time_days": 9, "request_key": key,
            "commercial_terms": {"delivery_method": "included", "tax_basis": "no_vat",
                                 "delivery_conditions": "Самовывоз со склада"},
            "delivery_cost_rub": None}
    first = await client.post(f"/api/v1/needs/{need_id}/offers", json=base, headers=_auth(token))
    assert first.status_code == 201, first.text
    retry = await client.post(f"/api/v1/needs/{need_id}/offers", json=base, headers=_auth(token))
    assert retry.status_code == 200
    assert retry.json()["id"] == first.json()["id"]
    other_terms = {**base, "commercial_terms": {**base["commercial_terms"], "delivery_method": "separate"},
                   "delivery_cost_rub": 1000}
    conflicted = await client.post(f"/api/v1/needs/{need_id}/offers", json=other_terms, headers=_auth(token))
    assert conflicted.status_code == 409
    other_date = {**base, "valid_until": str(date.today() + timedelta(days=10))}
    dated = await client.post(f"/api/v1/needs/{need_id}/offers", json=other_date, headers=_auth(token))
    assert dated.status_code == 409


async def test_system_characteristics_outside_user_limit(client, db_session):
    user, company, token = await _seller_company(db_session)
    created = await _product(client, token, company,
                             **{"characteristics": {f"поле-{i}": i for i in range(25)} | {"unit": "шт"}})
    assert created["revision"] == 1


async def test_passport_only_feed_filters_compatibility(client, db_session):
    from test_offer_draft_and_scorecard import _passport

    user, company, token = await _seller_company(db_session)
    await _passport(client, token, company)
    await _buyer_with_published_need(client, db_session, volume=5_000)
    feed = await client.get(f"/api/v1/needs?seller_company_id={company}", headers=_auth(token))
    assert feed.status_code == 200
    assert len(feed.json()) == 1
    await _buyer_with_published_need(
        client, db_session, volume=5_000,
        characteristics={"volume_ml": 600, "coating": "PLA", "material": "крафт-картон"})
    feed_again = await client.get(f"/api/v1/needs?seller_company_id={company}", headers=_auth(token))
    assert len(feed_again.json()) == 1
    await _product(client, token, company, **{
        "name": "Стакан 400 мл", "category": "Упаковка и тара", "subcategory": "Бумажные стаканы",
        "characteristics": {"volume_ml": 400, "coating": "PE", "material": "крафт-картон", "unit": "шт"},
        "price_rub": 12, "moq_units": 1000,
        "price_tiers": [{"min_units": 1000, "unit_price_rub": 12}]})
    feed_with_card = await client.get(f"/api/v1/needs?seller_company_id={company}", headers=_auth(token))
    assert len(feed_with_card.json()) == 1


async def test_offer_send_rechecks_term_and_warns_admission(client, db_session):
    user, company, token = await _seller_company(db_session)
    _, _, _, need_id = await _buyer_with_published_need(client, db_session, volume=5_000)
    late = await client.post(f"/api/v1/needs/{need_id}/offers",
                             json={"commercial_terms": confirmed_quote_terms(), "company_id": str(company),
                                   "price_rub": 11.5, "available_units": 5_000, "moq_units": 1_000,
                                   "delivery_cost_rub": 3_000, "lead_time_days": 90},
                             headers=_auth(token))
    assert late.status_code == 409
    sent = await client.post(f"/api/v1/needs/{need_id}/offers",
                             json={"commercial_terms": confirmed_quote_terms(), "company_id": str(company),
                                   "price_rub": 11.5, "available_units": 5_000, "moq_units": 1_000,
                                   "delivery_cost_rub": 3_000, "lead_time_days": 9},
                             headers=_auth(token))
    assert sent.status_code == 201, sent.text
    assert sent.json()["sending_warnings"], "допуск без документов показывается до отправки"


def json_dumps(value) -> str:
    import json as _json
    return _json.dumps(value)


async def test_rollback_refuses_reserved_stock_restore(client, db_session):
    from app.resources import reserve
    from datetime import date as _date
    from datetime import timedelta as _td

    user, company, token = await _seller_company(db_session)
    headers = _auth(token)
    path = f"/api/v1/companies/{company}/catalog-import"
    csv_text = ("Название;Категория;Цена;Минимум;Срок;Остаток;Внешний ID\n"
                "Болт М8;Строительство;12;100;2;1000;rb-stock\n").encode()
    preview = await client.post(path, files={"file": ("c.csv", csv_text, "text/csv")}, headers=headers)
    consent = {"commit": "true", "human_approved": "true", "request_key": str(uuid.uuid4()),
               "expected_hash": preview.json()["content_hash"], "expected_revisions": "{}"}
    created = await client.post(path, files={"file": ("c.csv", csv_text, "text/csv")},
                                data=consent, headers=headers)
    product_id = created.json()["created_ids"][0]
    changed_csv = ("Название;Категория;Цена;Минимум;Срок;Остаток;Внешний ID\n"
                   "Болт М8;Строительство;12;100;2;5000;rb-stock\n").encode()
    second_preview = await client.post(path, files={"file": ("c2.csv", changed_csv, "text/csv")}, headers=headers)
    second_consent = {"commit": "true", "human_approved": "true", "request_key": str(uuid.uuid4()),
                      "expected_hash": second_preview.json()["content_hash"],
                      "expected_revisions": json_dumps({product_id: {"revision": 1, "status": "changed"}})}
    second = await client.post(path, files={"file": ("c2.csv", changed_csv, "text/csv")},
                               data=second_consent, headers=headers)
    assert second.json()["updated_ids"] == [product_id]
    await reserve(db_session, company_id=company, anchor_type="test-hold", anchor_id=uuid.uuid4(),
                  units=4000, deadline=_date.today() + _td(days=30),
                  resource_kind="stock", product_id=uuid.UUID(product_id))
    await db_session.commit()
    refused = await client.post(f"/api/v1/companies/{company}/catalog-imports/{second.json()['import_id']}/rollback",
                                headers=headers)
    assert refused.status_code == 409


async def test_commit_requires_shown_published_decision(client, db_session):
    user, company, token = await _seller_company(db_session)
    headers = _auth(token)
    created = await _product(client, token, company, **{"external_id": "pub-bind"})
    await db_session.execute(
        text("UPDATE marketplace.products SET is_published = true WHERE id = :id"),
        {"id": uuid.UUID(created["id"])},
    )
    await db_session.commit()
    path = f"/api/v1/companies/{company}/catalog-import"
    csv_text = ("Название;Категория;Цена;Минимум;Срок;Внешний ID\n"
                "Болт М8;Строительство;15;100;2;pub-bind\n").encode()
    preview = await client.post(path, files={"file": ("c.csv", csv_text, "text/csv")}, headers=headers)
    assert preview.json()["rows"][0]["import_status"] == "published_skipped", preview.text
    shown = {created["id"]: {"revision": 1, "status": "published_skipped"}}
    unpublished = await client.post(f"/api/v1/products/{created['id']}/publish", json={"published": False},
                                    headers=headers)
    assert unpublished.status_code == 200
    consent = {"commit": "true", "human_approved": "true", "request_key": str(uuid.uuid4()),
               "expected_hash": preview.json()["content_hash"],
               "expected_revisions": json_dumps(shown)}
    conflicted = await client.post(path, files={"file": ("c.csv", csv_text, "text/csv")},
                                   data=consent, headers=headers)
    assert conflicted.status_code == 409


async def test_import_category_change_refreshes_profile(client, db_session):
    user, company, token = await _seller_company(db_session)
    headers = _auth(token)
    created = await _product(client, token, company, **{"external_id": "cat-change"})
    old_profile = dict(created["category_profile"] or {})
    path = f"/api/v1/companies/{company}/catalog-import"
    csv_text = ("Название;Категория;Подкатегория;Цена;Минимум;Срок;Внешний ID;Характеристика: material\n"
                "Стол;Товары для бизнеса;Мебель;7900;5;10;cat-change;ЛДСП\n").encode()
    preview = await client.post(path, files={"file": ("c.csv", csv_text, "text/csv")}, headers=headers)
    assert preview.json()["rows"][0]["import_status"] == "changed", preview.text
    consent = {"commit": "true", "human_approved": "true", "request_key": str(uuid.uuid4()),
               "expected_hash": preview.json()["content_hash"],
               "expected_revisions": json_dumps({created["id"]: {"revision": 1, "status": "changed"}})}
    committed = await client.post(path, files={"file": ("c.csv", csv_text, "text/csv")},
                                  data=consent, headers=headers)
    assert committed.status_code == 200, committed.text
    product = await db_session.get(Product, uuid.UUID(created["id"]))
    assert product.category == "Товары для бизнеса"
    assert (product.category_profile or {}) != old_profile
    assert product.quantity_conversion is None


async def test_offer_resource_kind_capacity_and_freshness(client, db_session):
    from datetime import date as _date
    from datetime import timedelta as _td

    from conftest import grant_capacity

    user, company, token = await _seller_company(db_session)
    base = {"commercial_terms": confirmed_quote_terms(), "company_id": str(company),
            "price_rub": 11.5, "available_units": 6, "moq_units": 1,
            "delivery_cost_rub": 100, "lead_time_days": 9, "resource_kind": "capacity"}
    await grant_capacity(db_session, company, 10)
    _, _, _, need_fit = await _buyer_with_published_need(client, db_session, volume=5_000)
    fits_ten = await client.post(f"/api/v1/needs/{need_fit}/offers", json=base, headers=_auth(token))
    assert fits_ten.status_code == 201, fits_ten.text
    _, _, _, need_over = await _buyer_with_published_need(client, db_session, volume=5_000)
    over = await client.post(f"/api/v1/needs/{need_over}/offers",
                             json={**base, "available_units": 11}, headers=_auth(token))
    assert over.status_code == 409
    assert "мощность" in over.text
    await db_session.execute(text("DELETE FROM marketplace.capacity_entries"))
    await db_session.commit()
    from app.models import CapacityEntry
    from app.resource_scopes import prepare_conversions

    conversions = prepare_conversions([{"category_id": "packaging.paper-cups", "order_unit": "шт",
                                        "resource_units_per_order_unit": 2}], True)
    db_session.add(CapacityEntry(company_id=company, date=date.today(), unit="шт",
                                 category_conversions=conversions, available_units=10))
    await db_session.commit()
    _, _, _, need_coeff = await _buyer_with_published_need(client, db_session, volume=5_000)
    over_coeff = await client.post(f"/api/v1/needs/{need_coeff}/offers", json=base, headers=_auth(token))
    assert over_coeff.status_code == 409
    _, _, _, need_exact = await _buyer_with_published_need(client, db_session, volume=5_000)
    fits = await client.post(f"/api/v1/needs/{need_exact}/offers",
                             json={**base, "available_units": 5}, headers=_auth(token))
    assert fits.status_code == 201, fits.text


async def test_stale_stock_warns_but_does_not_block(client, db_session):
    from datetime import datetime as _datetime
    from datetime import timezone as _tz

    user, company, token = await _seller_company(db_session)
    _, _, _, need_id = await _buyer_with_published_need(client, db_session, volume=5_000)
    created = await _product(client, token, company, **{
        "name": "Стакан 400 мл", "category": "Упаковка и тара", "subcategory": "Бумажные стаканы",
        "characteristics": {"volume_ml": 400, "coating": "PE", "material": "крафт-картон", "unit": "шт"},
        "price_rub": 12, "moq_units": 100})
    await db_session.execute(
        text("UPDATE marketplace.products SET stock_updated_at = now() - interval '8 days' WHERE id = :id"),
        {"id": uuid.UUID(created["id"])},
    )
    await db_session.commit()
    sent = await client.post(f"/api/v1/needs/{need_id}/offers",
                             json={"commercial_terms": confirmed_quote_terms(), "company_id": str(company),
                                   "price_rub": 11.5, "available_units": 100, "moq_units": 100,
                                   "delivery_cost_rub": 100, "lead_time_days": 2,
                                   "resource_kind": "stock", "product_id": created["id"]},
                             headers=_auth(token))
    assert sent.status_code == 201, sent.text
    assert any("7 дней" in warning for warning in sent.json()["sending_warnings"])


async def test_required_subject_fields_outside_user_limit(client, db_session):
    user, company, token = await _seller_company(db_session)
    created = await _product(client, token, company, **{
        "category": "Строительство", "subcategory": "Крепёж",
        "characteristics": {f"поле-{i}": i for i in range(25)} | {
            "unit": "шт", "material": "сталь", "product_kind": "болт"}})
    assert created["revision"] == 1


async def test_preview_checks_access_staleness_and_repeat(client, db_session):
    user, company, token = await _seller_company(db_session)
    _, _, _, need_id = await _buyer_with_published_need(client, db_session, volume=5_000)
    base = {"company_id": str(company), "price_rub": 11.5, "available_units": 5_000,
            "moq_units": 1_000, "delivery_cost_rub": 100, "lead_time_days": 9,
            "commercial_terms": confirmed_quote_terms(), "resource_kind": "capacity",
            "request_key": str(uuid.uuid4())}
    preview = await client.post(f"/api/v1/needs/{need_id}/offers/preview", json=base, headers=_auth(token))
    assert preview.status_code == 200, preview.text
    assert preview.json()["can_send"] is True
    closed = await db_session.get(Need, uuid.UUID(need_id))
    closed.visibility = "closed"
    await db_session.commit()
    hidden = await client.post(f"/api/v1/needs/{need_id}/offers/preview", json=base, headers=_auth(token))
    assert hidden.status_code == 403
    closed.visibility = "open_anonymized"
    await db_session.commit()
    sent = await client.post(f"/api/v1/needs/{need_id}/offers", json=base, headers=_auth(token))
    assert sent.status_code == 201, sent.text
    repeat_preview = await client.post(f"/api/v1/needs/{need_id}/offers/preview", json=base,
                                       headers=_auth(token))
    assert repeat_preview.json()["can_send"] is True
    assert repeat_preview.json()["existing_offer_id"] == sent.json()["id"]


async def test_preview_rejects_stale_draft(client, db_session):
    from test_offer_draft_and_scorecard import _passport

    user, company, token = await _seller_company(db_session)
    await _passport(client, token, company)
    _, _, _, need_id = await _buyer_with_published_need(client, db_session, volume=5_000)
    draft = await client.post(f"/api/v1/needs/{need_id}/offer-draft", json={"company_id": str(company)},
                              headers=_auth(token))
    assert draft.status_code == 201, draft.text
    payload = draft.json()["payload"]
    stale = await client.post(
        f"/api/v1/needs/{need_id}/offers/preview",
        json={"company_id": str(company), "price_rub": 11.5, "available_units": 5_000,
              "moq_units": 1_000, "delivery_cost_rub": 100, "lead_time_days": 9,
              "resource_kind": "capacity", "draft_id": draft.json()["id"]},
        headers=_auth(token))
    assert stale.status_code == 200
    assert stale.json()["can_send"] is True
    product_id = payload.get("product_id")
    if product_id:
        await client.patch(f"/api/v1/products/{product_id}", json={"price_rub": 99}, headers=_auth(token))
        changed = await client.post(
            f"/api/v1/needs/{need_id}/offers/preview",
            json={"company_id": str(company), "price_rub": 11.5, "available_units": 5_000,
                  "moq_units": 1_000, "delivery_cost_rub": 100, "lead_time_days": 9,
                  "resource_kind": "capacity", "draft_id": draft.json()["id"]},
            headers=_auth(token))
        assert changed.json()["can_send"] is False
        assert any("черновик" in blocker.lower() or "товар" in blocker.lower()
                   for blocker in changed.json()["blockers"])


async def test_rollback_refuses_historical_reservation_links(client, db_session):
    from datetime import date as _date
    from datetime import timedelta as _td

    from app.resources import reserve

    user, company, token = await _seller_company(db_session)
    headers = _auth(token)
    path = f"/api/v1/companies/{company}/catalog-import"
    csv_text = ("Название;Категория;Цена;Минимум;Срок;Остаток;Внешний ID\n"
                "Болт М8;Строительство;12;100;2;5000;hist-1\n").encode()
    preview = await client.post(path, files={"file": ("c.csv", csv_text, "text/csv")}, headers=headers)
    consent = {"commit": "true", "human_approved": "true", "request_key": str(uuid.uuid4()),
               "expected_hash": preview.json()["content_hash"], "expected_revisions": "{}"}
    created = await client.post(path, files={"file": ("c.csv", csv_text, "text/csv")},
                                data=consent, headers=headers)
    product_id = created.json()["created_ids"][0]
    await reserve(db_session, company_id=company, anchor_type="test-hold", anchor_id=uuid.uuid4(),
                  units=100, deadline=_date.today() + _td(days=30),
                  resource_kind="stock", product_id=uuid.UUID(product_id))
    await db_session.commit()
    from app.resources import release
    anchor_id = (await db_session.execute(
        text("SELECT anchor_id FROM marketplace.resource_reservations WHERE company_id = :cid LIMIT 1"),
        {"cid": company})).scalar_one()
    await release(db_session, company_id=company, anchor_type="test-hold", anchor_id=anchor_id)
    await db_session.commit()
    refused = await client.post(f"/api/v1/companies/{company}/catalog-imports/{created.json()['import_id']}/rollback",
                                headers=headers)
    assert refused.status_code == 409


async def test_capacity_check_subtracts_held_reservations(client, db_session):
    from datetime import date as _date

    from app.models import CapacityEntry
    from app.resource_scopes import prepare_conversions
    from app.resources import reserve

    user, company, token = await _seller_company(db_session)
    _, _, _, need_id = await _buyer_with_published_need(client, db_session, volume=5_000)
    conversions = prepare_conversions([{"category_id": "packaging.paper-cups", "order_unit": "шт",
                                        "resource_units_per_order_unit": 2}], True)
    db_session.add(CapacityEntry(company_id=company, date=_date.today(), unit="шт",
                                 category_conversions=conversions, available_units=10))
    await db_session.commit()
    await reserve(db_session, company_id=company, anchor_type="deal-x", anchor_id=uuid.uuid4(),
                  units=3, deadline=_date.today() + timedelta(days=30),
                  category="Упаковка и тара", subcategory="Бумажные стаканы", unit="шт")
    await db_session.commit()
    base = {"commercial_terms": confirmed_quote_terms(), "company_id": str(company),
            "price_rub": 11.5, "available_units": 3, "moq_units": 1,
            "delivery_cost_rub": 100, "lead_time_days": 9, "resource_kind": "capacity"}
    over = await client.post(f"/api/v1/needs/{need_id}/offers", json=base, headers=_auth(token))
    assert over.status_code == 409
    _, _, _, need_id2 = await _buyer_with_published_need(client, db_session, volume=5_000)
    fits = await client.post(f"/api/v1/needs/{need_id2}/offers",
                             json={**base, "available_units": 2}, headers=_auth(token))
    assert fits.status_code == 201, fits.text
