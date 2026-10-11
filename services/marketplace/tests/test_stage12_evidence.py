"""Regression scenarios for the PR124 review, using synthetic accounting evidence."""
import json
import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
import pytest
from sqlalchemy import select, text
from app.models import Deal, DealCostVersion, DealExecutionEvent, Product, BusinessDenialEvent, OfferDraft
from conftest import make_user, make_company, make_token
from test_stage12 import _deal, _accept, _auth, _agent_run, agents_ledger

async def report(client,c,role='seller',suffix=''):
    return await client.get(f"/api/v3/companies/{c['sc'] if role=='seller' else c['bc']}/commercial-analytics?role={role}{suffix}",headers=_auth(make_token(c['seller'] if role=='seller' else c['buyer'])))

async def returned(db,c,units):
    e=DealExecutionEvent(deal_id=c['deal'].id,actor_company_id=c['bc'],actor_user_id=c['buyer'],idempotency_key=uuid.uuid4(),kind='return',units=units,note='Синтетический акт возврата',status='confirmed',decided_at=datetime.now(timezone.utc))
    db.add(e);await db.commit();return e

async def costs(client,c,revision,value,**kw):
    return await client.put(f"/api/v3/deals/{c['deal'].id}/costs",headers=_auth(make_token(c['seller'])),json={'company_id':str(c['sc']),'expected_revision':revision,'unit_cost_rub':value,'attributable_expenses_rub':'0.00','tax_basis':'no_vat','note':'Синтетическая калькуляция цеха','human_approved':True,**kw})

async def test_net_average_full_return_and_distinct_skus(client,db_session):
    c=await _deal(db_session);await _accept(db_session,c,10);await returned(db_session,c,5)
    r=(await report(client,c)).json();assert r['average_prices'][0]['average_unit_price_rub']=='1000.00';assert r['average_prices'][0]['net_units']==5
    await returned(db_session,c,5);assert (await report(client,c)).json()['average_prices']==[]
    other=await _deal(db_session,buyer=c['buyer'],bc=c['bc'],unit_price='5',characteristics={'material':'металл'})
    await _accept(db_session,other,10)
    assert (await report(client,c,role='buyer')).json()['monthly'][0]['accepted_units'] is None

async def test_unknown_monthly_values_and_legacy_comparability(client,db_session):
    c=await _deal(db_session);await _accept(db_session,c,10)
    d=await _deal(db_session,buyer=c['buyer'],bc=c['bc']);await _accept(db_session,d,10)
    d['deal'].unit_price_rub=None;d['deal'].commercial_snapshot=None;await db_session.commit()
    r=(await report(client,c,'buyer')).json();m=r['monthly'][0]
    assert m['accepted_value_rub'] is None and m['value_known_orders']==1 and m['orders_count']==2
    assert r['totals']['net_goods_revenue_rub'] is None
    assert len(r['average_prices'])==1

async def test_tax_normalization_unknown_and_private_membership(client,db_session):
    c=await _deal(db_session,unit_price='1200');await _accept(db_session,c,10)
    c['deal'].commercial_snapshot={'estimate':{'terms':{'tax_basis':'includes_vat','vat_rate_pct':'20'}}};await db_session.commit()
    assert (await costs(client,c,0,'1000.00')).status_code==200
    r=(await report(client,c)).json()['orders'][0];assert r['gross_profit_rub']=='0.00';assert r['comparable_revenue_rub']=='10000.00'
    assert (await costs(client,c,1,'1000.00',tax_basis='unknown')).status_code==200
    assert (await report(client,c)).json()['orders'][0]['gross_profit_rub'] is None
    uid=await make_user(db_session)
    await db_session.execute(text('INSERT INTO auth.company_members(id,company_id,user_id,can_buy,can_sell,is_admin) VALUES(:id,:cid,:uid,true,false,false)'),{'id':uuid.uuid4(),'cid':c['sc'],'uid':uid});await db_session.commit()
    view=await client.get(f"/api/v3/deals/{c['deal'].id}/execution?company_id={c['sc']}",headers=_auth(make_token(uid)))
    assert view.status_code==200;assert 'cost_note' not in view.json();assert 'cost_history' not in view.json();assert 'gross_profit_rub' not in view.json()['financials']

