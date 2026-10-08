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


async def test_physical_edit_refreshes_preloaded_need_before_revision_check(client, db_session, spec, monkeypatch):
    import asyncio
    from app.api import physical_quantities
    nid, _, _, _, headers, payload, *_ = spec
    loaded, resume = asyncio.Event(), asyncio.Event()
    original = physical_quantities.lock_specification_edit

    async def pause_after_preload(*args, **kwargs):
        loaded.set()
        await resume.wait()
        return await original(*args, **kwargs)

    monkeypatch.setattr(physical_quantities, 'lock_specification_edit', pause_after_preload)
    stale = asyncio.create_task(client.put(f'/api/v3/physical/needs/{nid}', headers=headers,
        json={**payload, 'volume_units': 15, 'expected_revision': 1}))
    try:
        await asyncio.wait_for(loaded.wait(), 5)
        body, impact = await preview(client, spec, volume_units=20)
        saved = await client.put(f'/api/v3/needs/{nid}', headers=headers,
            json={**body, 'impact_hash': impact['impact_hash']})
        assert saved.status_code == 200, saved.text
        resume.set()
        response = await asyncio.wait_for(stale, 5)
        assert response.status_code == 409, response.text
        await db_session.refresh(await db_session.get(Need, nid))
        assert (await db_session.get(Need, nid)).volume_units == 20
        history = (await client.get(f'/api/v3/needs/{nid}/revisions', headers=headers)).json()
        assert [row['revision'] for row in history] == [2, 1]
    finally:
        resume.set()
        if not stale.done():
            stale.cancel()
        await asyncio.gather(stale, return_exceptions=True)


@pytest.fixture
async def publishable_group(db_session, spec, monkeypatch):
    from app.models import CompatibilityProfile, Coalition, CoalitionMember, GroupOffer
    from conftest import confirmed_quote_terms
    nid, _, cid, scid, _, _, *_ = spec
    user2 = await make_user(db_session)
    company2 = await make_company(db_session, user2, can_buy=True, can_sell=False)
    need2 = Need(company_id=company2, created_by_user_id=user2, category='Мебель',
        characteristics={'unit': 'шт', 'material': 'дерево'}, volume_units=10,
        deadline_date=date.today()+timedelta(days=30), status='open_for_offers')
    profile = CompatibilityProfile(category='Мебель', input_hash='synthetic-publish-race', common_base={'unit': 'шт'})
    db_session.add_all([need2, profile]); await db_session.flush()
    coalition = Coalition(category='Мебель', compatibility_profile_id=profile.id, producer_company_id=scid,
        combined_volume_units=20, status='candidate')
    db_session.add(coalition); await db_session.flush()
    db_session.add_all([CoalitionMember(coalition_id=coalition.id, need_id=nid, buyer_company_id=cid, units=10),
        CoalitionMember(coalition_id=coalition.id, need_id=need2.id, buyer_company_id=company2, units=10)])
    group = GroupOffer(coalition_id=coalition.id, company_id=scid, status='draft', seller_approval_status='pending')
    db_session.add(group); await db_session.commit()
    seller = await db_session.scalar(text('SELECT user_id FROM auth.company_members WHERE company_id=:id'), {'id': scid})
    seller_headers = {'Authorization': f'Bearer {make_token(seller)}'}
    data = {'min_total_units': 1, 'max_total_units': 100, 'available_capacity_units': 100,
        'price_tiers': [{'min_units': 1, 'unit_price_rub': '10'}],
        'production_start': str(date.today()+timedelta(days=3)), 'production_end': str(date.today()+timedelta(days=4)),
        'fill_deadline': str(date.today()+timedelta(days=1)), 'non_fill_rule': 'recalculate',
        'participant_terms': [{'need_id': str(n), 'delivery_cost_rub': '0', 'commercial_terms': confirmed_quote_terms()}
                              for n in (nid, need2.id)]}

    async def no_rematch(*args, **kwargs):
        pass

    async def admitted(*args, **kwargs):
        return []

    async def evaluated(payload):
        return {'feasible': True, 'reasons': [], 'members': [
            {'need_id': member['need_id'], 'common_production_cost_rub': member['volume_units']*10,
             'delivery_cost_rub': 0, 'total_cost_rub': member['volume_units']*10,
             'baseline_cost_rub': None, 'benefit_rub': None} for member in payload['members']]}

    monkeypatch.setattr('app.api.market.require_admission_for_specifications', admitted)
    monkeypatch.setattr('app.api.market.evaluate_coalition', evaluated)
    monkeypatch.setattr('app.api.market.run_market_rematch', no_rematch)
    monkeypatch.setattr('app.api.needs.run_market_rematch', no_rematch)
    return group.id, coalition.id, seller_headers, data


