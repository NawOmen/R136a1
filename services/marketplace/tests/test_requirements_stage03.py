"""S03 acceptance: one revision, stale dependencies, privacy, immutable obligations."""
import uuid
from datetime import date, timedelta

import pytest
from sqlalchemy import select, text

from app.models import (Need, Offer, NeedRevision, Notification, OptimizationVariantRecord,
    ResiliencePlan, ReserveCommitment, ResourceReservation, Deal, CapacityEntry)
from conftest import make_user, make_company, make_token


@pytest.fixture
async def spec(client, db_session):
    uid = await make_user(db_session)
    cid = await make_company(db_session, uid, can_buy=True, can_sell=False)
    seller = await make_user(db_session)
    scid = await make_company(db_session, seller, can_buy=False, can_sell=True)
    headers = {"Authorization": f"Bearer {make_token(uid)}"}
    payload = {"company_id": str(cid), "category": "Мебель", "characteristics": {"material": "дерево", "unit": "шт"},
        "volume_units": 10, "budget_rub": "20000.00", "deadline_date": str(date.today()+timedelta(days=30))}
    response = await client.post('/api/v3/needs', headers=headers, json=payload)
    assert response.status_code == 201, response.text
    nid = uuid.UUID(response.json()['id'])
    need = await db_session.get(Need, nid)
    need.status = 'open_for_offers'
    offer = Offer(need_id=nid, company_id=scid, created_by_user_id=seller, price_rub=1000,
        available_units=100, lead_time_days=2, delivery_cost_rub=0, moq_units=1, price_tiers=[], status='sent')
    db_session.add(offer); await db_session.flush()
    variant = OptimizationVariantRecord(need_id=nid, kind='reliable', input_hash='synthetic-stage03',
        result={'feasible': True, 'allocations': [], 'total_cost_rub': '10000'})
    db_session.add(variant); await db_session.flush()
    plan = ResiliencePlan(need_id=nid, buyer_company_id=cid, baseline_variant_id=variant.id,
        baseline_allocations=[], baseline_total_cost_rub=10000, baseline_lead_time_days=2,
        current_allocations=[], current_total_cost_rub=10000, current_lead_time_days=2)
    db_session.add(plan); await db_session.flush()
    reserve = ReserveCommitment(plan_id=plan.id, company_id=scid, reserve_tier='warm', confirmation_status='approved')
    db_session.add(reserve); await db_session.flush()
    capacity = CapacityEntry(company_id=scid, date=date.today(), available_units=100)
    db_session.add(capacity); await db_session.flush()
    held = ResourceReservation(capacity_entry_id=capacity.id, company_id=scid, anchor_type='reserve', anchor_id=reserve.id,
        units=10, status='held')
    db_session.add(held); await db_session.commit()
    return nid, uid, cid, scid, headers, payload, offer, plan, variant, reserve, held


async def preview(client, spec, **changes):
    nid, _, _, _, headers, payload, *_ = spec
    body = {**payload, 'expected_revision': 1, **changes}
    response = await client.post(f'/api/v3/needs/{nid}/edit-preview', headers=headers, json=body)
    assert response.status_code == 200, response.text
    return body, response.json()