async def test_cost_versions_and_snapshot_export_do_not_change(client,db_session):
    c=await _deal(db_session);await _accept(db_session,c,10)
    assert (await costs(client,c,0,'600.00')).status_code==200
    before=(await report(client,c)).json()
    assert (await costs(client,c,1,'800.00')).status_code==200
    await returned(db_session,c,5)
    after=(await report(client,c)).json();assert after['totals']['net_goods_revenue_rub']=='5000.00'
    revisions=(await db_session.scalars(select(DealCostVersion).where(DealCostVersion.deal_id==c['deal'].id).order_by(DealCostVersion.revision))).all()
    assert [v.unit_cost_rub for v in revisions]==[Decimal('600'),Decimal('800')]
    url=f"/api/v3/companies/{c['sc']}/commercial-report.csv?role=seller&report_id={before['report_id']}"
    csv=await client.get(url,headers=_auth(make_token(c['seller'])));assert csv.status_code==200
    assert before['built_at'] in csv.text and '10000.00' in csv.text and '600.00' in csv.text
    mismatch=await client.get(url+'&status=fulfilled',headers=_auth(make_token(c['seller'])));assert mismatch.status_code==409
    user=await make_user(db_session);other=await make_company(db_session,user)
    assert (await client.get(url.replace(str(c['sc']),str(other)),headers=_auth(make_token(user)))).status_code==404

async def test_period_adjustment_links_and_historical_marker(client,db_session):
    c=await _deal(db_session,created_days_ago=40);await _accept(db_session,c,10)
    e=await returned(db_session,c,5)
    today=str(datetime.now(timezone.utc).date())
    r=(await report(client,c,suffix=f'&start={today}&end={today}')).json()
    assert r['orders_count']==0
    adjustment=next(x for x in r['period_events'] if x['event_id']==str(e.id));assert adjustment['source_acceptances'][0]['units']==5
    old=(await report(client,c,suffix=f'&end={date.today()-timedelta(days=30)}')).json();assert old['historical_recalculated'] is True

async def test_frozen_product_filter_and_expired_offer(client,db_session):
    c=await _deal(db_session)
    c['deal'].commercial_snapshot={**c['deal'].commercial_snapshot,'product':{'name':'Старый стол','characteristics':{'material':'дерево'}}}
    p=Product(company_id=c['sc'],name='Новый стол',category='Мебель',characteristics={},price_rub=100,price_tiers=[],moq_units=1,lead_time_days=1)
    db_session.add(p);await db_session.flush();c['offer'].product_id=p.id;c['offer'].status='sent';c['offer'].valid_until=date.today()-timedelta(days=1);await db_session.commit()
    assert (await report(client,c,suffix='&product=старый')).json()['orders_count']==1
    assert (await report(client,c,suffix='&product=новый')).json()['orders_count']==0
    r=(await report(client,c)).json()['rejection_rate'];assert r['open']==0 and r['stale']==1

async def initial(db,rid,result,corrections=0):
    await db.execute(text('UPDATE agents.agent_runs SET initial_result=CAST(:result AS jsonb),human_corrections=:corrections WHERE id=:id'),{'id':rid,'result':json.dumps(result),'corrections':corrections});await db.commit()

async def evaluate(client,c,rid,**kw):
    return await client.post(f'/api/v3/companies/{c}/quality-evidence',headers=kw.pop('headers'),json={'run_id':str(rid),'task_scope':'Закупка бумажных стаканов','source':'Синтетическое задание, экспертная сверка','critical_fields':{'quantity_units':5000},'expected_category':'бумажные стаканы','human_approved':True,**kw})

