"""Серверные регрессии допуска и обновления КП после изменения потребности."""
import uuid
import pytest
from sqlalchemy import select
from app.models import Offer
from conftest import confirmed_quote_terms, grant_capacity, grant_packaging_documents
from test_category_admission import _auth
from test_offer_draft_and_scorecard import _buyer_with_published_need, _seller_company, _passport


async def setup_proposal(client, db_session):
    seller, company, token = await _seller_company(db_session)
    await _passport(client, token, company, min_order=1000)
    await grant_capacity(db_session, company, 20000)
    _, _, buyer_token, need_id = await _buyer_with_published_need(client, db_session, volume=5000)
    body = dict(company_id=str(company), price_rub='11.50', available_units=10000,
                moq_units=1000, delivery_cost_rub='3000.00', lead_time_days=2,
                commercial_terms=confirmed_quote_terms())
    return seller, company, token, buyer_token, need_id, body


async def test_missing_admission_blocks_preview_and_direct_send_without_creating_offer(client, db_session):
    _, _, seller_token, _, need_id, body = await setup_proposal(client, db_session)
    preview = await client.post(f'/api/v1/needs/{need_id}/offers/preview', json=body, headers=_auth(seller_token))
    assert preview.status_code == 200, preview.text
    assert not preview.json()['can_send']
    assert any('допуск' in reason.lower() for reason in preview.json()['blockers'])
    assert preview.json()['warnings'] == []
    sent = await client.post(f'/api/v1/needs/{need_id}/offers', json=body, headers=_auth(seller_token))
    assert sent.status_code == 409, sent.text
    assert await db_session.scalar(select(Offer).where(Offer.need_id == uuid.UUID(need_id))) is None


@pytest.mark.parametrize("edit_count", [1, 2])
async def test_seller_can_reconfirm_stale_offer_against_changed_need(client, db_session, edit_count):
    seller, company, seller_token, buyer_token, need_id, body = await setup_proposal(client, db_session)
    await grant_packaging_documents(db_session, company, decision_user_id=seller,
                                   confirms={'material':['крафт-картон'], 'coating':['PE']})
    sent = await client.post(f'/api/v1/needs/{need_id}/offers', json=body, headers=_auth(seller_token))
    assert sent.status_code == 201, sent.text
    original = sent.json()
    need = (await client.get(f'/api/v1/needs/{need_id}', headers=_auth(buyer_token))).json()
    edit = {key: need[key] for key in ('company_id','category','subcategory','characteristics','volume_units',
                                     'budget_rub','deadline_date','delivery_address_id','visibility','valid_until')}
    for index in range(edit_count):
        edit.update(expected_revision=need['revision']+index, volume_units=6000+index*1000)
        impact = await client.post(f'/api/v3/needs/{need_id}/edit-preview', json=edit, headers=_auth(buyer_token))
        assert impact.status_code == 200, impact.text
        changed = await client.put(f'/api/v3/needs/{need_id}', json={**edit,'impact_hash':impact.json()['impact_hash']}, headers=_auth(buyer_token))
        assert changed.status_code == 200, changed.text
    current = (await client.get(f'/api/v1/needs/{need_id}/offers', headers=_auth(seller_token))).json()
    assert current[0]['status'] == 'stale'
    assert 'Спецификация изменилась' in changed.json()['no_match_reason']
    stale_revision = current[0]['revision']
    assert stale_revision == original['revision'] + edit_count
    old_write = await client.patch(f"/api/v1/offers/{original['id']}", json={'expected_revision': stale_revision - 1, 'price_rub':'10.00'}, headers=_auth(seller_token))
    assert old_write.status_code == 409
    preview = await client.post(f'/api/v1/needs/{need_id}/offers/preview',
        json={**body, 'offer_id': original['id'], 'expected_revision': stale_revision}, headers=_auth(seller_token))
    assert preview.status_code == 200 and preview.json()['can_send'], preview.text
    refreshed = await client.patch(f"/api/v1/offers/{original['id']}",
        json={'expected_revision':stale_revision, 'price_rub':'11.00'}, headers=_auth(seller_token))
    assert refreshed.status_code == 200, refreshed.text
    result = refreshed.json()
    assert result['status'] == 'sent' and result['revision'] == stale_revision+1
    assert result['commercial_quote']['need']['revision'] == changed.json()['revision']
    assert result['commercial_quote']['estimate']['complete']
    assert len((await client.get(f'/api/v1/needs/{need_id}/offers', headers=_auth(seller_token))).json()) == 1
    stale_write = await client.patch(f"/api/v1/offers/{original['id']}",
        json={'expected_revision':original['revision'], 'price_rub':'10.00'}, headers=_auth(seller_token))
    assert stale_write.status_code == 409


async def test_multiple_rejection_reasons_fit_database_field_and_survive_coalition_hint(client, db_session):
    from datetime import date, timedelta
    from app.matching import run_market_rematch
    from app.models import Need
    seller, company, _, buyer_token, need_id, _ = await setup_proposal(client, db_session)
    need = await db_session.get(Need, uuid.UUID(need_id))
    db_session.add(Offer(need_id=need.id, company_id=company, created_by_user_id=seller,
        price_rub=1000, available_units=1, moq_units=30000, lead_time_days=120,
        valid_until=date.today()-timedelta(days=1), status='sent',
        commercial_quote={'need':{'revision':need.revision},'estimate':{'complete':True,'total_rub':'999999'}}))
    await db_session.commit()
    await run_market_rematch(db_session, 'regression_multi_check', need.id)
    await db_session.commit()
    response = await client.get(f'/api/v1/needs/{need_id}', headers=_auth(buyer_token))
    assert response.status_code == 200, response.text
    reason = response.json()['no_match_reason']
    assert len(reason) <= 500
    assert 'Допуск продавца не подтверждён' in reason
    assert 'Подтверждение соответствия упаковки' in reason
    assert 'MOQ, бюджет или срок' not in reason
