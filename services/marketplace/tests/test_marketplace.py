from sqlalchemy import text

from conftest import make_company, make_token, make_user


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


async def test_full_flow(client, db_session):
    seller_user = await make_user(db_session)
    seller_company = await make_company(db_session, seller_user, can_buy=False, can_sell=True)
    seller_token = make_token(seller_user)

    buyer_user = await make_user(db_session)
    buyer_company = await make_company(db_session, buyer_user, can_buy=True, can_sell=False)
    buyer_token = make_token(buyer_user)

    # продавец создаёт и публикует товар
    r = await client.post(
        f"/api/v1/companies/{seller_company}/products",
        json={"name": "Стакан 400 мл PE", "category": "бумажные стаканы", "characteristics": {"volume_ml": 400}, "price_rub": 11.2, "moq_units": 20000, "lead_time_days": 9},
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
    assert r.json()["status"] == "open_for_offers"

    # продавец отвечает предложением
    r = await client.post(
        f"/api/v1/needs/{need_id}/offers",
        json={"company_id": str(seller_company), "price_rub": 11.0, "available_units": 120000, "lead_time_days": 9},
        headers=_auth(seller_token),
    )
    assert r.status_code == 201
    offer_id = r.json()["id"]

    # покупатель выбирает предложение
    r = await client.post(f"/api/v1/offers/{offer_id}/select", headers=_auth(buyer_token))
    assert r.status_code == 201
    assert r.json()["status"] == "created"
    assert r.json()["performed_by_user_id"] == str(buyer_user)
    assert r.json()["units"] == 120000

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
        files={"file": ("evidence.pdf", b"synthetic-pdf", "application/pdf")},
        headers=_auth(make_token(buyer)),
    )
    assert uploaded.status_code == 201
    file_id = uploaded.json()["files"][0]["id"]

    downloaded = await client.get(
        f"/api/v1/need-files/{file_id}/download", headers=_auth(make_token(buyer))
    )
    assert downloaded.status_code == 200
    assert downloaded.content == b"synthetic-pdf"

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
