import unittest
from decimal import Decimal
from datetime import date
from types import SimpleNamespace
from app.physical_quantities import normalize_physical
from app.resource_scopes import prepare_conversions, conversion_for, occupied_units, resize_reservation
from app.category_compatibility import compare_specifications, equal_value
from app.category_registry import registry_snapshot
from app.schemas import CapabilityDetails


class PhysicalQuantityTests(unittest.TestCase):
    def test_fractional_need_uses_exact_integer_base_and_explicit_consent(self):
        raw={'characteristics':{'unit':'кг'},'volume_units':'2,5'}
        with self.assertRaisesRegex(ValueError,'подтвердите'):normalize_physical('need',raw)
        data,preview=normalize_physical('need',{**raw,'quantity_conversion_approved':True})
        self.assertEqual((data['volume_units'],data['characteristics']['unit'],preview['factor']),(2500,'г',1000))
        self.assertEqual(raw['characteristics']['unit'],'кг')

    def test_prices_tiers_stock_and_multiples_use_same_exact_unit(self):
        raw={'characteristics':{'unit':'м','order_multiple':'0.5'},'moq_units':1.2,'stock_units':0,'price_rub':120,'price_tiers':[{'min_units':2,'unit_price_rub':100}],'quantity_conversion_approved':True}
        data,_=normalize_physical('product',raw)
        self.assertEqual((data['moq_units'],data['stock_units'],data['price_rub']),(1200,0,Decimal("0.12")))
        self.assertEqual(data['price_tiers'],[{'min_units':2000,'unit_price_rub':Decimal('0.1')}])
        self.assertEqual(data['characteristics']['order_multiple'],500)

    def test_no_rounding_nonfinite_boolean_overflow_or_conflicting_aliases(self):
        for value in ['0.0001','NaN','Infinity',True,2147484]:
            with self.subTest(value=value),self.assertRaises(ValueError):
                normalize_physical('need',{'volume_units':value,'characteristics':{'unit':'кг'}},require_approval=False)
        with self.assertRaises(ValueError):normalize_physical('need',{'volume_units':1,'characteristics':{'unit':'кг','единица измерения':'м'}},require_approval=False)
        with self.assertRaises(ValueError):normalize_physical('need',{'volume_units':1.2,'characteristics':{'unit':'упак'}},require_approval=False)

    def test_all_physical_dimensions_precision(self):
        for unit,volume,base,total in [('т','0.001','г',1000),('м','0.001','мм',1),('м²','0.0001','см²',1),('л','0.001','мл',1),('м³','0.000001','мл',1)]:
            data,_=normalize_physical('need',{'volume_units':volume,'characteristics':{'unit':unit}},require_approval=False)
            self.assertEqual((data['characteristics']['unit'],data['volume_units']),(base,total))


class ResourceScopeTests(unittest.TestCase):
    def setUp(self):
        self.values=[{'category_id':'packaging.paper-cups','order_unit':'шт','resource_units_per_order_unit':3}]

    def test_shared_resource_needs_confirmed_current_coefficient_and_period(self):
        with self.assertRaises(ValueError):prepare_conversions(self.values,False)
        scopes=prepare_conversions(self.values,True)
        entry=SimpleNamespace(category='',unit='мин',date=date.today(),category_conversions=scopes)
        conversion=conversion_for(entry,'Упаковка и тара','Бумажные стаканчики','шт')
        self.assertEqual(conversion['resource_units_per_order_unit'],3)
        self.assertEqual(conversion['period_date'],date.today().isoformat())
        self.assertIsNone(conversion_for(entry,'Строительство','Крепёж','шт'))
        self.assertIsNone(conversion_for(entry,'Упаковка и тара','Бумажные стаканчики','упак'))
        scopes[0]['profile_version']-=1
        self.assertIsNone(conversion_for(entry,'Упаковка и тара','Бумажные стаканчики','шт'))

    def test_legacy_generic_capacity_has_no_implicit_permission(self):
        entry=SimpleNamespace(category='',unit='шт',date=date.today(),category_conversions=[])
        self.assertIsNone(conversion_for(entry,'Упаковка и тара','Бумажные стаканчики','шт'))

    def test_partial_release_and_activation_keep_frozen_resource_coefficient(self):
        row=SimpleNamespace(units=10,resource_units=30,resource_conversion={'resource_units_per_order_unit':3})
        self.assertEqual(occupied_units(row),30)
        resize_reservation(row,4)
        self.assertEqual((row.units,occupied_units(row)),(4,12))
        self.assertEqual(occupied_units(SimpleNamespace(units=7)),7)

    def test_reading_old_capability_never_upgrades_version(self):
        details=CapabilityDetails.model_validate({'category_scopes':[{'category_id':'packaging.paper-cups','unit':'шт','profile_version':1}]})
        self.assertEqual(details.category_scopes[0].profile_version,1)


class CompatibilityTests(unittest.TestCase):
    def test_numeric_aliases_unknown_mismatch_and_nested_boolean(self):
        self.assertFalse(equal_value({'v':[True]},{'v':[1]}))
        self.assertTrue(equal_value(12,'12'))
        product=SimpleNamespace(category='Упаковка и тара',subcategory='Бумажные стаканчики',characteristics={'material':'бумага','volume_ml':400})
        need=SimpleNamespace(category=product.category,subcategory=product.subcategory,volume_units=100,characteristics={'материал':' Бумага ','объем':'400 мл'})
        self.assertEqual(compare_specifications(product,need).state,'match')
        need.characteristics['объем']=500
        self.assertEqual(compare_specifications(product,need).state,'mismatch')
        del product.characteristics['volume_ml']
        self.assertEqual(compare_specifications(product,need).state,'unknown')

    def test_versions_and_multiple_are_hard_constraints(self):
        base=dict(category='Упаковка и тара',subcategory='Бумажные стаканчики',characteristics={'unit':'шт'})
        product=SimpleNamespace(**base,category_profile={'category_id':'packaging.paper-cups','profile_version':1})
        need=SimpleNamespace(**base,volume_units=12,category_profile={'category_id':'packaging.paper-cups','profile_version':2})
        self.assertEqual(compare_specifications(product,need).state,'unknown')
        product.category_profile=None;need.category_profile=None
        product.characteristics={'unit':'шт','order_multiple':'2.5'}
        self.assertEqual(compare_specifications(product,need).state,'unknown')
