from decimal import Decimal
from datetime import date, timedelta
from copy import deepcopy
import pytest
from conftest import make_user,make_company,make_token,grant_packaging_documents,confirmed_quote_terms


@pytest.mark.asyncio
async def test_referenced_delivery_destination_cannot_change_without_need_revision(client, db_session):
    from app.models import Need
    user = await make_user(db_session)
    company = await make_company(db_session, user, can_buy=True, can_sell=False)
    headers = {'Authorization': f'Bearer {make_token(user)}'}
    base = f'/api/v3/companies/{company}/addresses'
    created = await client.post(base, headers=headers, json={
        'address': 'Синтетическая улица, 1', 'city': 'Москва', 'region': 'Москва'})
    assert created.status_code == 201, created.text
    address_id = created.json()['id']
    url = f'{base}/{address_id}'
    editable = await client.patch(url, headers=headers, json={'address': 'Синтетическая улица, 2'})
    assert editable.status_code == 200
    need = Need(company_id=company, created_by_user_id=user, category='Строительство',
                characteristics={'unit': 'шт'}, volume_units=100, deadline_date=date.today()+timedelta(days=10),
                delivery_address_id=address_id, status='draft')
    db_session.add(need)
    await db_session.commit()
    for field, value in [('address', 'Синтетическая улица, 3'), ('city', 'Тула'), ('region', 'Тульская область')]:
        response = await client.patch(url, headers=headers, json={field: value})
        assert response.status_code == 409, response.text
    assert (await client.delete(url, headers=headers)).status_code == 409
    unchanged = await client.patch(url, headers=headers, json={'address': 'Синтетическая улица, 2', 'is_default': True})
    assert unchanged.status_code == 200
    assert unchanged.json()['address'] == 'Синтетическая улица, 2'
    assert unchanged.json()['is_default'] is True
    assert (await client.patch(url, headers=headers, json={'city': None})).status_code == 422


@pytest.mark.asyncio
async def test_v3_exact_large_batch_complete_consent_and_immutable_snapshot(client,db_session):
    buyer_user=await make_user(db_session);buyer=await make_company(db_session,buyer_user,can_buy=True,can_sell=False)
    seller_user=await make_user(db_session);seller=await make_company(db_session,seller_user,can_buy=False,can_sell=True)
    headers=lambda user:{'Authorization':f'Bearer {make_token(user)}'}
    chars={'unit':'шт','material':'бумага','volume_ml':400}
    await grant_packaging_documents(db_session,seller,decision_user_id=seller_user,confirms={'material':['бумага'],'volume_ml':[400]})
    raw={'name':'Синтетический товар','category':'Упаковка и тара','subcategory':'Бумажные стаканы','characteristics':chars,
         'price_rub':'0.00000000125','moq_units':1,'stock_units':1_000_000_000,'lead_time_days':1}
    created=await client.post(f'/api/v3/companies/{seller}/products',headers=headers(seller_user),json=raw)
    assert created.status_code==201,created.text
    product=created.json()
    assert isinstance(product['price_rub'],str) and Decimal(product['price_rub'])==Decimal(raw['price_rub'])
    assert (await client.post(f"/api/v3/products/{product['id']}/publish",headers=headers(seller_user),json={'published':True})).status_code==200
    legacy=(await client.get(f'/api/v1/companies/{seller}/products',headers=headers(seller_user))).json()[0]
    assert isinstance(legacy['price_rub'],float)
    response=await client.post('/api/v3/needs',headers=headers(buyer_user),json={
        'company_id':str(buyer),'category':raw['category'],'subcategory':raw['subcategory'],'characteristics':chars,
        'volume_units':1_000_000_000,'budget_rub':'1.25','deadline_date':str(date.today()+timedelta(days=30))})
    assert response.status_code==201,response.text
    need=response.json()
    assert (await client.post(f"/api/v3/needs/{need['id']}/publish",headers=headers(buyer_user))).status_code==200
    payload={'company_id':str(seller),'resource_kind':'stock','product_id':product['id'],'price_rub':raw['price_rub'],
             'available_units':1_000_000_000,'lead_time_days':1,'moq_units':1,'delivery_cost_rub':None}
    response=await client.post(f"/api/v3/needs/{need['id']}/offers",headers=headers(seller_user),json=payload)
    assert response.status_code==201,response.text
    quote=response.json()
    assert quote['delivery_cost_rub'] is None and not quote['commercial_quote']['estimate']['complete']
    selected=await client.post(f"/api/v3/offers/{quote['id']}/select",headers=headers(buyer_user),json={'human_approved':True,'expected_revision':1})
    assert selected.status_code==409 and 'согласование' in selected.json()['detail']
    complete=await client.patch(f"/api/v3/offers/{quote['id']}",headers=headers(seller_user),json={
        'expected_revision':1,'commercial_terms':{**confirmed_quote_terms(),'delivery_method':'included'}})
    assert complete.status_code==200,complete.text
    assert complete.json()['commercial_quote']['estimate']['total_rub']=='1.25'
    selected=await client.post(f"/api/v3/offers/{quote['id']}/select",headers=headers(buyer_user),json={'human_approved':True,'expected_revision':2})
    assert selected.status_code==201,selected.text
    deal=selected.json();snapshot=deepcopy(deal['commercial_snapshot'])
    assert Decimal(deal['total_price_rub'])==Decimal('1.25')
    assert Decimal(snapshot['product']['price_rub'])==Decimal(raw['price_rub'])
    changed=await client.patch(f"/api/v3/products/{product['id']}",headers=headers(seller_user),json={'price_rub':'0.00000000250'})
    assert changed.status_code==200,changed.text
    deals=(await client.get('/api/v3/deals/mine',headers=headers(buyer_user))).json()
    assert deals[0]['commercial_snapshot']==snapshot and Decimal(deals[0]['total_price_rub'])==Decimal('1.25')
    repeated=await client.post(f"/api/v3/offers/{quote['id']}/select",headers=headers(buyer_user),json={'human_approved':True,'expected_revision':2})
    assert repeated.status_code==201 and repeated.json()['id']==deal['id']


