"""Review-only acceptance checks. Not part of the PR under review."""
from datetime import date, timedelta

from conftest import grant_packaging_documents, make_company, make_token, make_user
from test_category_admission import _auth, _seller_with_product


async def test_medical_parent_without_subcategory_must_not_publish(client, db_session):
    _, _, token, product_id = await _seller_with_product(
        client, db_session, category="Медицина и гигиена", subcategory=None
    )
    result = await client.post(
        f"/api/v1/products/{product_id}/publish",
        json={"published": True}, headers=_auth(token),
    )
    assert result.status_code == 409, f"Expected 409, got {result.status_code}: published={result.json().get('is_published')}"


async def test_documents_for_different_subcategory_must_not_admit_cups(client, db_session):
    user, company, token, product_id = await _seller_with_product(client, db_session)
    await grant_packaging_documents(
        db_session, company, subcategory="Картонные коробки", decision_user_id=user
    )
    result = await client.post(
        f"/api/v1/products/{product_id}/publish",
        json={"published": True}, headers=_auth(token),
    )
    assert result.status_code == 409, f"Expected 409, got {result.status_code}: published={result.json().get('is_published')}"


async def test_cups_deal_without_documents_must_not_be_created(client, db_session):
    seller = await make_user(db_session)
    seller_company = await make_company(db_session, seller, can_buy=False, can_sell=True)
    buyer = await make_user(db_session)
    buyer_company = await make_company(db_session, buyer, can_buy=True, can_sell=False)
    buyer_headers = _auth(make_token(buyer))
    need = await client.post('/api/v1/needs', headers=buyer_headers, json={
        'company_id': str(buyer_company), 'category': 'бумажные стаканы',
        'characteristics': {'volume_ml': 400}, 'volume_units': 120000,
        'budget_rub': 1900000, 'deadline_date': (date.today() + timedelta(days=90)).isoformat(),
        'visibility': 'open_anonymized',
    })
    assert need.status_code == 201, need.text
    need_id = need.json()['id']
    published = await client.post(f'/api/v1/needs/{need_id}/publish', headers=buyer_headers)
    assert published.status_code == 200, published.text
    offer = await client.post(f'/api/v1/needs/{need_id}/offers', headers=_auth(make_token(seller)), json={
        'company_id': str(seller_company), 'price_rub': 11.0, 'available_units': 120000,
        'lead_time_days': 9, 'delivery_cost_rub': 10000,
    })
    assert offer.status_code == 201, offer.text
    result = await client.post(f"/api/v1/offers/{offer.json()['id']}/select", headers=buyer_headers)
    assert result.status_code == 409, f"Expected 409, got {result.status_code}: status={result.json().get('status')}"
