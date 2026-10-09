"""Real obligation handlers and admission guard; storage/permissions are isolated."""
from contextlib import ExitStack
from datetime import date, timedelta
from types import SimpleNamespace as NS
from unittest import IsolatedAsyncioTestCase, TestCase
from unittest.mock import AsyncMock, Mock, patch
import uuid

from fastapi import HTTPException
from app.api import market, offers, resilience
from app.category_registry import registry_snapshot, registry_context
from app.category_profile_snapshot import capture_category_profile
from app.matching import _passport_matches
from app.schemas import CoalitionDecisionIn, OfferSelectIn, ReserveDecisionIn, GroupOfferPublishIn


def result(value):
    return NS(scalar_one_or_none=lambda: value, scalar_one=lambda: value,
              scalars=lambda: NS(first=lambda: value, all=lambda: value), all=lambda: value)


def setup_revision():
    saved = capture_category_profile('Упаковка и тара', 'Бумажные стаканы')
    registry = registry_snapshot()
    leaf = next(leaf for group in registry['groups'] for leaf in group['leaves'] if leaf['id'] == saved['category_id'])
    leaf['technical_profile']['version'] += 1
    return saved, registry, leaf


class StaleCapacityProfileTests(IsolatedAsyncioTestCase):
    async def test_every_obligation_rejects_old_need_after_new_rules_without_writing(self):
        saved, registry, leaf = setup_revision()
        for route in ('direct', 'group_publish', 'group_confirm', 'reserve'):
            with self.subTest(route=route), registry_context(registry), ExitStack() as stack:
                seller, buyer = uuid.uuid4(), uuid.uuid4()
                need = NS(id=uuid.uuid4(), revision=1, company_id=buyer, category='Упаковка и тара',
                          subcategory='Бумажные стаканы', characteristics={'unit':'шт', 'material':'бумага', 'volume_ml':400},
                          category_profile=saved, volume_units=100, budget_rub=10000,
                          deadline_date=date.today()+timedelta(days=20), valid_until=None, status='awaiting_approvals')
                user = NS(id=uuid.uuid4())
                db = NS(get=AsyncMock(), execute=AsyncMock(), scalar=AsyncMock(return_value=None),
                        refresh=AsyncMock(), add=Mock(), flush=AsyncMock(), commit=AsyncMock())
                if route == 'direct':
                    module = offers
                    offer = NS(id=uuid.uuid4(), company_id=seller, need_id=need.id, revision=1, status='sent',
                               available_units=100, moq_units=1, product_id=None, valid_until=None,
                               lead_time_days=1, price_rub=10, price_tiers=[], delivery_cost_rub=0,commercial_quote={'estimate':{'complete':True,'total_rub':'1000'},'need':{'revision':1}})
                    db.get.return_value = offer
                    db.execute.return_value = result(need)
                    stack.enter_context(patch.object(module, 'get_company', AsyncMock(return_value={'verification_status':'verified'})))
                    action = lambda: offers.select_offer(offer.id, OfferSelectIn(expected_revision=1, human_approved=True), user, db)
                elif route == 'reserve':
                    module = resilience
                    commitment = NS(id=uuid.uuid4(), company_id=seller, plan_id=uuid.uuid4(), offer_id=None, confirmation_status='pending')
                    plan = NS(id=commitment.plan_id, need_id=need.id, status='preparing_reserves')
                    db.execute.side_effect = [result(commitment), result(plan)]
                    db.get.return_value = need
                    stack.enter_context(patch.object(module, '_lock_plan_resources', AsyncMock()))
                    stack.enter_context(patch.object(module, '_lock_plan_need', AsyncMock()))
                    action = lambda: resilience.decide_reserve_commitment(commitment.id, ReserveDecisionIn(company_id=seller, decision='approved'), user, db)
                else:
                    module = market
                    stack.enter_context(patch.object(module, '_lock_coalition_needs', AsyncMock(return_value={need.id: need})))
                    stack.enter_context(patch.object(module, 'record_human_approval', AsyncMock()))
                    coalition = NS(id=uuid.uuid4(), version=1, status='awaiting_approvals', producer_company_id=seller,
                                   compatibility_profile_id=uuid.uuid4())
                    members = [NS(id=uuid.uuid4(), need_id=need.id, buyer_company_id=buyer, units=100, approval_status='pending',commercial_estimate={'complete':True})]
                    group = NS(id=uuid.uuid4(), coalition_id=coalition.id, company_id=seller, status='preliminary',
                               seller_approval_status='approved', fill_deadline=date.today()+timedelta(days=1))
                    if route == 'group_confirm':
                        db.execute.side_effect = [result(coalition), result(group), result(members[0]), result(members),
                                                  result('verified'),
                                                  result([(member.buyer_company_id, 'verified') for member in members])]
                        db.get.return_value = need
                        action = lambda: market.decide_coalition(coalition.id, CoalitionDecisionIn(company_id=buyer, decision='approved', expected_revision=1), user, db)
                    else:
                        group.status = 'draft'
                        coalition.status = 'candidate'
                        db.scalar.return_value = coalition
                        db.get.side_effect = [group, NS()]
                        db.execute.return_value = result(members)
                        data = GroupOfferPublishIn(min_total_units=100, max_total_units=1000, available_capacity_units=1000,
                            price_tiers=[{'min_units':100,'unit_price_rub':10}], fill_deadline=date.today()+timedelta(days=1),
                            production_start=date.today()+timedelta(days=2), production_end=date.today()+timedelta(days=3),
                            non_fill_rule='close_without_obligations', participant_terms=[{'need_id':need.id},{'need_id':uuid.uuid4()}])
                        action = lambda: market.publish_group_offer(group.id, data, user, db)
                for name in ('require_company_buyer','require_company_seller','require_company_admin','require_verified_company'):
                    if hasattr(module,name): stack.enter_context(patch.object(module,name,AsyncMock()))
                # Keep require_company_admission real: dropping the frozen snapshot must fail this regression.
                with self.assertRaises(HTTPException) as rejected:
                    await action()
                self.assertEqual(rejected.exception.status_code,409)
                self.assertIn('Сохранённая версия правил потребности',rejected.exception.detail)
                db.add.assert_not_called()
                db.flush.assert_not_awaited()
                db.commit.assert_not_awaited()
                self.assertEqual(saved['profile_version'], leaf['technical_profile']['version']-1)


