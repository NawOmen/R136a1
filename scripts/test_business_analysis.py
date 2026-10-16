"""S16: unknown, comparability, negative outcomes and exact economic boundaries."""
import copy
from decimal import Decimal
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

spec = importlib.util.spec_from_file_location('business_analysis', Path(__file__).with_name('business_analysis.py'))
analysis = importlib.util.module_from_spec(spec)
spec.loader.exec_module(analysis)


class BusinessAnalysis(unittest.TestCase):
    def setUp(self):
        self.data = json.loads(analysis.DEFAULT_INPUT.read_text())

    def case(self, identifier='direct'):
        return copy.deepcopy(next(c for c in self.data['cases'] if c['id'] == identifier))

    def result(self, case):
        data = copy.deepcopy(self.data)
        data['cases'] = [case]
        return analysis.build_report(data)['cases'][0]

    def test_full_cost_and_first_use_training_without_waiting_in_labour(self):
        result = self.result(self.case())
        self.assertEqual(result['buyer']['procurement_saving_rub'], '300.00')
        self.assertEqual(result['buyer']['time']['steady_active_saving_minutes'], '40')
        self.assertEqual(result['buyer']['time']['first_use_active_saving_minutes'], '30')
        self.assertEqual(result['buyer']['value_equivalent_rub'], '600.00')
        c = self.case(); c['buyer']['time'].update(manual_wait_minutes='100000', model_wait_minutes='90000')
        self.assertEqual(self.result(c)['buyer']['value_equivalent_rub'], '600.00')

    def test_corrections_retries_and_losses_are_retained(self):
        result = self.result(self.case('corrections'))
        self.assertEqual(result['buyer']['value_equivalent_rub'], '-700.00')
        self.assertEqual(result['seller']['value_equivalent_rub'], '-500.00')
        self.assertLess(Decimal(result['buyer']['procurement_saving_percent']), 0)

    def test_missing_or_incomparable_scope_never_claims_savings(self):
        for key, value in [('quantity', '101'), ('unit', 'кг'), ('tax_basis', 'unknown'),
                           ('destination', 'another-address'), ('specification', None), ('category_id', None),
                           ('deadline', 'another-period')]:
            with self.subTest(key=key):
                c = self.case(); c['buyer']['system']['scope'][key] = value
                r = self.result(c)
                self.assertFalse(r['buyer']['comparable'])
                self.assertIsNone(r['buyer']['procurement_saving_percent'])
                self.assertIsNone(r['buyer']['value_equivalent_rub'])
                self.assertIsNone(r['buyer']['time']['labour_equivalent_rub'])
        c = self.case(); c['buyer']['system']['scope']['quantity'] = '100.0'
        self.assertTrue(self.result(c)['buyer']['comparable'])

    def test_known_supplier_can_be_cheaper_than_automation(self):
        r = self.result(self.case('known-supplier'))
        self.assertEqual(r['buyer']['procurement_saving_rub'], '0.00')
        self.assertEqual(r['buyer']['value_equivalent_rub'], '-250.00')

    def test_unknown_baseline_costs_and_payments_are_not_zero(self):
        r = self.result(self.case('unknown'))
        self.assertIsNone(r['buyer']['procurement_saving_rub'])
        self.assertIsNone(r['buyer']['procurement_saving_percent'])
        self.assertIsNone(r['seller']['incremental_contribution_rub'])
        self.assertIsNone(r['seller']['payments_rub'])
        self.assertIsNone(r['platform']['operating_result_rub'])

    def test_repeat_is_not_additional_market_volume(self):
        r = self.result(self.case('repeat'))
        self.assertEqual(r['seller']['incremental_contribution_rub'], '0.00')
        self.assertEqual(r['seller']['value_equivalent_rub'], '300.00')
        r = self.result(self.case('additional-volume'))
        self.assertEqual(r['seller']['incremental_contribution_rub'], '700.00')

    def test_scenario_subscription_and_commission_include_payer_costs(self):
        subscription = self.result(self.case('additional-volume'))
        self.assertEqual(subscription['buyer']['value_equivalent_rub'], '450.00')
        self.assertEqual(subscription['platform']['after_development_and_acquisition_rub'], '-197.00')
        commission = self.result(self.case('commission'))
        self.assertEqual(commission['buyer']['value_equivalent_rub'], '600.00')
        self.assertEqual(commission['seller']['value_equivalent_rub'], '750.00')
        self.assertEqual(commission['platform']['operating_result_rub'], '53.00')

    def test_gmv_never_becomes_platform_income_and_all_costs_matter(self):
        c = self.case(); c['platform']['gmv_rub'] = '999999999.00'
        r = self.result(c)['platform']
        self.assertEqual(r['scenario_income_rub'], '0.00')
        self.assertEqual(r['operating_result_rub'], '-97.00')
        self.assertEqual(r['after_development_and_acquisition_rub'], '-347.00')
        c['platform']['allocated_acquisition_rub'] = None
        self.assertIsNone(self.result(c)['platform']['after_development_and_acquisition_rub'])
        c['platform']['tax_comparable'] = False
        self.assertIsNone(self.result(c)['platform']['operating_result_rub'])

    def test_unknown_probability_and_switching_do_not_promise_prevented_loss(self):
        r = self.result(self.case())['reserve']
        self.assertIsNone(r['expected_effect_rub'])
        self.assertEqual(r['conditional_net_effect_rub'], '3700.00')
        self.assertEqual(r['sensitivity_rub']['0.1'], '280.00')
        r = self.result(self.case('unknown-time'))['reserve']
        self.assertIsNone(r['conditional_net_effect_rub'])
        self.assertTrue(all(v is None for v in r['sensitivity_rub'].values()))

    def test_expensive_and_useless_reserve_can_lose_money(self):
        r = self.result(self.case('expensive-reserve'))['reserve']
        self.assertEqual(r['expected_effect_rub'], '-2620.00')
        self.assertEqual(r['uncovered_units'], '20')
        c = self.case(); c['reserve'].update(loss_with_rub='7000.00', incident_probability='1')
        r = self.result(c)['reserve']
        self.assertEqual(r['expected_effect_rub'], '-2300.00')
        self.assertIsNone(r['break_even_probability'])

    def test_blocked_and_abandoned_do_not_become_success_or_sales_benefits(self):
        report = analysis.build_report(self.data)
        self.assertEqual(report['case_count'], 12)
        self.assertEqual(report['outcomes'], {'completed': 10, 'blocked': 1, 'abandoned': 1})
        for id in ('below-moq', 'abandoned'):
            with self.subTest(id=id):
                r = self.result(self.case(id))
                self.assertIsNone(r['buyer']['value_equivalent_rub'])
                self.assertIsNone(r['seller']['value_equivalent_rub'])
                self.assertIsNone(r['buyer']['time']['labour_equivalent_rub'])
                self.assertIsNone(r['buyer']['time']['first_use_active_saving_minutes'])
                self.assertEqual(r['buyer']['time']['system_labour_cost_equivalent_rub'],
                                 '300.00' if id == 'below-moq' else '800.00')
                self.assertEqual(r['platform']['operating_result_rub'], '-97.00')

    def test_exact_decimal_input_and_round_only_final_value(self):
        c = self.case(); c['buyer']['baseline']['costs']['goods_rub'] = '10000.01'
        c['buyer']['time'].update(manual_active_minutes='1', system_active_minutes='0',
            correction_minutes='0', retry_minutes='0', system_training_minutes='0', hourly_rate_rub='1.00')
        self.assertEqual(self.result(c)['buyer']['value_equivalent_rub'], '300.03')
        for value in (True, 0.1, '-1', 'NaN', 'Infinity', '0.001'):
            with self.subTest(value=value):
                c = self.case(); c['platform']['storage_rub'] = value
                with self.assertRaises(ValueError): self.result(c)
        c = self.case(); c['reserve']['incident_probability'] = '1.01'
        with self.assertRaises(ValueError): self.result(c)

    def test_all_current_categories_have_exact_profile_and_example_coverage(self):
        r = analysis.catalogue_analysis()
        self.assertEqual((r['groups'], r['leaves'], r['seeded_working_leaves']), (12, 47, 46))
        self.assertEqual(r['admission_states'], {'existing_rules': 46, 'unsupported': 1})
        self.assertEqual({row['id'] for row in r['categories'] if row['seeded_working_leaf']},
                         {row['id'] for row in r['categories'] if row['admission_state'] != 'unsupported'})
        for row in r['categories']:
            self.assertTrue(row['required_fields'])
            self.assertTrue(row['example_incompatible_fields'])
            self.assertEqual(len(row['routes']), 10)
            for ref in row['test_refs']: self.assertTrue((analysis.ROOT / ref).is_file())

    def test_registry_mismatch_or_duplicate_example_cannot_pass(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            for relative in ('services/marketplace/app/category_registry.json',
                             'services/marketplace/unit/fixtures/category_stage01.json'):
                path = root / relative; path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes((analysis.ROOT / relative).read_bytes())
            fixtures = root / 'services/marketplace/unit/fixtures/category_stage01.json'
            data = json.loads(fixtures.read_text()); data.pop(); fixtures.write_text(json.dumps(data))
            with self.assertRaises(ValueError): analysis.catalogue_analysis(root)
            data.append(copy.deepcopy(data[0])); fixtures.write_text(json.dumps(data))
            with self.assertRaises(ValueError): analysis.catalogue_analysis(root)

    def test_version_and_unsupported_category_cannot_be_forged(self):
        for key, value in [('schema_version', 2), ('schema_version', True), ('kind', 'sales_results'), ('currency', 'USD')]:
            with self.subTest(key=key):
                data = copy.deepcopy(self.data); data[key] = value
                with self.assertRaises(ValueError): analysis.build_report(data)
        c = self.case(); c['buyer']['system']['scope']['category_id'] = 'medical-hygiene.consumables'
        with self.assertRaises(ValueError): self.result(c)


if __name__ == '__main__':
    unittest.main()
