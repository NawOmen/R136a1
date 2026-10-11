import uuid
from datetime import date, timedelta
from sqlalchemy import text
from app.models import Offer, CapacityEntry, ProductImage
from app.category_registry import resolve_category
from app.matching import order_unit
from conftest import make_company, make_marketplace_admin, make_token, make_user
from test_stage11 import _make_need, _auth

async def test_repeat_preview_does_not_report_buyer_capacity_as_supplier_capacity(client, db_session):
    buyer = await make_user(db_session)
    buyer_company = await make_company(db_session, buyer, can_buy=True, can_sell=False)
    need = await _make_need(client, buyer, buyer_company)
    seller = await make_user(db_session)
    seller_company = await make_company(db_session, seller, can_buy=False, can_sell=True)
    leaf=resolve_category(need['category'],need.get('subcategory'))
    conversion={'category_id':leaf['id'],'order_unit':order_unit(need['characteristics']),'profile_version':leaf['technical_profile']['version'],'resource_units_per_order_unit':1}
    for company, quantity in [(buyer_company, 1000), (seller_company, 50)]:
        db_session.add(CapacityEntry(company_id=company, date=date.today()+timedelta(days=5), category='', unit='шт', available_units=quantity, category_conversions=[conversion]))
    db_session.add(Offer(need_id=uuid.UUID(need['id']), company_id=seller_company, price_rub=10, available_units=5, lead_time_days=1, valid_until=date.today()+timedelta(days=10), commercial_quote={'estimate':{'complete':True,'total_rub':'50'}}))
    await db_session.commit()
    r=await client.post(f"/api/v1/needs/{need['id']}/repeat-preview",headers=_auth(make_token(buyer)))
    assert r.status_code == 200, r.text
    capacities=[c['now'] for c in r.json()['changes'] if c['field']=='Свободная мощность']
    assert '1000' not in capacities, r.json()

async def test_repeat_preview_excludes_expired_sent_offer(client, db_session):
    buyer = await make_user(db_session)
    buyer_company = await make_company(db_session,buyer,can_buy=True,can_sell=False)
    need=await _make_need(client,buyer,buyer_company)
    seller=await make_user(db_session)
    seller_company=await make_company(db_session,seller,can_buy=False,can_sell=True)
    db_session.add(Offer(need_id=uuid.UUID(need['id']),company_id=seller_company,price_rub=1,available_units=5,lead_time_days=1,valid_until=date.today()-timedelta(days=1),commercial_quote={'estimate':{'complete':True,'total_rub':'5'}}))
    await db_session.commit()
    r=await client.post(f"/api/v1/needs/{need['id']}/repeat-preview",headers=_auth(make_token(buyer)))
    assert r.status_code==200,r.text
    assert any('истекло' in warning for warning in r.json()['warnings']), r.json()
    historic = [change for change in r.json()['changes'] if 'итог прошлого КП' in change['field']]
    assert historic[0]['was'] == '5'
    assert historic[0]['now'] == 'новая смета ещё не получена'

async def test_duplicate_image_deletion_preserves_original_blob(client, db_session, stub_object_storage):
    seller=await make_user(db_session)
    company=await make_company(db_session,seller,can_buy=False,can_sell=True)
    headers=_auth(make_token(seller))
    r=await client.post(f'/api/v1/companies/{company}/products',json={'name':'Синтетический крепёж','category':'Строительство','subcategory':'Крепёж','characteristics':{'unit':'шт'},'price_rub':5,'moq_units':10,'lead_time_days':1},headers=headers)
    assert r.status_code==201,r.text
    product_id=uuid.UUID(r.json()['id']); image_id=uuid.uuid4(); file_key='products/synthetic-image'
    stub_object_storage[file_key]=b'synthetic-png-content'
    db_session.add(ProductImage(id=image_id,product_id=product_id,file_name='demo.png',file_key=file_key,content_type='image/png',position=0))
    await db_session.execute(text('UPDATE marketplace.products SET is_published=true WHERE id=:id'),{'id':product_id})
    await db_session.commit()
    original=await client.get(f'/api/v1/product-images/{image_id}')
    assert original.content==b'synthetic-png-content'
    r=await client.post(f'/api/v1/products/{product_id}/duplicate',headers=headers)
    assert r.status_code==201,r.text
    copied_image=r.json()['images'][0]['id']
    deleted=await client.delete(f'/api/v1/product-images/{copied_image}',headers=headers)
    assert deleted.status_code==204,deleted.text
    original=await client.get(f'/api/v1/product-images/{image_id}')
    assert original.status_code==200,original.text
    assert original.content==b'synthetic-png-content', {'status':original.status_code,'body':original.content}

