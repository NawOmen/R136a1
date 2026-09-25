from sqlalchemy import select, func
from app.models import Product
from conftest import make_user, make_company, make_token
import uuid

CSV = 'Название;Категория;Цена;Минимум;Срок;Остаток;Характеристика: unit\nСтол офисный;Товары для бизнеса;7900;5;10;40;шт\n'.encode()


async def test_catalog_preview_confirmation_and_retry(client, db_session):
    user = await make_user(db_session)
    company = await make_company(db_session, user, can_buy=False, can_sell=True)
    headers = {"Authorization": f"Bearer {make_token(user)}"}
    path = f"/api/v1/companies/{company}/catalog-import"
    files = {"file": ("catalog.csv", CSV, "text/csv")}
    preview = await client.post(path, files=files, headers=headers)
    assert preview.status_code == 200, preview.text
    assert len(preview.json()["rows"]) == 1
    assert await db_session.scalar(select(func.count()).select_from(Product)) == 0
    consent = {"commit": "true", "human_approved": "true", "request_key": str(uuid.uuid4()), "expected_hash": preview.json()["content_hash"]}
    for _ in range(2):
        result = await client.post(path, files=files, headers=headers, data=consent)
        assert result.status_code == 200, result.text
        assert len(result.json()["created_ids"]) == 1
    assert await db_session.scalar(select(func.count()).select_from(Product)) == 1
    product = await db_session.scalar(select(Product))
    assert product.is_published is False
    assert product.stock_units == 40
    mismatch = await client.post(path, files={"file": ("changed.csv", CSV.replace(b"7900", b"8900"), "text/csv")}, headers=headers, data=consent)
    assert mismatch.status_code == 428


async def test_catalog_invalid_rows_cannot_partially_commit(client, db_session):
    user = await make_user(db_session)
    company = await make_company(db_session, user, can_buy=False, can_sell=True)
    headers = {"Authorization": f"Bearer {make_token(user)}"}
    path = f"/api/v1/companies/{company}/catalog-import"
    files = {"file": ("catalog.csv", CSV + 'Ошибка;Товары для бизнеса;nan;1;2;0;шт\n'.encode(), "text/csv")}
    preview = await client.post(path, files=files, headers=headers)
    assert preview.status_code == 200
    assert preview.json()["errors"][0]["line"] == 3
    result = await client.post(path, files=files, headers=headers, data={"commit": "true", "human_approved": "true", "expected_hash": preview.json()["content_hash"], "request_key": str(uuid.uuid4())})
    assert result.status_code == 422
    assert await db_session.scalar(select(func.count()).select_from(Product)) == 0