@pytest.mark.asyncio
async def test_buyer_selects_own_confirmed_baseline_negative_effect_and_private_snapshot(client,db_session):
    from app.models import Need,Offer,CompatibilityProfile,Coalition,CoalitionMember
    from app.commercial import estimate,offer_quote
    buyer_user=await make_user(db_session);buyer=await make_company(db_session,buyer_user,can_buy=True,can_sell=False)
    foreign_user=await make_user(db_session);await make_company(db_session,foreign_user,can_buy=True,can_sell=False)
    seller_user=await make_user(db_session);seller=await make_company(db_session,seller_user,can_buy=False,can_sell=True)
    need=Need(company_id=buyer,created_by_user_id=buyer_user,category='Строительство',subcategory='Крепёж',characteristics={'unit':'шт'},
              volume_units=100,budget_rub=2000,deadline_date=date.today()+timedelta(days=10),status='awaiting_approvals')
    profile=CompatibilityProfile(category='Строительство',input_hash='synthetic-baseline-comparison')
    db_session.add_all([need,profile]);await db_session.flush()
    offer=Offer(need_id=need.id,company_id=seller,created_by_user_id=seller_user,price_rub=7,available_units=100,
                moq_units=1,lead_time_days=1,delivery_cost_rub=0,commercial_terms=confirmed_quote_terms())
    coalition=Coalition(compatibility_profile_id=profile.id,producer_company_id=seller,category=need.category,
                        combined_volume_units=100,status='awaiting_approvals')
    db_session.add_all([offer,coalition]);await db_session.flush()
    offer.commercial_quote=await offer_quote(db_session,offer,need)
    member=CoalitionMember(coalition_id=coalition.id,need_id=need.id,buyer_company_id=buyer,units=100,total_cost_rub=1200,
        commercial_estimate=estimate(units=100,unit_price=7,delivery=500,terms=confirmed_quote_terms(),buyer=buyer,seller=seller,
                                     source={'type':'group_offer','id':'synthetic-group','revision':1}))
    db_session.add(member);await db_session.commit()
    headers=lambda user:{'Authorization':f'Bearer {make_token(user)}'}
    payload={'company_id':str(buyer),'offer_id':str(offer.id),'expected_revision':1}
    denied=await client.post(f'/api/v3/coalitions/{coalition.id}/baseline',headers=headers(foreign_user),json=payload)
    assert denied.status_code in (403,404)
    selected=await client.post(f'/api/v3/coalitions/{coalition.id}/baseline',headers=headers(buyer_user),json=payload)
    assert selected.status_code==200,selected.text
    own=selected.json()['members'][0]
    assert Decimal(own['benefit_rub'])==Decimal('-500')
    assert own['commercial_estimate']['baseline_snapshot']['offer']['revision']==1
    seller_view=(await client.get('/api/v3/coalitions/mine',headers=headers(seller_user))).json()[0]['members'][0]
    assert seller_view['baseline_cost_rub'] is None and seller_view['benefit_rub'] is None
    assert seller_view['commercial_estimate']['baseline_snapshot'] is None

    cleared=await client.post(f'/api/v3/coalitions/{coalition.id}/baseline',headers=headers(buyer_user),
                              json={**payload,'offer_id':None})
    assert cleared.status_code==200,cleared.text
    assert cleared.json()['members'][0]['benefit_rub'] is None
    assert cleared.json()['members'][0]['commercial_estimate']['baseline_snapshot'] is None
