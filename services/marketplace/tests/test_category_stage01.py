"""Focused API smoke tests for role boundaries, published rules and exact quantities."""
import uuid
import pytest
from sqlalchemy import text
from app.trust import payload_hash
from conftest import make_user,make_company,make_token


@pytest.mark.asyncio
async def test_editor_authority_rules_are_shared_but_historical_product_snapshot_is_frozen(client,db_session):
    editor=await make_user(db_session)
    seller=await make_user(db_session)
    company=await make_company(db_session,seller)
    auth=lambda identifier:{'Authorization':f'Bearer {make_token(identifier)}'}
    denied=await client.get('/api/v1/editor/categories',headers=auth(seller))
    assert denied.status_code==403
    await db_session.execute(text('UPDATE auth.users SET is_category_editor=true WHERE id=:id'),{'id':editor})
    await db_session.commit()
    created=await client.post(f'/api/v1/companies/{company}/products',headers=auth(seller),json={
        'name':'Синтетический стакан','category':'Упаковка и тара','subcategory':'Бумажные стаканы',
        'characteristics':{'material':'бумага','volume_ml':400},'price_rub':10,'moq_units':100,'lead_time_days':1})
    assert created.status_code==201,created.text
    old=created.json(); registry=(await client.get('/api/v1/editor/categories',headers=auth(editor))).json()
    leaf=registry['registry']['groups'][0]['leaves'][0]
    profile=leaf['technical_profile'];profile['passport']['acceptance']['checks'].append('Проверка синтетического образца редактором')
    payload={'category_id':leaf['id'],'expected_registry_hash':registry['registry_hash'],'technical_profile':profile,'reason':'Проверены условия приёмки образца','approved':False}
    preview=await client.post('/api/v1/editor/categories/preview',headers=auth(editor),json=payload)
    assert preview.status_code==200,preview.text
    publish=await client.post('/api/v1/editor/categories/publish',headers=auth(editor),json=payload)
    assert publish.status_code==428
    payload['approved']=True
    publish=await client.post('/api/v1/editor/categories/publish',headers=auth(editor),json=payload)
    assert publish.status_code==200,publish.text
    assert (await client.post('/api/v1/editor/categories/publish',headers=auth(editor),json=payload)).status_code==409
    current=(await client.get('/api/v1/categories/profiles')).json()
    assert current['groups'][0]['leaves'][0]['technical_profile']['version']==old['category_profile']['profile_version']+1
    product=(await client.get(f'/api/v1/companies/{company}/products',headers=auth(seller))).json()[0]
    assert product['category_profile']==old['category_profile']
    diff=(await client.get(f"/api/v1/products/{old['id']}/category-profile",headers=auth(seller))).json()
    assert diff['state']=='update_available'
    adopt={key:diff[key] for key in ('expected_specification_hash','expected_snapshot_hash','expected_current_hash')};adopt['approved']=True
    adopted=await client.post(f"/api/v1/products/{old['id']}/category-profile/adopt",headers=auth(seller),json=adopt)
    assert adopted.status_code==200,adopted.text
    assert adopted.json()['state']=='current'
    actions=(await db_session.execute(text("SELECT action FROM marketplace.human_approval_records ORDER BY created_at"))).scalars().all()
    assert 'category_rules_published' in actions and 'adopt_category_profile' in actions


@pytest.mark.asyncio
async def test_fractional_product_preview_and_persistence_cannot_round(client,db_session):
    seller=await make_user(db_session);company=await make_company(db_session,seller)
    headers={'Authorization':f'Bearer {make_token(seller)}'}
    raw={'name':'Синтетическое сырьё','category':'Сырьё и материалы','subcategory':'Полимеры',
        'characteristics':{'unit':'кг','material':'полипропилен','grade':'СИН-01'},'price_rub':150,'moq_units':'2.5','stock_units':'12.75','lead_time_days':1}
    preview=await client.post('/api/v2/physical-quantities/preview',json={'kind':'product','values':raw})
    assert preview.status_code==200,preview.text
    assert preview.json()['normalized']['moq_units']==2500
    assert (await client.post(f'/api/v2/companies/{company}/products',headers=headers,json=raw)).status_code==422
    response=await client.post(f'/api/v2/companies/{company}/products',headers=headers,json={**raw,'quantity_conversion_approved':True})
    assert response.status_code==201,response.text
    product=response.json()
    assert (product['characteristics']['unit'],product['moq_units'],product['stock_units'],product['price_rub'])==('г',2500,12750,0.15)
    raw['moq_units']='0.0001'
    assert (await client.post(f'/api/v2/companies/{company}/products',headers=headers,json={**raw,'quantity_conversion_approved':True})).status_code==422