async def test_group_publication_refreshes_cancelled_group_after_wait(client, db_session, spec, publishable_group, monkeypatch):
    import asyncio
    from app.api import market
    from app.models import Coalition, GroupOffer, ParticipantOrder
    group_id, coalition_id, seller_headers, data = publishable_group
    nid, _, _, _, buyer_headers, *_ = spec
    read, resume = asyncio.Event(), asyncio.Event()
    original = market._lock_coalition_needs

    async def pause_before_lock(*args, **kwargs):
        read.set()
        await resume.wait()
        return await original(*args, **kwargs)

    monkeypatch.setattr(market, '_lock_coalition_needs', pause_before_lock)
    publish = asyncio.create_task(client.post(f'/api/v3/group-offers/{group_id}/publish', headers=seller_headers, json=data))
    try:
        await asyncio.wait_for(read.wait(), 5)
        body, impact = await preview(client, spec, volume_units=20)
        saved = await client.put(f'/api/v3/needs/{nid}', headers=buyer_headers,
            json={**body, 'impact_hash': impact['impact_hash']})
        assert saved.status_code == 200, saved.text
        resume.set()
        response = await asyncio.wait_for(publish, 5)
        assert response.status_code == 409, response.text
        coalition = await db_session.get(Coalition, coalition_id); await db_session.refresh(coalition)
        group = await db_session.get(GroupOffer, group_id); await db_session.refresh(group)
        assert coalition.status == 'cancelled'
        assert group.status == 'recalculation_required' and group.seller_approval_status == 'pending'
        assert not (await db_session.scalars(select(ParticipantOrder))).all()
    finally:
        resume.set()
        if not publish.done():
            publish.cancel()
        await asyncio.gather(publish, return_exceptions=True)


async def test_published_group_binds_consents_to_member_need_revision(client, db_session, spec, publishable_group):
    from app.models import CoalitionMember
    group_id, coalition_id, seller_headers, data = publishable_group
    nid, _, cid, _, buyer_headers, *_ = spec
    published = await client.post(f'/api/v3/group-offers/{group_id}/publish', headers=seller_headers, json=data)
    assert published.status_code == 200, published.text
    members = (await db_session.scalars(select(CoalitionMember).where(CoalitionMember.coalition_id == coalition_id))).all()
    assert all(member.commercial_estimate['need_revision'] == 1 for member in members)
    # Even inconsistent legacy/imported state cannot create an obligation for an old specification.
    need = await db_session.get(Need, nid); await db_session.refresh(need)
    need.revision = 2
    await db_session.commit()
    response = await client.post(f'/api/v3/coalitions/{coalition_id}/decision', headers=buyer_headers,
        json={'company_id': str(cid), 'decision': 'approved', 'expected_revision': published.json()['version']})
    assert response.status_code == 409, response.text


@pytest.mark.parametrize('quantity,unit,origin', [('1.25','кг','agent'), ('1.250','килограмм','agent'),
                                                ('1250','г','agent'), ('2','кг','manual_override'), ('1250','шт','manual_override')])
async def test_gateway_quantity_evidence_preserves_only_equivalent_physical_input(client, db_session, spec, gateway_contract, quantity, unit, origin):
    import json
    _, uid, cid, _, headers, payload, *_ = spec
    run = uuid.uuid4()
    source = {'source_id': 'synthetic-quantity-source', 'source_name': 'Требования покупателя',
        'source_kind': 'text', 'value': '1.25', 'original_unit': 'кг', 'normalized_unit': 'кг',
        'excerpt': 'Нужно 1.25 кг материала', 'content_hash': 'synthetic-sha256',
        'locator': {'located': True, 'start': 0, 'end': 23}, 'active': True, 'confidence': 1}
    result = {'can_confirm': True, 'conflicts': [], 'questions': [], 'properties': [
        {'key': 'quantity_units', 'value': '1.25', 'status': 'confirmed', 'sources': [source]}]}
    has_type = await db_session.scalar(text("SELECT EXISTS(SELECT 1 FROM information_schema.columns WHERE table_schema='agents' AND table_name='agent_runs' AND column_name='agent_type')"))
    query = text("INSERT INTO agents.agent_runs (id,revision,state,result,user_id,company_id,agent_type,requested_route,input_summary) VALUES (:id,1,'confirmed_by_user',CAST(:result AS JSONB),:uid,:cid,'buyer_investigator','local','')" if has_type else
        "INSERT INTO agents.agent_runs (id,revision,state,result,user_id,company_id) VALUES (:id,1,'confirmed_by_user',CAST(:result AS JSONB),:uid,:cid)")
    await db_session.execute(query, {'id': run, 'uid': uid, 'cid': cid, 'result': json.dumps(result)})
    await db_session.commit()
    response = await client.post('/api/v3/physical/needs', headers=headers, json={**payload,
        'category': 'Мебель' if unit == 'шт' else 'Сырьё и материалы',
        'subcategory': None if unit == 'шт' else 'Полимеры', 'characteristics': {'unit': unit},
        'volume_units': quantity, 'quantity_conversion_approved': True, 'agent_run_id': str(run), 'agent_run_revision': 1})
    assert response.status_code == 201, response.text
    field = response.json()['requirements_evidence']['fields']['quantity_units']
    assert field['origin'] == origin
    if origin == 'agent':
        assert field['value'] == 1250 and field['normalized_unit'] == 'г'
        assert field['sources'] == [source]
        assert field['conversion'] == {'input_value': '1.25', 'input_unit': 'кг',
            'normalized_value': 1250, 'normalized_unit': 'г', 'factor': 1000, 'exact': True}
    else:
        assert field['sources'] == [] and field['previous_evidence']['sources'] == [source]