async def test_expert_correctness_immutable_result_min_sample_and_denied_access(client,db_session,agents_ledger):
    user=await make_user(db_session);company=await make_company(db_session,user);headers=_auth(make_token(user))
    wrong={'category':'бумажные стаканы','properties':[{'key':'quantity_units','value':999999,'status':'confirmed'}],'conflicts':[{'key':'material'}]}
    ids=[]
    for _ in range(5):
        rid=await _agent_run(db_session,agents_ledger,user,company,'buyer_agent',wrong);ids.append(rid);await initial(db_session,rid,wrong,1)
        e=await evaluate(client,company,rid,headers=headers);assert e.status_code==201,e.text;assert e.json()['assessment']['correct']==1
        assert (await evaluate(client,company,rid,headers=headers)).json()['id']==e.json()['id']
    await db_session.execute(text("UPDATE agents.agent_runs SET result='{}'::jsonb WHERE id=ANY(:ids)"),{'ids':ids});await db_session.commit()
    r=(await client.get(f'/api/v3/companies/{company}/role-quality',headers=headers)).json()['roles'][0]
    assert r['status']=='evaluated' and r['critical_correctness_pct']==50.0 and r['critical_completeness_pct']==100
    assert r['conflicts_found']==5 and r['human_corrections']==5 and r['expert_verified_runs']==5
    other=await make_user(db_session)
    assert (await evaluate(client,company,ids[0],headers=_auth(make_token(other)))).status_code==404

async def test_open_states_do_not_become_success_or_evaluated(client,db_session,agents_ledger):
    u=await make_user(db_session);c=await make_company(db_session,u);h=_auth(make_token(u))
    for state in ['received','processing','needs_clarification','ready_for_review','failed']:
        await _agent_run(db_session,agents_ledger,u,c,'buyer_agent',{},state=state,duration_ms=None,estimated_cost_rub=None)
    body=(await client.get(f'/api/v3/companies/{c}/role-quality',headers=h)).json()['roles'][0]
    assert body['status']=='not_evaluated' and body['completed_runs']==0 and body['open_runs']==4
    assert body['average_duration_ms'] is None and body['known_cost_rub'] is None
    score=(await client.get(f'/api/v3/companies/{c}/agent-scorecard',headers=h)).json()
    assert score['agent_average_duration_ms'] is None and score['agent_estimated_cost_rub'] is None

async def test_bank_is_bundled_wrong_numeric_not_correct_and_requires_applicability(client,db_session,agents_ledger):
    from app.agent_quality import bank_tasks
    from pathlib import Path
    assert json.loads(Path('/workspace/packages/test-fixtures/agent-task-bank/ru_tasks.json').read_text())['tasks']==bank_tasks()
    u=await make_user(db_session);c=await make_company(db_session,u);h=_auth(make_token(u))
    result={'category':'бумажные стаканы','properties':[{'key':'quantity_units','value':999999,'status':'confirmed'}],'conflicts':[],'questions':[]}
    rid=await _agent_run(db_session,agents_ledger,u,c,'buyer_agent',result);await initial(db_session,rid,result)
    assert (await evaluate(client,c,rid,headers=h,bank_task_id='bank-001')).status_code==422
    r=await evaluate(client,c,rid,headers=h,bank_task_id='bank-001',bank_applicability_confirmed=True)
    assert r.status_code==201,r.text
    assert next(x for x in r.json()['assessment']['checks'] if x['key']=='quantity_units')['correct'] is False

