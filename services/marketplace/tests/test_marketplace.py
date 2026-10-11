from synthetic_files import PNG, PDF

from conftest import confirmed_quote_terms
from sqlalchemy import func, select, text

from conftest import grant_capacity, grant_packaging_documents, make_company, make_token, make_user


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


async def test_full_flow(client, db_session):
    seller_user = await make_user(db_session)
    seller_company = await make_company(db_session, seller_user, can_buy=False, can_sell=True)
    seller_token = make_token(seller_user)

    buyer_user = await make_user(db_session)
    buyer_company = await make_company(db_session, buyer_user, can_buy=True, can_sell=False)
    buyer_token = make_token(buyer_user)

    # категорийный допуск: без подтверждённых документов публикация упаковки запрещена
    await grant_packaging_documents(db_session, seller_company, decision_user_id=seller_user, confirms={"material": ["крафт-картон"]})

    await grant_capacity(db_session, seller_company, 120_000)

    # продавец создаёт и публикует товар
    r = await client.post(
        f"/api/v1/companies/{seller_company}/products",
        json={"name": "Стакан 400 мл PE", "category": "бумажные стаканы", "characteristics": {"volume_ml": 400, "material": "крафт-картон"}, "price_rub": 11.2, "moq_units": 20000, "lead_time_days": 9},
        headers=_auth(seller_token),
    )
    assert r.status_code == 201
    product_id = r.json()["id"]

    r = await client.post(f"/api/v1/products/{product_id}/publish", json={"published": True}, headers=_auth(seller_token))
    assert r.status_code == 200

    r = await client.get("/api/v1/products")
    assert any(p["id"] == product_id for p in r.json())

    # покупатель создаёт адрес и потребность
    r = await client.post(
        f"/api/v1/companies/{buyer_company}/addresses",
        json={"address": "г. Москва, ул. Тестовая, 1", "city": "Москва", "region": "г. Москва", "is_default": True},
        headers=_auth(buyer_token),
    )
    assert r.status_code == 201
    address_id = r.json()["id"]

    r = await client.post(
        "/api/v1/needs",
        json={"company_id": str(buyer_company), "category": "бумажные стаканы", "characteristics": {"volume_ml": 400}, "volume_units": 120000, "budget_rub": 1900000, "deadline_date": "2026-10-30", "delivery_address_id": str(address_id), "visibility": "open_anonymized"},
        headers=_auth(buyer_token),
    )
    assert r.status_code == 201
    need_id = r.json()["id"]
    assert r.json()["status"] == "draft"

    r = await client.post(f"/api/v1/needs/{need_id}/publish", headers=_auth(buyer_token))
    assert r.status_code == 200
    assert r.json()["status"] == "waiting_for_match"
    assert r.json()["no_match_reason"]

    # продавец отвечает предложением
    r = await client.post(
        f"/api/v1/needs/{need_id}/offers",
        json={'commercial_terms': confirmed_quote_terms(), "company_id": str(seller_company), "product_id":product_id, "price_rub": 11.0, "available_units": 120000, "lead_time_days": 9, "delivery_cost_rub": 10000},
        headers=_auth(seller_token),
    )
    assert r.status_code == 201
    offer_id = r.json()["id"]

    # покупатель выбирает предложение
    r = await client.post(f"/api/v1/offers/{offer_id}/select", headers=_auth(buyer_token), json={"expected_revision": 1, "human_approved": True})
    assert r.status_code == 201
    assert r.json()["status"] == "created"
    assert r.json()["performed_by_user_id"] == str(buyer_user)
    assert r.json()["units"] == 120000
    assert r.json()["total_price_rub"] == 1330000

    r = await client.get(f"/api/v1/needs/{need_id}", headers=_auth(buyer_token))
    assert r.json()["status"] == "matched"


