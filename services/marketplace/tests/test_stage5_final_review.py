"""Регрессии финального ревью S05: согласование, ресурсы и повтор КП."""
import json
import uuid
from datetime import date, timedelta
import pytest
from sqlalchemy import func, select, text
from app.models import Need, Offer, ResourceReservation
from conftest import confirmed_quote_terms, grant_capacity
from test_category_admission import _auth
from test_offer_draft_and_scorecard import _buyer_with_published_need, _passport, _seller_company
from test_stage5_supplier import _product
from test_requirements_stage03 import gateway_contract

async def cup(client, company, token, stock=100):
    return await _product(client, token, company, category='Упаковка и тара', subcategory='Бумажные стаканы', characteristics={'unit': 'шт', 'volume_ml': 400, 'coating': 'PE', 'material': 'крафт-картон'}, price_tiers=[], moq_units=1, stock_units=stock)

async def send(client, company, token, need, **extra):
    return await client.post(f'/api/v1/needs/{need}/offers', json=offer_payload(company) | extra, headers=_auth(token))

def csv_file(price=13, stock=4000, external='bolt-m8', name='Болт М8'):
    return f'Название;Категория;Подкатегория;Цена;Минимум;Срок;Остаток;Внешний ID;Характеристика: unit;Характеристика: material\n{name};Строительство;Крепёж;{price};100;2;{stock};{external};шт;сталь\n'.encode()

async def preview(client, company, token, content):
    result = await client.post(f'/api/v1/companies/{company}/catalog-import', files={'file': ('c.csv', content, 'text/csv')}, headers=_auth(token))
    assert result.status_code == 200 and result.json()['errors'] == [], result.text
    return result.json()

async def rollback(client, company, token, import_id):
    return await client.post(f'/api/v1/companies/{company}/catalog-imports/{import_id}/rollback', headers=_auth(token))

async def get_product(client, company, token, identifier):
    rows = (await client.get(f'/api/v1/companies/{company}/products', headers=_auth(token))).json()
    return next((row for row in rows if row['id'] == identifier))

async def commit(client, company, token, content, shown, key=None):
    return await client.post(f'/api/v1/companies/{company}/catalog-import', files={'file': ('c.csv', content, 'text/csv')}, data={'commit': 'true', 'human_approved': 'true', 'request_key': key or str(uuid.uuid4()), 'expected_hash': shown['content_hash'], 'expected_revisions': json.dumps({r['product_id']: {'revision': r['product_revision'], 'status': r['import_status']} for r in shown['rows'] if r.get('product_id')})}, headers=_auth(token))

def offer_payload(company):
    return {'company_id': str(company), 'commercial_terms': confirmed_quote_terms(), 'price_rub': 11.5, 'available_units': 6, 'moq_units': 1, 'lead_time_days': 2, 'delivery_cost_rub': 0, 'request_key': str(uuid.uuid4())}

async def test_rollback_created_draft_referenced_by_offer(client, db_session):
    _, company, token = await _seller_company(db_session)
    content = 'Название;Категория;Подкатегория;Цена;Минимум;Срок;Остаток;Внешний ID;Характеристика: unit;Характеристика: volume_ml;Характеристика: coating;Характеристика: material\nСтакан;Упаковка и тара;Бумажные стаканы;12;1;2;100;cup-offer;шт;400;PE;крафт-картон\n'.encode()
    shown = await preview(client, company, token, content)
    imported = await commit(client, company, token, content, shown)
    assert imported.status_code == 200, imported.text
    product_id = imported.json()['created_ids'][0]
    _, _, _, need_id = await _buyer_with_published_need(client, db_session, volume=6)
    created = await send(client, company, token, need_id, product_id=product_id, resource_kind='stock')
    assert created.status_code == 201, created.text
    assert await db_session.scalar(select(func.count(ResourceReservation.id))) == 0
    rolled = await rollback(client, company, token, imported.json()['import_id'])
    assert rolled.status_code == 409, rolled.text
    assert await get_product(client, company, token, product_id) is not None
    assert await db_session.get(Offer, uuid.UUID(created.json()['id'])) is not None

@pytest.mark.parametrize('mode', ['different_key', 'cancelled_need', 'expired_need', 'same_key'])
async def test_preview_idempotency_matches_create(client, db_session, mode):
    _, company, token = await _seller_company(db_session)
    _, _, buyer_token, need_id = await _buyer_with_published_need(client, db_session, volume=6)
    await grant_capacity(db_session, company, 100)
    payload = offer_payload(company)
    first = await client.post(f'/api/v1/needs/{need_id}/offers', json=payload, headers=_auth(token))
    assert first.status_code == 201, first.text
    if mode == 'different_key':
        payload['request_key'] = str(uuid.uuid4())
    elif mode == 'cancelled_need':
        cancelled = await client.post(f'/api/v1/needs/{need_id}/cancel', headers=_auth(buyer_token))
        assert cancelled.status_code == 200 and cancelled.json()['status'] == 'cancelled', cancelled.text
    elif mode == 'expired_need':
        need = await db_session.get(Need, uuid.UUID(need_id))
        need.deadline_date = date.today() - timedelta(days=1)
        need.valid_until = need.deadline_date
        await db_session.commit()
    shown = await client.post(f'/api/v1/needs/{need_id}/offers/preview', json=payload, headers=_auth(token))
    assert shown.status_code == 200, shown.text
    assert shown.json()['can_send'] is (mode == 'same_key'), shown.text
    assert bool(shown.json()['blockers']) is (mode != 'same_key')
    sent = await client.post(f'/api/v1/needs/{need_id}/offers', json=payload, headers=_auth(token))
    assert sent.status_code == (200 if mode == 'same_key' else 409), sent.text
    if mode == 'same_key':
        assert sent.json()['id'] == first.json()['id']
        assert shown.json()['existing_offer_id'] == first.json()['id']

