"""Working assortment: real HTTP/DB lifecycle per leaf, no mocked business writes.

Object storage is not involved; separate Docker proof covers files and real solver.
Synthetic verified evidence isolates the category/business route from editor review.
"""
import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
import pytest
from sqlalchemy import select
from app.assortment import ASSORTMENT
from app.category_admission import match_profile
from app.category_registry import resolve_category
from app.models import Document, HumanApprovalRecord, ResourceReservation
from conftest import make_company, make_token, make_user
from test_stage10_complete import ready, shipped, received, inspected, act
from conftest import confirmed_quote_terms, grant_capacity
from test_stage10_complete import full_order, state, PROOF, DAY
from test_s10_fulfillment import order

LEAVES = list({(r[2], r[3]): r for r in reversed(ASSORTMENT)}.values())

def body(response, status=200):
    assert response.status_code == status, response.text
    return response.json()

@pytest.mark.parametrize('row', LEAVES, ids=lambda r: r[0])
async def test_working_leaf_order_report_repeat_and_denials(client, db_session, row):
    seller = await make_user(db_session); buyer = await make_user(db_session)
    sc = await make_company(db_session, seller, can_buy=False)
    bc = await make_company(db_session, buyer, can_sell=False)
    sh = {'Authorization': 'Bearer ' + make_token(seller)}
    bh = {'Authorization': 'Bearer ' + make_token(buyer)}
    spec = {'category': row[2], 'subcategory': row[3], 'characteristics': row[5]}
    profile = match_profile(row[2], row[3], row[5])
    for requirement in profile.requirements:
        db_session.add(Document(company_id=sc, name='Синтетическое доказательство S15',
            document_type=requirement.document_types[0], file_key='synthetic/s15-not-a-download',
            content_type='text/plain', verification_status='verified', scope_category=row[2], scope_subcategory=row[3],
            valid_until=date.today()+timedelta(days=30), verified_by_user_id=seller,
            verified_at=datetime.now(timezone.utc), confirms={k:[str(v)] for k,v in row[5].items()}))
    await db_session.commit()
    await grant_capacity(db_session,sc,20,category_id=resolve_category(row[2],row[3])["id"],unit=row[5]["unit"])
    product = body(await client.post(f'/api/v1/companies/{sc}/products', headers=sh,
        json={**spec, 'name':row[4], 'price_rub':1000, 'moq_units':1, 'stock_units':20, 'lead_time_days':2}),201)
    pid = product['id']
    body(await client.post(f'/api/v1/products/{pid}/publish',headers=sh,json={'published':True}))
    catalog = body(await client.get('/api/v1/products'))
    assert pid in {p['id'] for p in catalog}
    need = body(await client.post('/api/v1/needs',headers=bh,json={**spec,'company_id':str(bc),
        'volume_units':10,'budget_rub':20000,'deadline_date':(date.today()+timedelta(days=20)).isoformat()}),201)
    body(await client.post(f"/api/v1/needs/{need['id']}/publish",headers=bh))
    offer = body(await client.post(f"/api/v1/needs/{need['id']}/offers",headers=sh,json={
        'company_id':str(sc),'product_id':pid,'price_rub':1000,'available_units':10,'lead_time_days':2,
        'delivery_cost_rub':0,'commercial_terms':confirmed_quote_terms()}),201)
    select_url = f"/api/v1/offers/{offer['id']}/select"
    assert (await client.post(select_url,headers=bh,json={'expected_revision':1,'human_approved':False})).status_code==422
    deal = body(await client.post(select_url,headers=bh,json={'expected_revision':1,'human_approved':True}),201)
    assert Decimal(str(deal['total_price_rub']))==Decimal('10000')
    o={'deal':uuid.UUID(deal['id']),'bc':bc,'sc':sc,'bh':bh,'sh':sh}
    stranger=await make_user(db_session)
    denied=await client.get(f"/api/v3/deals/{o['deal']}/fulfillment?company_id={bc}",
        headers={'Authorization':'Bearer '+make_token(stranger)})
    assert denied.status_code in (403,404)
    await ready(client,o); batch=await shipped(client,o,10)
    await received(client,o,batch,10)
    accepted,command=await inspected(client,o,batch,10)
    again,_=await act(client,o,'inspection',{},buyer=True,command=command)
    assert again['revision']==accepted['revision'] and again['totals']==accepted['totals']
    body(await client.put(f"/api/v3/deals/{o['deal']}/costs",headers=sh,json={'company_id':str(sc),
        'expected_revision':0,'unit_cost_rub':'600.00','attributable_expenses_rub':'200.00',
        'tax_basis':'no_vat','note':'Синтетическая калькуляция','human_approved':True}))
    report=body(await client.get(f'/api/v3/companies/{sc}/commercial-analytics?role=seller',headers=sh))
    assert report['totals']['net_goods_revenue_rub']=='10000.00'
    assert report['totals']['gross_profit_rub']=='4000.00'
    repeat={'deadline_date':(date.today()+timedelta(days=25)).isoformat(),'request_key':str(uuid.uuid4())}
    new=body(await client.post(f"/api/v1/needs/{need['id']}/repeat",headers=bh,json=repeat),201)
    retry=body(await client.post(f"/api/v1/needs/{need['id']}/repeat",headers=bh,json=repeat),201)
    assert new['id']==retry['id'] and new['id']!=need['id'] and new['status']=='draft'
    reservations=(await db_session.scalars(select(ResourceReservation).where(ResourceReservation.anchor_id==o['deal']))).all()
    assert len(reservations)==1 and reservations[0].units==10
    approvals=(await db_session.scalars(select(HumanApprovalRecord).where(HumanApprovalRecord.actor_company_id==bc))).all()
    assert approvals


