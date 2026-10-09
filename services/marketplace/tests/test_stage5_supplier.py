"""Этап S05: поставщик — редактор, КП, лента, импорт, наполнение.

Проверяем приёмку S05.01–S05.05: ступени и версии карточек, идемпотентность КП,
фильтры и отклонения ленты, diff/откат импорта, идемпотентность сида.
"""
import uuid
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
                                     files={"file": (f"p{position}.png", b"\x89PNG\r\n\x1a\n", "image/png")},
                                     headers=_auth(token))
        assert uploaded.status_code == 201, uploaded.text
    sixth = await client.post(f"/api/v1/products/{created['id']}/images",
                              files={"file": ("p5.png", b"\x89PNG\r\n\x1a\n", "image/png")},
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


async def test_assortment_scope_and_seed_stories(db_session):
    from app.assortment import ASSORTMENT
    from seed_assortment import group_pictogram, seed_assortment

    assert len(ASSORTMENT) == 24
    keys = [item[0] for item in ASSORTMENT]
    assert len(set(keys)) == len(keys)
    families = {item[1] for item in ASSORTMENT}
    assert len(families) == 6
    for family in families:
        assert sum(1 for item in ASSORTMENT if item[1] == family) >= 3
    assert group_pictogram("Крепёж")[:8] == b"\x89PNG\r\n\x1a\n"

    for index, (title, can_sell) in enumerate((("ООО «Урал Комплект»", True), ("ООО «Регион Поставка»", True))):
        user = await make_user(db_session, email=f"seed-seller-{index}@demo.ru")
        company = await make_company(db_session, user, can_buy=False, can_sell=can_sell)
        await db_session.execute(
            text("UPDATE auth.companies SET display_name = :title WHERE id = :id"),
            {"title": title, "id": company},
        )
        await db_session.commit()
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
    assert first_products > before_products
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
    from app.models import ProductImage
    images = (await db_session.execute(select(ProductImage))).scalars().all()
    assert len(images) == 6
    assert all(image.content_type == "image/png" for image in images)
    assert len({image.product_id for image in images}) == 6