async def test_code_draft_corrections_not_attributed_to_model(client,db_session,agents_ledger):
    c=await _deal(db_session);u=c['seller'];company=c['sc'];h=_auth(make_token(u))
    rid=await _agent_run(db_session,agents_ledger,u,company,'seller_agent',{'eligible':True},state='completed');await initial(db_session,rid,{'eligible':True})
    db_session.add(OfferDraft(need_id=c['need'].id,company_id=company,status='used',used_offer_id=c['offer'].id,changed_fields=['price_rub','delivery_cost_rub']))
    await db_session.commit()
    r=(await client.get(f'/api/v3/companies/{company}/role-quality',headers=h)).json()['roles'][0];assert r['human_corrections']==0 and r['blocked_actions']==0

async def test_draft_cohort_excludes_stale_and_incomplete_and_preserves_origin_outcomes(client,db_session):
    c=await _deal(db_session,created_days_ago=40)
    db_session.add_all([OfferDraft(need_id=c['need'].id,company_id=c['sc'],status='stale'),OfferDraft(need_id=c['need'].id,company_id=c['sc'],missing=['Цена неизвестна']),OfferDraft(need_id=c['need'].id,company_id=c['sc'],status='used',used_offer_id=c['offer'].id)])
    await db_session.commit()
    r=(await client.get(f"/api/v3/companies/{c['sc']}/agent-scorecard",headers=_auth(make_token(c['seller'])))).json()
    assert r['offer_drafts_total']==1 and r['offer_drafts_excluded']==2 and r['deals_from_drafts']==1

async def test_business_denial_survives_rollback_and_is_not_model_event(client,db_session):
    from test_offer_draft_and_scorecard import _seller_company
    user,company,token=await _seller_company(db_session)
    p=await client.post(f'/api/v3/companies/{company}/products',headers=_auth(token),json={'name':'Синтетический стакан','category':'Упаковка и тара','subcategory':'Бумажные стаканы','characteristics':{'volume_ml':400,'coating':'PE','material':'крафт-картон'},'price_rub':'12','moq_units':5000,'lead_time_days':10})
    assert p.status_code==201,p.text
    url=f"/api/v3/products/{p.json()['id']}/publish"
    for _ in range(2):
        r=await client.post(url,headers=_auth(token),json={'published':True});assert r.status_code==409,r.text
    entries=(await db_session.scalars(select(BusinessDenialEvent).where(BusinessDenialEvent.company_id==company))).all()
    assert len(entries)==1 and entries[0].role=='supplier_admission'
    score=(await client.get(f'/api/v3/companies/{company}/agent-scorecard',headers=_auth(token))).json();assert score['admission_blocked']==1

async def test_group_filters_apply_to_status_product_and_counterparty(client,db_session):
    from app.models import CompatibilityProfile,Coalition,GroupOffer,ParticipantOrder
    c=await _deal(db_session)
    profile=CompatibilityProfile(category='Мебель',input_hash=uuid.uuid4().hex);db_session.add(profile);await db_session.flush()
    coalition=Coalition(compatibility_profile_id=profile.id,producer_company_id=c['sc'],category='Мебель',combined_volume_units=10);db_session.add(coalition);await db_session.flush()
    offer=GroupOffer(coalition_id=coalition.id,company_id=c['sc']);db_session.add(offer);await db_session.flush()
    db_session.add(ParticipantOrder(coalition_id=coalition.id,group_offer_id=offer.id,need_id=c['need'].id,buyer_company_id=c['bc'],seller_company_id=c['sc'],units=10,total_price_rub=10000,status='created',commercial_snapshot=c['deal'].commercial_snapshot));await db_session.commit()
    assert (await report(client,c,suffix='&source=group')).json()['group_orders_count']==1
    for suffix in ['&status=fulfilled','&counterparty=Несуществующая компания','&product=Несуществующий товар']:
        assert (await report(client,c,suffix='&source=group'+suffix)).json()['group_orders_count']==0
    assert (await report(client,c,suffix='&source=group&product=Тестовый')).json()['group_orders_count']==1