@pytest.mark.parametrize("retry", [False, True])
async def test_preview_rejects_changed_requirements_source(client, db_session, gateway_contract, retry):
    _, company, token = await _seller_company(db_session)
    buyer_user, buyer, buyer_token, need_id = await _buyer_with_published_need(client, db_session, volume=6)
    await grant_capacity(db_session, company, 100)
    run = uuid.uuid4()
    has_type = await db_session.scalar(text("SELECT EXISTS(SELECT 1 FROM information_schema.columns WHERE table_schema='agents' AND table_name='agent_runs' AND column_name='agent_type')"))
    columns = ",agent_type,requested_route,input_summary" if has_type else ""
    values = ",'buyer_investigator','local',''" if has_type else ""
    await db_session.execute(text(f"INSERT INTO agents.agent_runs (id,revision,state,result,user_id,company_id{columns}) VALUES (:id,2,'confirmed_by_user',CAST(:result AS JSONB),:uid,:cid{values})"),
        {'id': run, 'uid': buyer_user, 'cid': buyer, 'result': json.dumps({'can_confirm': True, 'properties': [], 'conflicts': [], 'questions': []})})
    await db_session.commit()
    need = await db_session.get(Need, uuid.UUID(need_id))
    update = {'company_id': str(buyer), 'category': need.category, 'subcategory': need.subcategory, 'characteristics': need.characteristics, 'volume_units': need.volume_units, 'budget_rub': str(need.budget_rub), 'deadline_date': str(need.deadline_date), 'valid_until': str(need.valid_until), 'delivery_address_id': str(need.delivery_address_id), 'expected_revision': need.revision, 'agent_run_id': str(run), 'agent_run_revision': 2}
    shown = await client.post(f'/api/v3/needs/{need_id}/edit-preview', json=update, headers=_auth(buyer_token))
    assert shown.status_code == 200, shown.text
    applied = await client.put(f'/api/v3/needs/{need_id}', json=update | {'impact_hash': shown.json()['impact_hash']}, headers=_auth(buyer_token))
    assert applied.status_code == 200, applied.text
    payload = offer_payload(company)
    current = await client.post(f'/api/v1/needs/{need_id}/offers/preview', json=payload, headers=_auth(token))
    assert current.status_code == 200 and current.json()['can_send'] is True, current.text
    if retry:
        first = await client.post(f'/api/v1/needs/{need_id}/offers', json=payload, headers=_auth(token))
        assert first.status_code == 201, first.text
    await db_session.execute(text("UPDATE agents.agent_runs SET revision=3,state='needs_clarification' WHERE id=:id"), {'id': run})
    await db_session.commit()
    shown = await client.post(f'/api/v1/needs/{need_id}/offers/preview', json=payload, headers=_auth(token))
    assert shown.status_code == 409 and 'Источник требований' in shown.text, shown.text
    sent = await client.post(f'/api/v1/needs/{need_id}/offers', json=payload, headers=_auth(token))
    assert sent.status_code == 409 and 'Источник требований' in sent.text, sent.text

@pytest.mark.parametrize('scope,day_offset', [('construction.fasteners', 0), ('packaging.paper-cups', 31), ('packaging.paper-cups', -1)])
async def test_capacity_calendar_without_usable_entries(client, db_session, scope, day_offset):
    _, company, token = await _seller_company(db_session)
    _, _, _, need_id = await _buyer_with_published_need(client, db_session, volume=6)
    await grant_capacity(db_session, company, 100, day=date.today() + timedelta(days=day_offset), category_id=scope)
    payload = {'company_id': str(company), 'commercial_terms': confirmed_quote_terms(), 'price_rub': 11.5, 'available_units': 6, 'moq_units': 1, 'lead_time_days': 2, 'delivery_cost_rub': 0, 'request_key': str(uuid.uuid4())}
    shown = await client.post(f'/api/v1/needs/{need_id}/offers/preview', json=payload, headers=_auth(token))
    assert shown.status_code == 200 and shown.json()['can_send'] is False, shown.text
    created = await client.post(f'/api/v1/needs/{need_id}/offers', json=payload, headers=_auth(token))
    assert created.status_code == 409, created.text
    assert await db_session.scalar(select(func.count(Offer.id))) == 0