async def test_next_step_does_not_claim_draft_is_published(client,db_session):
    buyer=await make_user(db_session)
    company=await make_company(db_session,buyer,can_buy=True,can_sell=False)
    need=await _make_need(client,buyer,company)
    assert need['status']=='draft'
    r=await client.get('/api/v1/next-step',headers=_auth(make_token(buyer)))
    assert r.status_code==200,r.text
    assert 'Запросы опубликованы' not in r.json()['description'],r.json()

async def test_replayed_support_response_emits_one_user_notification(client,db_session):
    admin=await make_marketplace_admin(db_session)
    user=await make_user(db_session)
    r=await client.post('/api/v1/support/tickets',json={'subject':'Синтетический вопрос','message':'Синтетическое описание проблемы.'},headers=_auth(make_token(user)))
    assert r.status_code==201,r.text
    ticket_id=r.json()['id']
    for _ in range(2):
        r=await client.patch(f'/api/v1/admin/support/tickets/{ticket_id}',json={'status':'resolved','admin_response':'Синтетический ответ.'},headers=_auth(make_token(admin)))
        assert r.status_code==200,r.text
    count=await db_session.scalar(text("SELECT COUNT(*) FROM marketplace.notifications WHERE user_id=:id AND type='support_ticket_updated'"),{'id':user})
    assert count==1, {'notification_count':count}

async def test_concurrent_market_watch_retry_returns_same_subscription(client,db_session,monkeypatch):
    import asyncio
    user=await make_user(db_session)
    await make_company(db_session,user,can_buy=True,can_sell=False)
    replies=await asyncio.gather(*[client.post('/api/v1/market-watches',json={'category':'Мебель'},headers=_auth(make_token(user))) for _ in range(2)],return_exceptions=True)
    outcomes=[type(r).__name__ if isinstance(r,BaseException) else r.status_code for r in replies]
    assert outcomes==[201,201],outcomes
    assert replies[0].json()['id']==replies[1].json()['id']


async def test_support_create_retry_is_single_and_rejects_changed_intent(client, db_session):
    user = await make_user(db_session)
    headers = _auth(make_token(user))
    body = {'subject': 'Синтетический вопрос', 'message': 'Синтетическое описание проблемы.', 'request_key': str(uuid.uuid4())}
    first = await client.post('/api/v1/support/tickets', json=body, headers=headers)
    replay = await client.post('/api/v1/support/tickets', json=body, headers=headers)
    assert first.status_code == replay.status_code == 201
    assert first.json()['id'] == replay.json()['id']
    changed = await client.post('/api/v1/support/tickets', json={**body, 'message': 'Другое синтетическое описание.'}, headers=headers)
    assert changed.status_code == 409
    count = await db_session.scalar(text('SELECT count(*) FROM marketplace.support_tickets'))
    assert count == 1


async def test_next_step_respects_selected_company_mode_and_revocation(client, db_session):
    user = await make_user(db_session)
    buyer = await make_company(db_session, user, can_buy=True, can_sell=False)
    seller = await make_company(db_session, user, can_buy=False, can_sell=True)
    await _make_need(client, user, buyer)
    response = await client.get(f'/api/v1/next-step?company_id={seller}&mode=sell', headers=_auth(make_token(user)))
    assert response.status_code == 200
    assert response.json()['href'] == '/seller/products'
    invalid = await client.get(f'/api/v1/next-step?company_id={seller}&mode=buy', headers=_auth(make_token(user)))
    assert invalid.status_code == 403
    await db_session.execute(text('DELETE FROM auth.company_members WHERE company_id=:cid'), {'cid': seller})
    await db_session.commit()
    revoked = await client.get(f'/api/v1/next-step?company_id={seller}&mode=sell', headers=_auth(make_token(user)))
    assert revoked.status_code == 403