async def test_unverified_company_can_create_draft_but_cannot_publish(client, db_session):
    user = await make_user(db_session)
    company = await make_company(db_session, user, can_buy=True, can_sell=False, verified=False)
    r = await client.post(
        "/api/v1/needs",
        json={"company_id": str(company), "category": "бумажные стаканы", "characteristics": {}, "volume_units": 1000, "deadline_date": "2026-10-30", "visibility": "open_anonymized"},
        headers=_auth(make_token(user)),
    )
    assert r.status_code == 201
    assert r.json()["status"] == "draft"

    publish = await client.post(
        f"/api/v1/needs/{r.json()['id']}/publish", headers=_auth(make_token(user))
    )
    assert publish.status_code == 403


async def test_unverified_company_cannot_publish_product(client, db_session):
    user = await make_user(db_session)
    company = await make_company(db_session, user, can_buy=False, can_sell=True, verified=False)
    created = await client.post(
        f"/api/v1/companies/{company}/products",
        json={"name": "Стакан", "category": "бумажные стаканы", "characteristics": {}, "price_rub": 10, "moq_units": 1000, "lead_time_days": 5},
        headers=_auth(make_token(user)),
    )
    assert created.status_code == 201
    publish = await client.post(
        f"/api/v1/products/{created.json()['id']}/publish",
        json={"published": True},
        headers=_auth(make_token(user)),
    )
    assert publish.status_code == 403


async def test_blocked_user_cannot_use_marketplace(client, db_session):
    user = await make_user(db_session)
    await db_session.execute(
        text("UPDATE auth.users SET account_status = 'blocked' WHERE id = :id"), {"id": user}
    )
    await db_session.commit()
    r = await client.get("/api/v1/notifications", headers=_auth(make_token(user)))
    assert r.status_code == 401


async def test_open_feed_is_anonymized(client, db_session):
    user = await make_user(db_session)
    company = await make_company(db_session, user, can_buy=True, can_sell=False)
    created = await client.post(
        "/api/v1/needs",
        json={"company_id": str(company), "category": "бумажные стаканы", "characteristics": {}, "volume_units": 1000, "budget_rub": 20000, "deadline_date": "2026-10-30", "visibility": "open_anonymized"},
        headers=_auth(make_token(user)),
    )
    await client.post(
        f"/api/v1/needs/{created.json()['id']}/publish", headers=_auth(make_token(user))
    )

    seller = await make_user(db_session)
    feed = await client.get("/api/v1/needs", headers=_auth(make_token(seller)))
    assert feed.status_code == 200
    item = feed.json()[0]
    assert "company_id" not in item
    assert "created_by_user_id" not in item
    assert "budget_rub" not in item
    assert "delivery_address_id" not in item
    assert "files" not in item

    detail = await client.get(
        f"/api/v1/needs/{created.json()['id']}", headers=_auth(make_token(seller))
    )
    assert detail.status_code == 200
    assert "company_id" not in detail.json()
    assert "budget_rub" not in detail.json()


async def test_need_file_download_is_available_only_to_buyer(
    client, db_session, monkeypatch
):
    stored: dict[str, bytes] = {}

    def fake_upload(key: str, data: bytes, content_type: str) -> str:
        stored[key] = data
        return key

    def fake_download(key: str) -> bytes:
        return stored[key]

    monkeypatch.setattr("app.api.needs.upload_object", fake_upload)
    monkeypatch.setattr("app.api.needs.download_object", fake_download)

    buyer = await make_user(db_session)
    company = await make_company(db_session, buyer, can_buy=True, can_sell=False)
    created = await client.post(
        "/api/v1/needs",
        json={"company_id": str(company), "category": "бумажные стаканы", "characteristics": {}, "volume_units": 1000, "deadline_date": "2026-10-30", "visibility": "open_anonymized"},
        headers=_auth(make_token(buyer)),
    )
    need_id = created.json()["id"]
    uploaded = await client.post(
        f"/api/v1/needs/{need_id}/files",
        files={"file": ("evidence.pdf", PDF, "application/pdf")},
        headers=_auth(make_token(buyer)),
    )
    assert uploaded.status_code == 201
    file_id = uploaded.json()["files"][0]["id"]

    text_uploaded = await client.post(
        f"/api/v1/needs/{need_id}/files",
        files={"file": ("requirements.md", b"synthetic requirements", "text/markdown")},
        headers=_auth(make_token(buyer)),
    )
    assert text_uploaded.status_code == 201
    assert any(
        item["content_type"] == "text/markdown"
        for item in text_uploaded.json()["files"]
    )

    downloaded = await client.get(
        f"/api/v1/need-files/{file_id}/download", headers=_auth(make_token(buyer))
    )
    assert downloaded.status_code == 200
    assert downloaded.content == PDF

    outsider = await make_user(db_session)
    forbidden = await client.get(
        f"/api/v1/need-files/{file_id}/download", headers=_auth(make_token(outsider))
    )
    assert forbidden.status_code == 404