async def test_reliability_comes_from_actual_outcomes_and_deadlines(client,db_session):
    c=await _deal(db_session);await _accept(db_session,c,10)
    assert (await report(client,c,'buyer')).json()['reliability']['status']=='not_evaluated'
    for _ in range(4):
        d=await _deal(db_session,buyer=c['buyer'],bc=c['bc']);await _accept(db_session,d,10)
    r=(await report(client,c,'buyer')).json()['reliability'];assert r['status']=='evaluated' and r['on_time_share_pct']==100
    await returned(db_session,c,1)
    r=(await report(client,c,'buyer')).json()['reliability'];assert r['on_time_share_pct']==80 and r['outcomes']['returned']==1

async def test_expert_cohorts_do_not_mix_models_routes_or_unfinished_runs(client,db_session,agents_ledger):
    u=await make_user(db_session);c=await make_company(db_session,u);h=_auth(make_token(u));result={'category':'бумажные стаканы','properties':[{'key':'quantity_units','value':5000}]}
    for model,state,route in [('A','confirmed_by_user','local'),('B','confirmed_by_user','local'),('A','ready_for_review','local'),('A','confirmed_by_user','rules_only'),('A','confirmed_by_user','external')]:
        rid=await _agent_run(db_session,agents_ledger,u,c,'buyer_agent',result,model_version=model,state=state,used_route=route);await initial(db_session,rid,result)
        assert (await evaluate(client,c,rid,headers=h)).status_code==201
    r=(await client.get(f'/api/v3/companies/{c}/role-quality',headers=h)).json();assert len(r['roles'])==4
    assert all(row['status']=='not_evaluated' for row in r['roles'])

async def test_fractional_inference_cost_and_zero_have_explicit_coverage(client,db_session,agents_ledger):
    u=await make_user(db_session);c=await make_company(db_session,u);h=_auth(make_token(u))
    await _agent_run(db_session,agents_ledger,u,c,'buyer_agent',{},estimated_cost_rub='0.0001',duration_ms=0)
    score=(await client.get(f'/api/v3/companies/{c}/agent-scorecard',headers=h)).json();assert Decimal(score['agent_estimated_cost_rub'])==Decimal('0.0001');assert score['agent_average_duration_ms']==0
    role=(await client.get(f'/api/v3/companies/{c}/role-quality',headers=h)).json()['roles'][0];assert Decimal(role['known_cost_rub'])==Decimal('0.0001')


async def test_malformed_initial_result_and_legacy_run_cannot_be_expert_verified(client,db_session,agents_ledger):
    u=await make_user(db_session);c=await make_company(db_session,u);h=_auth(make_token(u))
    rid=await _agent_run(db_session,agents_ledger,u,c,'buyer_agent',{})
    assert (await evaluate(client,c,rid,headers=h)).status_code==409
    await initial(db_session,rid,['wrong'])
    assert (await evaluate(client,c,rid,headers=h)).status_code==409
    r=await client.get(f'/api/v3/companies/{c}/role-quality',headers=h);assert r.status_code==200
    assert r.json()['roles'][0]['expert_verified_runs']==0

async def test_snapshot_integrity_and_export_permission_revocation(client,db_session):
    from app.models import CommercialReportSnapshot
    c=await _deal(db_session);r=(await report(client,c)).json()
    url=f"/api/v3/companies/{c['sc']}/commercial-report.csv?role=seller&report_id={r['report_id']}";h=_auth(make_token(c['seller']))
    snapshot=await db_session.get(CommercialReportSnapshot,uuid.UUID(r['report_id']))
    snapshot.payload={**snapshot.payload,'orders_count':999};await db_session.commit()
    assert (await client.get(url,headers=h)).status_code==409
    r=(await report(client,c)).json();url=url.split('&report_id=')[0]+'&report_id='+r['report_id']
    await db_session.execute(text('UPDATE auth.company_members SET can_sell=false WHERE company_id=:cid'),{'cid':c['sc']});await db_session.commit()
    assert (await client.get(url,headers=h)).status_code==403