async def test_group_publication_holds_need_lock_until_commit(client, db_session, spec, publishable_group, monkeypatch):
    import asyncio
    from app.models import Coalition, CoalitionMember, ParticipantOrder
    group_id, coalition_id, seller_headers, data = publishable_group
    nid, _, _, _, buyer_headers, *_ = spec
    body, impact = await preview(client, spec, volume_units=20)
    reached, resume = asyncio.Event(), asyncio.Event()

    async def pause_admission(*args, **kwargs):
        reached.set()
        await resume.wait()
        return []

    monkeypatch.setattr('app.api.market.require_admission_for_specifications', pause_admission)
    publish = asyncio.create_task(client.post(f'/api/v3/group-offers/{group_id}/publish', headers=seller_headers, json=data))
    edit = None
    try:
        await asyncio.wait_for(reached.wait(), 5)
        edit = asyncio.create_task(client.put(f'/api/v3/needs/{nid}', headers=buyer_headers,
            json={**body, 'impact_hash': impact['impact_hash']}))
        # Assert an actual PostgreSQL lock wait rather than relying on timing of tasks.
        blocked = False
        for _ in range(100):
            await db_session.execute(text('SELECT pg_stat_clear_snapshot()'))
            blocked = await db_session.scalar(text("SELECT EXISTS(SELECT 1 FROM pg_stat_activity WHERE datname=current_database() AND wait_event_type='Lock' AND query LIKE '%marketplace.needs%' AND pid<>pg_backend_pid())"))
            if blocked:
                break
            await asyncio.sleep(0.01)
        assert blocked and not edit.done()
        resume.set()
        published = await asyncio.wait_for(publish, 5)
        assert published.status_code == 200, published.text
        edited = await asyncio.wait_for(edit, 5)
        assert edited.status_code == 409, edited.text  # Publication changed the impact preview.
        body, fresh = await preview(client, spec, volume_units=20)
        saved = await client.put(f'/api/v3/needs/{nid}', headers=buyer_headers,
            json={**body, 'impact_hash': fresh['impact_hash']})
        assert saved.status_code == 200, saved.text
        assert saved.json()['volume_units'] == 20 and saved.json()['revision'] == 2
        coalition = await db_session.get(Coalition, coalition_id); await db_session.refresh(coalition)
        assert coalition.status == 'cancelled'
        members = (await db_session.scalars(select(CoalitionMember).where(CoalitionMember.coalition_id == coalition_id))).all()
        for member in members:
            user_id = await db_session.scalar(text('SELECT user_id FROM auth.company_members WHERE company_id=:id'), {'id': member.buyer_company_id})
            decision = await client.post(f'/api/v3/coalitions/{coalition_id}/decision',
                headers={'Authorization': f'Bearer {make_token(user_id)}'}, json={
                    'company_id': str(member.buyer_company_id), 'decision': 'approved',
                    'expected_revision': coalition.version})
            assert decision.status_code == 409, decision.text
        assert not (await db_session.scalars(select(ParticipantOrder))).all()
    finally:
        resume.set()
        tasks = [task for task in (publish, edit) if task is not None]
        for task in tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)