@pytest.mark.asyncio
async def test_editor_document_review_does_not_grant_account_or_medical_permissions(client,db_session,stub_object_storage):
    seller=await make_user(db_session);editor=await make_user(db_session);company=await make_company(db_session,seller)
    headers=lambda identifier:{'Authorization':f'Bearer {make_token(identifier)}'}
    uploaded=await client.post(f'/api/v1/companies/{company}/documents',headers=headers(seller),data={'name':'Синтетическое заключение','document_type':'specification_review'},files={'file':('synthetic.txt',b'synthetic fixture','text/plain')})
    assert uploaded.status_code==201,uploaded.text
    document=uploaded.json()
    assert (await client.get(f"/api/v1/editor/documents/{document['id']}/download",headers=headers(seller))).status_code==403
    await db_session.execute(text('UPDATE auth.users SET is_category_editor=true WHERE id=:id'),{'id':editor});await db_session.commit()
    downloaded=await client.get(f"/api/v1/editor/documents/{document['id']}/download",headers=headers(editor))
    assert downloaded.status_code==200 and downloaded.content==b'synthetic fixture'
    review=await client.post(f"/api/v1/documents/{document['id']}/verification",headers=headers(editor),json={'decision':'verified','scope_category':'Строительство','scope_subcategory':'Крепёж','confirms':{'material':['сталь']},'note':'Синтетическая проверка'})
    assert review.status_code==200,review.text
    listed=await client.get('/api/v1/editor/documents?verification_status=verified',headers=headers(editor))
    assert listed.status_code==200 and listed.json()[0]['confirms']=={'material':['сталь']}
    assert (await client.get('/api/v1/admin/support/tickets',headers=headers(editor))).status_code==403


@pytest.mark.asyncio
async def test_shared_capacity_consumes_coefficients_and_partial_release_keeps_units_separate(client,db_session):
    from datetime import date
    from app.resources import reserve,release
    from app.models import ResourceReservation
    from sqlalchemy import select
    seller=await make_user(db_session);company=await make_company(db_session,seller)
    headers={'Authorization':f'Bearer {make_token(seller)}'}
    entries=[{'date':str(date.today()),'unit':'мин','available_units':30,'conversions_approved':True,'category_conversions':[
        {'category_id':'packaging.paper-cups','order_unit':'шт','resource_units_per_order_unit':3},
        {'category_id':'business-supplies.furniture','order_unit':'шт','resource_units_per_order_unit':5}]}]
    response=await client.put(f'/api/v1/companies/{company}/capacity',headers=headers,json={'entries':entries})
    assert response.status_code==200,response.text
    anchor=uuid.uuid4()
    await reserve(db_session,company_id=company,anchor_type='deal',anchor_id=anchor,units=6,deadline=date.today(),category='Упаковка и тара',subcategory='Бумажные стаканы')
    await db_session.commit()
    row=(await db_session.scalars(select(ResourceReservation))).one()
    assert (row.units,row.resource_units,row.resource_conversion['period_date'])==(6,18,str(date.today()))
    await release(db_session,company_id=company,anchor_type='deal',anchor_id=anchor,units=2)
    await db_session.commit()
    assert (row.units,row.resource_units)==(4,12)
    await reserve(db_session,company_id=company,anchor_type='deal',anchor_id=uuid.uuid4(),units=3,deadline=date.today(),category='Товары для бизнеса',subcategory='Мебель')
    await db_session.commit()
    remaining=(await client.get(f'/api/v1/companies/{company}/capacity',headers=headers)).json()[0]
    assert (remaining['reserved_units'],remaining['free_units'])==(27,3)
    entries[0]['available_units']=26
    assert (await client.put(f'/api/v1/companies/{company}/capacity',headers=headers,json={'entries':entries})).status_code==409


@pytest.mark.asyncio
async def test_packaging_confirmation_binds_reviewed_factor_and_preserves_order_unit(client,db_session):
    seller=await make_user(db_session);company=await make_company(db_session,seller)
    headers={'Authorization':f'Bearer {make_token(seller)}'}
    product=await client.post(f'/api/v1/companies/{company}/products',headers=headers,json={
        'name':'Синтетическая упаковка','category':'Упаковка и тара','subcategory':'Бумажные стаканы',
        'characteristics':{'unit':'упак','material':'бумага','volume_ml':400,'pack_units':100},
        'price_rub':1000,'moq_units':2,'lead_time_days':1})
    assert product.status_code==201,product.text
    identifier=product.json()['id'];route=f'/api/v1/products/{identifier}/packaging-conversion'
    raw={'target_unit':'шт','factor':100}
    preview=(await client.post(route,headers=headers,json=raw)).json()
    assert (await client.post(route,headers=headers,json={**raw,'approved':True,'expected_specification_hash':preview['specification_hash']})).status_code==409
    confirmed=await client.post(route,headers=headers,json={**raw,'approved':True,'expected_specification_hash':preview['specification_hash'],'expected_review_hash':preview['review_hash']})
    assert confirmed.status_code==200,confirmed.text
    equivalent=await client.get(f'/api/v1/products/{identifier}/packaging-equivalent?quantity=2',headers=headers)
    assert equivalent.json()['equivalent_quantity']==200
    stored=(await client.get(f'/api/v1/companies/{company}/products',headers=headers)).json()[0]
    assert (stored['characteristics']['unit'],stored['moq_units'],stored['price_rub'])==('упак',2,1000)