async def test_preview_allows_valid_idempotent_draft_retry(client, db_session):
    _, company, token = await _seller_company(db_session)
    await _passport(client, token, company, business_kind='stock_supplier', min_order=1)
    await cup(client, company, token, stock=100)
    _, _, _, need_id = await _buyer_with_published_need(client, db_session, volume=6)
    draft = await client.post(f'/api/v1/needs/{need_id}/offer-draft', json={'company_id': str(company)}, headers=_auth(token))
    assert draft.status_code == 201, draft.text
    payload = {'company_id': str(company), 'commercial_terms': confirmed_quote_terms(), 'price_rub': 11.5, 'available_units': 6, 'moq_units': 1, 'lead_time_days': 2, 'delivery_cost_rub': 0, 'request_key': str(uuid.uuid4()), 'draft_id': draft.json()['id']}
    created = await client.post(f'/api/v1/needs/{need_id}/offers', json=payload, headers=_auth(token))
    assert created.status_code == 201, created.text
    shown = await client.post(f'/api/v1/needs/{need_id}/offers/preview', json=payload, headers=_auth(token))
    assert shown.status_code == 200 and shown.json()['can_send'] is True, shown.text
    assert shown.json()['existing_offer_id'] == created.json()['id']
    retried = await client.post(f'/api/v1/needs/{need_id}/offers', json=payload, headers=_auth(token))
    assert retried.status_code == 200 and retried.json()['id'] == created.json()['id'], retried.text

@pytest.mark.parametrize('binding', [None, 1, {'revision': 1}, {'revision': 1, 'status': None}, {'revision': 1, 'status': 'published_skipped'}, {'revision': 1, 'status': True}, {'revision': True, 'status': 'changed'}, {'revision': '1', 'status': 'changed'}])
async def test_import_requires_complete_preview_binding(client, db_session, binding):
    _, company, token = await _seller_company(db_session)
    product = await _product(client, token, company, external_id='bolt-m8')
    content = csv_file(price=15)
    shown = await preview(client, company, token, content)
    assert shown['rows'][0]['import_status'] == 'changed'
    path = f'/api/v1/companies/{company}/catalog-import'
    result = await client.post(path, files={'file': ('c.csv', content, 'text/csv')}, data={'commit': 'true', 'human_approved': 'true', 'request_key': str(uuid.uuid4()), 'expected_hash': shown['content_hash'], 'expected_revisions': json.dumps({product['id']: binding})}, headers=_auth(token))
    assert result.status_code == 409, result.text
    saved = await get_product(client, company, token, product['id'])
    assert saved['price_rub'] == 12 and saved['revision'] == 1
    key = str(uuid.uuid4())
    accepted = await commit(client, company, token, content, shown, key=key)
    assert accepted.status_code == 200, accepted.text
    repeated = await commit(client, company, token, content, shown, key=key)
    assert repeated.status_code == 200 and repeated.json()['import_id'] == accepted.json()['import_id']
    saved = await get_product(client, company, token, product['id'])
    assert saved['price_rub'] == 15 and saved['revision'] == 2

async def test_unknown_capacity_remains_unknown(client, db_session):
    _, company, token = await _seller_company(db_session)
    _, _, _, need_id = await _buyer_with_published_need(client, db_session, volume=6)
    payload = offer_payload(company)
    shown = await client.post(f'/api/v1/needs/{need_id}/offers/preview', json=payload, headers=_auth(token))
    assert shown.status_code == 200 and shown.json()['can_send'] is False, shown.text
    assert await db_session.scalar(select(func.count(Offer.id))) == 0
    sent = await client.post(f'/api/v1/needs/{need_id}/offers', json=payload, headers=_auth(token))
    assert sent.status_code == 409 and "мощность" in sent.text
    assert await db_session.scalar(select(func.count(Offer.id))) == 0

@pytest.mark.parametrize('change,expected_status', [({'request_key': None}, 409), ({'price_rub': 12}, 409), ({'moq_units': 7}, 422), ({'valid_until': str(date.today() - timedelta(days=1))}, 422), ({'draft_id': str(uuid.uuid4())}, 404)])
async def test_preview_retry_preserves_request_checks(client, db_session, change, expected_status):
    _, company, token = await _seller_company(db_session)
    _, _, _, need_id = await _buyer_with_published_need(client, db_session, volume=6)
    await grant_capacity(db_session, company, 100)
    payload = offer_payload(company)
    first = await client.post(f'/api/v1/needs/{need_id}/offers', json=payload, headers=_auth(token))
    assert first.status_code == 201, first.text
    payload.update(change)
    shown = await client.post(f'/api/v1/needs/{need_id}/offers/preview', json=payload, headers=_auth(token))
    assert shown.status_code == 200 and shown.json()['can_send'] is False, shown.text
    assert shown.json()['blockers']
    sent = await client.post(f'/api/v1/needs/{need_id}/offers', json=payload, headers=_auth(token))
    assert sent.status_code == expected_status, sent.text
    assert await db_session.scalar(select(func.count(Offer.id))) == 1