@pytest.mark.parametrize('physical', [False, True])
async def test_two_member_edits_serialize_before_need_and_audit_locks(client, db_session, session_factory,
                                                                    spec, publishable_group, monkeypatch, physical):
    import asyncio
    from app.api import needs as needs_api
    from app.matching import run_market_rematch
    from app.models import Coalition, CoalitionMember, MatchEvent, ParticipantOrder
    _, coalition_id, _, _ = publishable_group
    nid, _, _, _, headers, *_ = spec
    other = await db_session.scalar(select(CoalitionMember).where(
        CoalitionMember.coalition_id == coalition_id, CoalitionMember.need_id != nid))
    other_need = await db_session.get(Need, other.need_id)
    other_headers = {'Authorization': f'Bearer {make_token(other_need.created_by_user_id)}'}
    other_body = {'company_id': str(other_need.company_id), 'category': other_need.category,
        'characteristics': other_need.characteristics, 'volume_units': 11,
        'deadline_date': str(other_need.deadline_date), 'expected_revision': 1}
    other_base = '/api/v3/physical/needs' if physical else '/api/v3/needs'
    if physical:
        other_body.update(category='Сырьё и материалы', subcategory='Полимеры', characteristics={'unit': 'кг'},
                          volume_units='0.011', quantity_conversion_approved=True)
    second_preview = await client.post(f'{other_base}/{other.need_id}/edit-preview',
        headers=other_headers, json=other_body)
    assert second_preview.status_code == 200, second_preview.text
    first_body, first_impact = await preview(client, spec, volume_units=20)
    # Keep the actual cross-market status updates that caused the deadlock.
    monkeypatch.setattr(needs_api, 'run_market_rematch', run_market_rematch)
    entered, resume = asyncio.Event(), asyncio.Event()
    original = needs_api.revision_impact

    async def pause_first_editor(db, need, data):
        if need.id == nid:
            entered.set()
            await resume.wait()
        return await original(db, need, data)

    monkeypatch.setattr(needs_api, 'revision_impact', pause_first_editor)
    first = asyncio.create_task(client.put(f'/api/v3/needs/{nid}', headers=headers,
        json={**first_body, 'impact_hash': first_impact['impact_hash']}))
    second = None
    try:
        await asyncio.wait_for(entered.wait(), 5)
        second = asyncio.create_task(client.put(f'{other_base}/{other.need_id}', headers=other_headers,
            json={**other_body, 'impact_hash': second_preview.json()['impact_hash']}))
        waiting = False
        for _ in range(100):
            await db_session.execute(text('SELECT pg_stat_clear_snapshot()'))
            waiting = await db_session.scalar(text("SELECT EXISTS(SELECT 1 FROM pg_stat_activity WHERE datname=current_database() AND wait_event_type='Lock' AND query LIKE '%need_specification_edit%' AND pid<>pg_backend_pid())"))
            if waiting:
                break
            await asyncio.sleep(0.01)
        assert waiting and not second.done()
        # The second request must not hold its Need row while waiting for the edit boundary.
        async with session_factory() as probe:
            assert await probe.scalar(select(Need.id).where(Need.id == other.need_id).with_for_update(nowait=True)) == other.need_id
            await probe.rollback()
        resume.set()
        first_response, second_response = await asyncio.wait_for(asyncio.gather(first, second), 10)
        assert first_response.status_code == 200, first_response.text
        assert second_response.status_code == 409, second_response.text
        # The changed group requires fresh consent, not a hidden automatic retry of stale approval.
        refreshed = await client.post(f'{other_base}/{other.need_id}/edit-preview', headers=other_headers, json=other_body)
        assert refreshed.status_code == 200, refreshed.text
        retried = await client.put(f'{other_base}/{other.need_id}', headers=other_headers,
            json={**other_body, 'impact_hash': refreshed.json()['impact_hash']})
        assert retried.status_code == 200, retried.text
        for need_id, expected_units, owner_headers in ((nid, 20, headers), (other.need_id, 11, other_headers)):
            saved = await client.get(f'/api/v3/needs/{need_id}', headers=owner_headers)
            assert saved.json()['revision'] == 2 and saved.json()['volume_units'] == expected_units
        coalition = await db_session.get(Coalition, coalition_id); await db_session.refresh(coalition)
        assert coalition.status == 'cancelled'
        assert not (await db_session.scalars(select(ParticipantOrder))).all()
        events = (await db_session.scalars(select(MatchEvent).where(MatchEvent.event_type == 'need_specification_changed'))).all()
        assert len(events) == 2 and all(event.status == 'processed' for event in events)
    finally:
        resume.set()
        tasks = [task for task in (first, second) if task is not None]
        for task in tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
