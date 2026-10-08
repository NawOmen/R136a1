"""Exercise real obligation handlers while isolating storage and permissions."""
from contextlib import ExitStack
from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, Mock, patch
import uuid

from app.api import market, resilience
from app.schemas import CoalitionDecisionIn, ResiliencePlanConfirmIn


def result(value):
    return SimpleNamespace(scalar_one_or_none=lambda: value,
                           scalars=lambda: SimpleNamespace(first=lambda: value, all=lambda: value),
                           all=lambda: value)


def need(profile_version, units):
    return SimpleNamespace(id=uuid.uuid4(), revision=3, category='Строительство', subcategory='Крепёж',
        characteristics={'unit': 'шт', 'length_mm': units}, volume_units=units,
        category_profile=None if profile_version is None else {'profile_version': profile_version, 'fields': {'unit': {'label': 'Штуки'}}},
        status='awaiting_approvals', deadline_date=date.today()+timedelta(days=10), valid_until=None)


def report(version):
    return SimpleNamespace(state='ready', profile_title='Крепёж', profile_key='fasteners',
        rules_version=version, blocking_open=0, checked_at=datetime.now(timezone.utc),
        requirements=[SimpleNamespace(code='evidence', state='verified', document_ids=[uuid.uuid4()])])


def permission_patches(stack, module):
    for name in ('require_company_buyer', 'require_company_admin', 'require_verified_company', 'reserve'):
        stack.enter_context(patch.object(module, name, AsyncMock()))