class PassportVersionTests(TestCase):
    def test_discovery_and_admission_compare_frozen_profile_with_current_scope(self):
        saved, registry, leaf = setup_revision()
        passport = NS(details={'category_scopes':[{'category_id':leaf['id'], 'profile_version':leaf['technical_profile']['version'],
                        'unit':'шт', 'min_units':1, 'max_units':1000,
                        'characteristics':{'material':['бумага'],'volume_ml':[400]}}]})
        common = {'unit':'шт','material':'бумага','volume_ml':400}
        with registry_context(registry):
            args = (passport,'Упаковка и тара',common,'Бумажные стаканы',100)
            self.assertFalse(_passport_matches(*args,category_profile=saved))
            current = capture_category_profile('Упаковка и тара','Бумажные стаканы')
            self.assertTrue(_passport_matches(*args,category_profile=current))
            discovery = {**common,'category_profile_version':{'category_id':saved['category_id'],'version':saved['profile_version']}}
            self.assertFalse(_passport_matches(passport,'Упаковка и тара',discovery,'Бумажные стаканы',100))
            discovery['category_profile_version']['version'] = current['profile_version']
            self.assertTrue(_passport_matches(passport,'Упаковка и тара',discovery,'Бумажные стаканы',100))
            self.assertFalse(_passport_matches(*args,category_profile={**current,'profile_version':True}))
            self.assertTrue(_passport_matches(*args,category_profile=None))