async def test_published_revision_preview_invalidation_and_history(client, db_session, spec):
    nid, uid, _, _, headers, _, offer, plan, variant, reserve, held = spec
    body, impact = await preview(client, spec, volume_units=20)
    assert impact['requires_confirmation'] and str(offer.id) in impact['affected']['offers']
    assert (await db_session.get(Offer, offer.id)).status == 'sent'
    assert (await client.put(f'/api/v3/needs/{nid}', headers=headers, json=body)).status_code == 409
    response = await client.put(f'/api/v3/needs/{nid}', headers=headers, json={**body, 'impact_hash': impact['impact_hash']})
    assert response.status_code == 200, response.text
    assert response.json()['revision'] == 2
    for row in (offer, plan, variant, reserve, held): await db_session.refresh(row)
    assert offer.status == 'stale' and plan.status == 'stale' and held.status == 'released'
    assert variant.result['stale'] and reserve.confirmation_status == 'expired'
    assert (await client.post(f'/api/v1/offers/{offer.id}/select', headers=headers,
        json={'expected_revision': 1, 'human_approved': True})).status_code == 409
    history = (await client.get(f'/api/v3/needs/{nid}/revisions', headers=headers)).json()
    assert [row['revision'] for row in history] == [2, 1]
    assert history[1]['snapshot']['volume_units'] == 10
    assert history[0]['snapshot']['requirements_evidence']['fields']['quantity_units']['confirmed_by_user_id'] == str(uid)
    assert list((await db_session.scalars(select(Notification).where(Notification.user_id == uid))).all())
    assert (await client.put(f'/api/v3/needs/{nid}', headers=headers, json={**body, 'impact_hash': impact['impact_hash']})).status_code == 409
    # Stale plans remain readable, but cannot be acted on or block a new generation.
    assert (await client.post(f'/api/v1/resilience-plans/{plan.id}/simulate-failure', headers=headers,
        json={'failed_company_ids': []})).status_code in {409, 422}
    new_plan = ResiliencePlan(need_id=nid, buyer_company_id=plan.buyer_company_id, baseline_variant_id=variant.id,
        baseline_allocations=[], baseline_total_cost_rub=10000, baseline_lead_time_days=2,
        current_allocations=[], current_total_cost_rub=10000, current_lead_time_days=2)
    db_session.add(new_plan); await db_session.commit()
    assert new_plan.id != plan.id


async def test_label_preserves_revision_and_prior_consents(client, db_session, spec):
    nid, _, _, _, headers, _, offer, plan, *_ = spec
    body, impact = await preview(client, spec, visibility='closed')
    assert not impact['changes'] and not impact['requires_confirmation']
    response = await client.put(f'/api/v3/needs/{nid}', headers=headers, json=body)
    assert response.status_code == 200, response.text
    assert response.json()['revision'] == 1
    await db_session.refresh(offer); await db_session.refresh(plan)
    assert offer.status == 'sent' and plan.status == 'preparing_reserves'


async def test_preview_expires_when_offer_revision_changes(client, db_session, spec):
    nid, _, _, _, headers, _, offer, *_ = spec
    body, impact = await preview(client, spec, volume_units=20)
    offer.revision += 1; await db_session.commit()
    response = await client.put(f'/api/v3/needs/{nid}', headers=headers, json={**body, 'impact_hash': impact['impact_hash']})
    assert response.status_code == 409
    assert (await db_session.get(Need, nid)).revision == 1


async def test_existing_obligation_is_never_rewritten(client, db_session, spec):
    nid, _, cid, scid, headers, _, offer, *_ = spec
    deal = Deal(need_id=nid, offer_id=offer.id, buyer_company_id=cid, seller_company_id=scid,
        units=10, unit_price_rub=1000, total_price_rub=10000, commercial_snapshot={'version': 'immutable'})
    db_session.add(deal); await db_session.commit()
    body, impact = await preview(client, spec, volume_units=20)
    assert not impact['editable']
    assert (await client.put(f'/api/v3/needs/{nid}', headers=headers, json={**body, 'impact_hash': impact['impact_hash']})).status_code == 409
    await db_session.refresh(deal)
    assert deal.commercial_snapshot == {'version': 'immutable'}


@pytest.fixture
async def gateway_contract(db_session):
    existed = await db_session.scalar(text("SELECT to_regclass('agents.agent_runs') IS NOT NULL"))
    await db_session.execute(text('CREATE SCHEMA IF NOT EXISTS agents'))
    await db_session.execute(text('CREATE TABLE IF NOT EXISTS agents.agent_runs (id UUID PRIMARY KEY, revision INTEGER NOT NULL, state TEXT NOT NULL, result JSONB NOT NULL, user_id UUID NOT NULL, company_id UUID)'))
    await db_session.commit()
    yield
    if not existed:
        await db_session.execute(text('DROP TABLE agents.agent_runs'))
        await db_session.commit()