async def test_need_file_rejects_unsupported_type(client, db_session):
    buyer = await make_user(db_session)
    company = await make_company(db_session, buyer, can_buy=True, can_sell=False)
    created = await client.post(
        "/api/v1/needs",
        json={"company_id": str(company), "category": "бумажные стаканы", "characteristics": {}, "volume_units": 1000, "deadline_date": "2026-10-30", "visibility": "open_anonymized"},
        headers=_auth(make_token(buyer)),
    )
    uploaded = await client.post(
        f"/api/v1/needs/{created.json()['id']}/files",
        files={"file": ("payload.exe", b"synthetic", "application/octet-stream")},
        headers=_auth(make_token(buyer)),
    )
    assert uploaded.status_code == 415


async def test_company_without_seller_cannot_create_product(client, db_session):
    user = await make_user(db_session)
    company = await make_company(db_session, user, can_buy=True, can_sell=False)
    r = await client.post(
        f"/api/v1/companies/{company}/products",
        json={"name": "Стакан", "category": "бумажные стаканы", "characteristics": {}, "price_rub": 10, "moq_units": 1000, "lead_time_days": 5},
        headers=_auth(make_token(user)),
    )
    assert r.status_code == 403


async def test_demo_seed_separates_buyer_address_and_seller_data(
    db_session, session_factory, monkeypatch
):
    import seed as marketplace_seed
    from app.models import DeliveryAddress, Product, ProductionProfile

    buyer_user = await make_user(db_session, email="demo@demo.ru")
    buyer_company = await make_company(
        db_session, buyer_user, can_buy=True, can_sell=True
    )
    seller_user = await make_user(db_session, email="seller@demo.ru")
    seller_company = await make_company(
        db_session, seller_user, can_buy=False, can_sell=True
    )
    await db_session.execute(
        text("UPDATE auth.companies SET display_name = :name WHERE id = :id"),
        {"name": marketplace_seed.BUYER_COMPANY_NAME, "id": buyer_company},
    )
    await db_session.execute(
        text("UPDATE auth.companies SET display_name = :name WHERE id = :id"),
        {"name": marketplace_seed.SELLER_COMPANY_NAME, "id": seller_company},
    )
    await db_session.commit()

    monkeypatch.setattr(marketplace_seed, "SessionLocal", session_factory)
    await marketplace_seed.seed()

    buyer_addresses = (
        await db_session.execute(
            select(DeliveryAddress).where(
                DeliveryAddress.company_id == buyer_company
            )
        )
    ).scalars().all()
    seller_addresses = (
        await db_session.execute(
            select(DeliveryAddress).where(
                DeliveryAddress.company_id == seller_company
            )
        )
    ).scalars().all()
    products = (
        await db_session.execute(
            select(Product).where(Product.company_id == seller_company)
        )
    ).scalars().all()

    assert len(buyer_addresses) == 1
    assert buyer_addresses[0].is_default is True
    assert seller_addresses == []
    assert await db_session.get(ProductionProfile, seller_company) is not None
    from app.assortment import ASSORTMENT
    assert len(products) == 2 + len(ASSORTMENT)
    assert len({product.category for product in products}) >= 4
    await marketplace_seed.seed()
    count_after_retry = await db_session.scalar(
        select(func.count()).select_from(Product).where(Product.company_id == seller_company)
    )
    assert count_after_retry == len(products)