async def test_partial_claim_cannot_be_completed_or_accepted_by_foreign_actor(client, full_order, db_session):
    o = full_order
    await ready(client, o)
    batch = await shipped(client, o, 10)
    await received(client, o, batch, 8, missing=2)
    before = await state(client, o)
    payload = {**PROOF, 'expected_date': DAY, 'batch_id': batch,
               'line_id': before['line_id'], 'accepted': 5, 'rejected': 3}
    stranger = await make_user(db_session)
    foreign = await make_company(db_session, stranger)
    await db_session.commit()
    command = {'company_id': str(foreign), 'expected_revision': before['revision'],
               'terms_version': before['terms_version'], 'human_approved': True,
               'idempotency_key': str(uuid.uuid4()), 'action': 'inspection', 'payload': payload}
    denied = await client.post(f"/api/v3/deals/{o['deal']}/fulfillment",
        headers={'Authorization': 'Bearer ' + make_token(stranger)}, json=command)
    assert denied.status_code in (403, 404)
    after = await state(client, o)
    assert after['revision'] == before['revision'] and after['totals'] == before['totals']
    await act(client, o, 'inspection', payload, status=403)  # Seller cannot accept for buyer.
    accepted, _ = await inspected(client, o, batch, 5, rejected=3)
    assert accepted['status'] == 'disputed' and accepted['totals']['accepted_units'] == 5
    assert accepted['disputes'] and accepted['totals']['shipped_units'] == 10
    await act(client, o, 'complete', {**PROOF, 'expected_date': DAY}, buyer=True, status=409)
    final = await state(client, o)
    assert final['revision'] == accepted['revision'] and final['totals'] == accepted['totals']


async def test_unknown_cost_and_payments_do_not_fabricate_profit(client, db_session):
    from test_stage12 import _deal, _accept, _auth
    c = await _deal(db_session)
    await _accept(db_session, c, 6)
    response = await client.get(f"/api/v3/companies/{c['sc']}/commercial-analytics?role=seller",
                               headers=_auth(make_token(c['seller'])))
    report = body(response)
    row = next(row for row in report['orders'] if row['deal_id'] == str(c['deal'].id))
    assert Decimal(row['net_goods_revenue_rub']) == 6000
    for field in ('cost_of_goods_rub', 'gross_profit_rub', 'contribution_rub'):
        assert row[field] is None and report['totals'][field] is None
        assert report['totals'][field + '_known_orders'] == 0
    assert row['cost_tax_basis'] == 'unknown'
    assert row['payments_rub'] is None and report['payments_rub'] is None