class ObligationProfileAuditTests(IsolatedAsyncioTestCase):
    async def test_coalition_freezes_each_participant_with_its_admission(self):
        needs = [need(1, 10), need(None, 20)]
        members = [SimpleNamespace(id=uuid.uuid4(), need_id=item.id, buyer_company_id=uuid.uuid4(),
                   approval_status='pending' if index == 0 else 'approved', units=item.volume_units,
                   total_cost_rub=item.volume_units*12) for index, item in enumerate(needs)]
        seller = uuid.uuid4()
        coalition = SimpleNamespace(id=uuid.uuid4(), version=4, status='awaiting_approvals',
                                    producer_company_id=seller, category='Строительство')
        offer = SimpleNamespace(id=uuid.uuid4(), status='preliminary', seller_approval_status='approved',
            company_id=seller, fill_deadline=date.today()+timedelta(days=2), production_start=date.today(),
            production_end=date.today()+timedelta(days=5))
        db = SimpleNamespace(execute=AsyncMock(side_effect=[result(coalition), result(offer), result(members[0]), result(members)]),
            get=AsyncMock(side_effect=lambda model, key: next(item for item in needs if item.id == key)),
            add=Mock(), commit=AsyncMock())
        reports = [report('rules-one'), report('rules-two')]
        audit = AsyncMock()
        with ExitStack() as stack:
            permission_patches(stack, market)
            admission = stack.enter_context(patch.object(market, 'require_admission_for_specifications', AsyncMock(return_value=reports)))
            stack.enter_context(patch.object(market, 'append_audit_event', audit))
            stack.enter_context(patch.object(market, '_coalition_out', AsyncMock()))
            stack.enter_context(patch.object(market, '_user_company_ids', AsyncMock(return_value=[])))
            await market.decide_coalition(coalition.id, CoalitionDecisionIn(company_id=members[0].buyer_company_id,
                decision='approved', expected_revision=4), SimpleNamespace(id=uuid.uuid4()), db)
        self.assertEqual(coalition.status, 'confirmed')
        self.assertEqual(db.add.call_count, 2)
        self.assertEqual(len(admission.await_args.args[2]), 2)
        participants = audit.await_args.kwargs['payload']['participants']
        self.assertEqual(len(participants), 2)
        for item, member, original, checked in zip(participants, members, needs, reports, strict=True):
            self.assertEqual(item['need_id'], str(original.id))
            self.assertEqual(item['buyer_company_id'], str(member.buyer_company_id))
            self.assertEqual(item['seller_company_id'], str(seller))
            self.assertEqual(item['need_revision'], 3)
            self.assertEqual(item['units'], original.volume_units)
            self.assertEqual(item['admission']['rules_version'], checked.rules_version)
            self.assertEqual(item['admission']['requirements'][0]['documents'], [str(checked.requirements[0].document_ids[0])])
            self.assertEqual(item['admission']['specification']['category_profile'], original.category_profile)
            self.assertEqual(item['admission']['specification']['characteristics'], original.characteristics)
        needs[0].characteristics['length_mm'] = 999
        needs[0].category_profile['fields']['unit']['label'] = 'Изменено'
        self.assertEqual(participants[0]['admission']['specification']['characteristics']['length_mm'], 10)
        self.assertEqual(participants[0]['admission']['specification']['category_profile']['fields']['unit']['label'], 'Штуки')
        self.assertIsNone(participants[1]['admission']['specification']['category_profile'])

    async def test_resilience_approval_freezes_every_baseline_allocation(self):
        original = need(2, 30)
        sellers = sorted([str(uuid.uuid4()), str(uuid.uuid4())])
        allocations = [dict(company_id=seller, units=units, unit_price_rub=12, delivery_cost_rub=0,
                            lead_time_days=1) for seller, units in zip(sellers, [10, 20])]
        plan = SimpleNamespace(id=uuid.uuid4(), need_id=original.id, buyer_company_id=uuid.uuid4(), version=5,
            status='ready_for_confirmation', baseline_allocations=allocations, baseline_variant_id=uuid.uuid4(),
            auto_replace_within_thresholds=False, max_price_increase_pct=5, max_delay_days=2)
        offers = [SimpleNamespace(id=uuid.uuid4(), moq_units=1, available_units=50, price_rub=12, price_tiers=[],
            delivery_cost_rub=0, lead_time_days=1, valid_until=None, resource_kind='production', product_id=None) for _ in sellers]
        db = SimpleNamespace(scalar=AsyncMock(side_effect=[plan, original]),
                             scalars=AsyncMock(side_effect=[result([offer]) for offer in offers]),
                             add=Mock(), commit=AsyncMock())
        reports = [report('first'), report('second')]
        approval = AsyncMock()
        with ExitStack() as stack:
            permission_patches(stack, resilience)
            admission = stack.enter_context(patch.object(resilience, 'require_company_admission', AsyncMock(side_effect=reports)))
            stack.enter_context(patch.object(resilience, '_lock_plan_resources', AsyncMock()))
            stack.enter_context(patch.object(resilience, 'record_human_approval', approval))
            stack.enter_context(patch.object(resilience, '_plan_out', AsyncMock()))
            await resilience.confirm_resilience_plan(plan.id, ResiliencePlanConfirmIn(approved=True, expected_revision=5),
                                                     SimpleNamespace(id=uuid.uuid4()), db)
        self.assertEqual(plan.status, 'active')
        self.assertEqual(admission.await_count, 2)
        payload = approval.await_args.kwargs['payload']
        self.assertEqual(payload['plan_version'], 5)
        snapshots = payload['baseline_allocations']
        self.assertEqual(len(snapshots), 2)
        for snapshot, allocation, offer, checked in zip(snapshots, allocations, offers, reports, strict=True):
            self.assertEqual(snapshot['allocation'], allocation)
            self.assertEqual(snapshot['offer_id'], str(offer.id))
            self.assertEqual(snapshot['need_revision'], 3)
            self.assertEqual(snapshot['admission']['rules_version'], checked.rules_version)
            self.assertEqual(snapshot['admission']['specification']['moq_units'], allocation['units'])
            self.assertEqual(snapshot['admission']['specification']['category_profile'], original.category_profile)
            self.assertEqual(snapshot['admission']['specification']['characteristics'], original.characteristics)
        allocations[0]['units'] = 999
        original.characteristics['length_mm'] = 999
        original.category_profile['profile_version'] = 99
        self.assertEqual(snapshots[0]['allocation']['units'], 10)
        self.assertEqual(snapshots[0]['admission']['specification']['characteristics']['length_mm'], 30)
        self.assertEqual(snapshots[0]['admission']['specification']['category_profile']['profile_version'], 2)