async def test_document_decision_requires_reason_and_retry_preserves_audit(client, db_session):
    from app.models import Document
    seller = await make_user(db_session)
    company = await make_company(db_session, seller, can_buy=False, can_sell=True)
    admin = await make_marketplace_admin(db_session)
    document = Document(company_id=company, name="Синтетический документ", document_type="declaration",
                        file_key="synthetic/document", content_type="application/pdf")
    db_session.add(document)
    await db_session.commit()
    url = f'/api/v3/documents/{document.id}/decision'
    body = {'decision': 'verified', 'scope_category': 'Упаковка и тара'}
    for value in (body, {**body, 'note': '  '}):
        assert (await client.post(url, json=value, headers=_auth(make_token(admin)))).status_code == 422
    body['note'] = 'Проверены синтетические подтверждения'
    for _ in range(2):
        result = await client.post(url, json=body, headers=_auth(make_token(admin)))
        assert result.status_code == 200, result.text
    count = await db_session.scalar(text("SELECT count(*) FROM marketplace.human_approval_records WHERE entity_id=:id AND action='verify_document'"), {'id': document.id})
    assert count == 1
    assert (await client.post(url, json=body, headers=_auth(make_token(seller)))).status_code == 403


async def test_preview_uses_new_supplier_period_and_subtracts_occupied_physical_resource(client, db_session):
    from datetime import datetime, timezone
    from app.models import ResourceReservation
    buyer = await make_user(db_session)
    company = await make_company(db_session, buyer, can_buy=True, can_sell=False)
    need = await _make_need(client, buyer, company)
    seller = await make_user(db_session)
    supplier = await make_company(db_session, seller, can_buy=False, can_sell=True)
    leaf = resolve_category(need['category'], need.get('subcategory'))
    conversion = {'category_id': leaf['id'], 'order_unit': order_unit(need['characteristics']), 'profile_version': leaf['technical_profile']['version'], 'resource_units_per_order_unit': 2}
    entry = CapacityEntry(company_id=supplier, date=date.today()+timedelta(days=40), category='', unit='машино-час', available_units=20, category_conversions=[conversion])
    db_session.add(entry)
    await db_session.flush()
    db_session.add(ResourceReservation(company_id=supplier, anchor_type='offer', anchor_id=uuid.uuid4(), capacity_entry_id=entry.id,
                                       units=4, resource_units=8, resource_conversion=conversion, status='committed'))
    db_session.add(Offer(need_id=uuid.UUID(need['id']), company_id=supplier, price_rub=10, available_units=20, lead_time_days=1, valid_until=date.today()+timedelta(days=10)))
    await db_session.commit()
    url = f"/api/v1/needs/{need['id']}/repeat-preview"
    response = await client.post(url, json={'deadline_date': (date.today()+timedelta(days=45)).isoformat()}, headers=_auth(make_token(buyer)))
    assert response.status_code == 200, response.text
    resources = [change for change in response.json()['changes'] if 'ресурс к новому сроку' in change['field']]
    assert resources[0]['now'] == '6'
    earlier = await client.post(url, json={'deadline_date': (date.today()+timedelta(days=35)).isoformat()}, headers=_auth(make_token(buyer)))
    resources = [change for change in earlier.json()['changes'] if 'ресурс к новому сроку' in change['field']]
    assert resources[0]['now'] == 'не подтверждён'


async def test_repeat_preview_handles_offer_without_expiry(client, db_session):
    buyer = await make_user(db_session)
    company = await make_company(db_session, buyer, can_buy=True, can_sell=False)
    need = await _make_need(client, buyer, company)
    seller = await make_user(db_session)
    supplier = await make_company(db_session, seller, can_buy=False, can_sell=True)
    db_session.add(Offer(need_id=uuid.UUID(need['id']), company_id=supplier, price_rub=10,
                         available_units=5, lead_time_days=1, valid_until=None))
    await db_session.commit()
    response = await client.post(f"/api/v1/needs/{need['id']}/repeat-preview", headers=_auth(make_token(buyer)))
    assert response.status_code == 200, response.text
    assert any('срок прошлого КП не указан' in warning for warning in response.json()['warnings'])
