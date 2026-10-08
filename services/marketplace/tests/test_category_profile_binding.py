"""Versioned profile provenance is server-owned; ordinary edits preserve history."""
from datetime import date, timedelta

from app.category_profile_snapshot import capture_category_profile
from app.models import Product, Need
from conftest import make_company, make_token, make_user


def auth(token): return {'Authorization':f'Bearer {token}'}


async def test_new_records_bind_server_profile_and_ignore_client_override(client,db_session):
    user=await make_user(db_session)
    company=await make_company(db_session,user,can_buy=True,can_sell=True)
    headers=auth(make_token(user))
    spec={'category':'Строительство','subcategory':'Крепёж','characteristics':{'unit':'шт','length_mm':40},'category_profile':{'profile_version':999}}
    response=await client.post(f'/api/v1/companies/{company}/products',headers=headers,json={**spec,'name':'Болт','price_rub':12,'moq_units':1,'lead_time_days':1})
    assert response.status_code==201,response.text
    assert response.json()['category_profile']==capture_category_profile(spec['category'],spec['subcategory'])
    assert response.json()['characteristics']==spec['characteristics']
    response=await client.post('/api/v1/needs',headers=headers,json={**spec,'company_id':str(company),'volume_units':10,'deadline_date':(date.today()+timedelta(days=10)).isoformat()})
    assert response.status_code==201,response.text
    assert response.json()['category_profile']==capture_category_profile(spec['category'],spec['subcategory'])
    assert response.json()['characteristics']==spec['characteristics']


async def test_price_and_budget_edits_preserve_unknown_but_spec_edits_bind_current(client,db_session):
    user=await make_user(db_session)
    company=await make_company(db_session,user,can_buy=True,can_sell=True)
    headers=auth(make_token(user))
    product=Product(company_id=company,name='Болт',category='Строительство',subcategory='Крепёж',characteristics={'unit':'шт','length_mm':40},price_rub=12,moq_units=1,lead_time_days=1)
    need=Need(company_id=company,category='Строительство',subcategory='Крепёж',characteristics={'unit':'шт','length_mm':40},volume_units=10,deadline_date=date.today()+timedelta(days=10),status='draft')
    db_session.add_all([product,need]);await db_session.flush()
    product.category_profile=None;need.category_profile=None
    await db_session.commit()
    response=await client.patch(f'/api/v1/products/{product.id}',headers=headers,json={'price_rub':13})
    assert response.status_code==200,response.text
    assert response.json()['category_profile'] is None
    request={'company_id':str(company),'category':need.category,'subcategory':need.subcategory,'characteristics':need.characteristics,'volume_units':10,'deadline_date':need.deadline_date.isoformat(),'budget_rub':200,'expected_revision':1}
    response=await client.put(f'/api/v1/needs/{need.id}',headers=headers,json=request)
    assert response.status_code==200,response.text
    assert response.json()['category_profile'] is None
    request.update(expected_revision=2,characteristics={'unit':'шт','length_mm':50})
    response=await client.put(f'/api/v1/needs/{need.id}',headers=headers,json=request)
    assert response.status_code==200,response.text
    assert response.json()['category_profile']==capture_category_profile(need.category,need.subcategory)
    response=await client.patch(f'/api/v1/products/{product.id}',headers=headers,json={'characteristics':{'unit':'шт','length_mm':50}})
    assert response.status_code==200,response.text
    assert response.json()['category_profile']==capture_category_profile(product.category,product.subcategory)


async def test_repeat_captures_new_profile_and_retry_keeps_original_snapshot(client,db_session):
    from copy import deepcopy
    from unittest.mock import patch
    import uuid
    user=await make_user(db_session)
    company=await make_company(db_session,user,can_buy=True,can_sell=False)
    headers=auth(make_token(user))
    original=Need(company_id=company,category='Строительство',subcategory='Крепёж',characteristics={'unit':'шт'},volume_units=10,deadline_date=date.today()+timedelta(days=10),status='draft')
    db_session.add(original);await db_session.flush()
    historical=deepcopy(original.category_profile);historical['profile_version']=99
    original.category_profile=historical;await db_session.commit()
    data={'deadline_date':(date.today()+timedelta(days=14)).isoformat(),'request_key':str(uuid.uuid4())}
    response=await client.post(f'/api/v1/needs/{original.id}/repeat',headers=headers,json=data)
    assert response.status_code==201,response.text
    current=response.json()['category_profile']
    assert current==capture_category_profile(original.category,original.subcategory)
    with patch('app.category_profile_snapshot.capture_category_profile',side_effect=AssertionError('Повтор не должен перепривязывать сохранённый запрос')):
        retry=await client.post(f'/api/v1/needs/{original.id}/repeat',headers=headers,json=data)
    assert retry.status_code==201,retry.text
    assert retry.json()['id']==response.json()['id']
    assert retry.json()['category_profile']==current
    await db_session.refresh(original)
    assert original.category_profile==historical