async def test_confirmed_gateway_binding_and_source_staleness(client, db_session, spec, gateway_contract):
    nid, uid, cid, scid, headers, payload, *_ = spec
    # Minimal cross-service contract, independent of a live model.
    await db_session.execute(text('CREATE SCHEMA IF NOT EXISTS agents'))
    await db_session.execute(text('CREATE TABLE IF NOT EXISTS agents.agent_runs (id UUID PRIMARY KEY, revision INTEGER NOT NULL, state TEXT NOT NULL, result JSONB NOT NULL, user_id UUID NOT NULL, company_id UUID)'))
    run = uuid.uuid4()
    has_type = await db_session.scalar(text("SELECT EXISTS(SELECT 1 FROM information_schema.columns WHERE table_schema='agents' AND table_name='agent_runs' AND column_name='agent_type')"))
    columns = ",agent_type,requested_route,input_summary" if has_type else ""
    values = ",'buyer_investigator','local',''" if has_type else ""
    await db_session.execute(text(f"INSERT INTO agents.agent_runs (id,revision,state,result,user_id,company_id{columns}) VALUES (:id, 2, 'confirmed_by_user', CAST(:result AS JSONB), :uid, :cid{values})"),
        {'id': run, 'uid': uid, 'cid': cid, 'result': '{"can_confirm":true,"properties":[],"conflicts":[],"questions":[]}'})
    await db_session.commit()
    body, impact = await preview(client, spec, agent_run_id=str(run), agent_run_revision=2)
    assert 'evidence' in impact['changes']
    result = await client.put(f'/api/v3/needs/{nid}', headers=headers, json={**body, 'impact_hash': impact['impact_hash']})
    assert result.status_code == 200, result.text
    await db_session.execute(text("UPDATE agents.agent_runs SET revision=3, state='needs_clarification' WHERE id=:id"), {'id':run})
    await db_session.commit()
    out = await client.get(f'/api/v3/needs/{nid}', headers=headers)
    assert out.json()['requirements_evidence']['stale']
    assert (await client.post(f'/api/v3/needs/{nid}/publish', headers=headers)).status_code == 409
    seller = await db_session.scalar(text('SELECT user_id FROM auth.company_members WHERE company_id=:id'), {'id': scid})
    foreign = await client.get(f'/api/v3/needs/{nid}', headers={'Authorization':f'Bearer {make_token(seller)}'})
    assert 'requirements_evidence' not in foreign.json()
    assert (await client.get(f'/api/v3/needs/{nid}/revisions', headers={'Authorization':f'Bearer {make_token(seller)}'})).status_code == 404


async def test_group_consent_and_hold_expire_together(client, db_session, spec):
    from app.models import CompatibilityProfile, Coalition, CoalitionMember, GroupOffer
    nid, _, cid, scid, headers, _, _, _, _, _, held = spec
    profile = CompatibilityProfile(category='Мебель', input_hash='synthetic-s03-group')
    db_session.add(profile); await db_session.flush()
    group = Coalition(category='Мебель', compatibility_profile_id=profile.id, combined_volume_units=10, status='awaiting_approvals')
    db_session.add(group); await db_session.flush()
    member = CoalitionMember(coalition_id=group.id, need_id=nid, buyer_company_id=cid, units=10,
        approval_status='approved', commercial_estimate={'historical': 'unchanged'})
    proposal = GroupOffer(coalition_id=group.id, company_id=scid, status='preliminary', seller_approval_status='approved')
    db_session.add_all([member, proposal]); held.anchor_type='coalition'; held.anchor_id=group.id
    await db_session.commit()
    body, impact = await preview(client, spec, volume_units=20)
    assert str(group.id) in impact['affected']['coalitions']
    result = await client.put(f'/api/v3/needs/{nid}', headers=headers, json={**body, 'impact_hash':impact['impact_hash']})
    assert result.status_code == 200, result.text
    for row in (group,member,proposal,held):await db_session.refresh(row)
    assert group.status=='cancelled' and member.approval_status=='pending'
    assert proposal.seller_approval_status=='pending' and held.status=='released'
    assert member.commercial_estimate=={'historical':'unchanged'}


async def test_physical_evidence_keeps_input_and_exact_normalization(client, spec):
    _, _, _, _, headers, payload, *_ = spec
    response = await client.post('/api/v3/physical/needs', headers=headers,
        json={**payload, 'category':'Сырьё и материалы', 'subcategory':'Полимеры', 'characteristics':{'unit':'кг'},'volume_units':'1.25','quantity_conversion_approved':True})
    assert response.status_code == 201, response.text
    field=response.json()['requirements_evidence']['fields']['quantity_units']
    assert field['original_value']=='1.25' and field['original_unit']=='кг'
    assert field['value']==1250 and field['normalized_unit']=='г'
