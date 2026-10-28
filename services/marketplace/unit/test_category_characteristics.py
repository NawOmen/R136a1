"""Technical category rules and v1 compatibility without a running database."""
from datetime import date
import unittest
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from pydantic import ValidationError
from fastapi import HTTPException
from app.category_characteristics import validate_profile_values, characteristic_profile
from app.category_registry import registry_snapshot
from app.schemas import ProductIn, ProductPatch, NeedIn, NeedEditIn, PublishIn
from app.assortment import ASSORTMENT
from app.experience import validate_characteristics


class TechnicalProfileTests(unittest.TestCase):
    def test_every_leaf_has_distinct_applicable_initial_profile(self):
        data = registry_snapshot()
        for group in data['groups']:
            for leaf in group['leaves']:
                profile = characteristic_profile(group['label'],leaf['label'])
                self.assertGreaterEqual(profile['version'],1)
                self.assertIn('unit',profile['fields'])
                self.assertGreater(len(profile['fields']),1)
        self.assertNotIn('volume_ml', characteristic_profile('Товары для бизнеса','Мебель')['fields'])
        self.assertIn('thread', characteristic_profile('Строительство','Крепёж')['fields'])
        self.assertIn('output', characteristic_profile('Услуги производства','Сборка')['fields'])

    def test_generic_dimensions_keep_explicit_text_without_implied_unit(self):
        chars={'dimensions':'120×60×75 см','dimensions_mm':'1200×600×750'}
        product=ProductIn(name='Стол',category='Товары для бизнеса',subcategory='Мебель',characteristics=chars,price_rub=1000,moq_units=1,lead_time_days=1)
        self.assertEqual(product.characteristics,chars)
        data=registry_snapshot()
        self.assertNotIn('dimensions',data['characteristic_fields']['dimensions_mm']['aliases'])
        self.assertNotIn('unit',data['characteristic_fields']['dimensions'])
        self.assertEqual(characteristic_profile('Товары для бизнеса','Мебель')['version'],3)

    def test_seed_values_and_compound_dimensions_remain_valid(self):
        for row in ASSORTMENT:
            with self.subTest(product=row[0]):
                self.assertEqual(validate_profile_values(row[2],row[3],row[5]),[])

    def test_numeric_strings_comma_and_legacy_unit_are_accepted_without_rewrite(self):
        chars = {'material':'картон','объём':'400 мл','volume_ml':'400.0'}
        self.assertEqual(validate_profile_values('Упаковка и тара','Бумажные стаканы',chars),[])
        self.assertEqual(chars['объём'],'400 мл')
        self.assertEqual(validate_profile_values('Строительство','Крепёж',{'length_mm':'40,5'}),[])

    def test_invalid_numeric_types_bounds_and_units_rejected(self):
        for value in [0,-1,True,{},[],None,'NaN','Infinity','сорок','4 кг']:
            with self.subTest(value=value):
                self.assertTrue(validate_profile_values('Строительство','Крепёж',{'length_mm':value}))

    def test_blank_or_nontext_known_values_rejected(self):
        for value in ['', '  ', 5, [], 'x'*501]:
            self.assertTrue(validate_profile_values('Товары для бизнеса','Мебель',{'material':value}))

    def test_alias_conflicts_and_unknown_fields(self):
        self.assertTrue(validate_profile_values('Упаковка и тара','Коробки',{'material':'бумага','материал':'металл'}))
        self.assertTrue(validate_profile_values('Упаковка и тара','Коробки',{'MATERIAL':'бумага','material':'металл'}))
        self.assertEqual(validate_profile_values('Товары для бизнеса','Мебель',{'особый параметр':{'custom':1}}),[])

    def test_product_drafts_and_needs_can_be_incomplete(self):
        self.assertEqual(validate_profile_values('Упаковка и тара','Бумажные стаканы',{}),[])
        self.assertTrue(validate_profile_values('Упаковка и тара','Бумажные стаканы',{},require_product_fields=True))
        self.assertEqual(validate_profile_values('Несуществующая категория','Несуществующий лист',{},require_product_fields=True),[])

    def test_temperature_dependency_and_integer_shelf_life(self):
        self.assertTrue(validate_profile_values('Продукты питания','Замороженная продукция',{'temperature_min_c':-10,'temperature_max_c':-20}))
        self.assertEqual(validate_profile_values('Продукты питания','Замороженная продукция',{'temperature_min_c':-20,'temperature_max_c':-10}),[])
        self.assertTrue(validate_profile_values('Продукты питания','Замороженная продукция',{'temperature_min_c':'-10 °C','temperature_max_c':'-20 °C'}))
        self.assertTrue(validate_profile_values('Продукты питания','Бакалея',{'shelf_life_days':1.5}))

    def test_product_api_schema_and_merged_patch_validate_values(self):
        payload = dict(name='Болт',category='Строительство',subcategory='Крепёж',characteristics={'length_mm':40},price_rub=10,moq_units=1,lead_time_days=1)
        self.assertEqual(ProductIn(**payload).characteristics['length_mm'],40)
        patch_data = ProductPatch(characteristics={'length_mm':-1}).model_dump(exclude_unset=True)
        with self.assertRaises(ValidationError): ProductIn(**{**payload, **patch_data})
        self.assertEqual(ProductIn(**{**payload,'characteristics':{}}).characteristics,{})

    def test_need_create_and_edit_schema_preserve_legacy_value(self):
        payload=dict(company_id=uuid.uuid4(),category='Упаковка и тара',subcategory='Бумажные стаканы',characteristics={'объём':'400 мл'},volume_units=1,deadline_date=date.today())
        self.assertEqual(NeedIn(**payload).characteristics['объём'],'400 мл')
        with self.assertRaises(ValidationError): NeedEditIn(**{**payload,'characteristics':{'volume_ml':False}},expected_revision=1)
        with self.assertRaises(ValidationError): NeedIn(**{**payload,'characteristics':{str(n):'x' for n in range(26)}})

    def test_existing_required_packaging_messages_are_preserved(self):
        errors, warnings = validate_characteristics('Упаковка и тара','Бумажные стаканы',{'цвет':'крафт'},5000)
        self.assertIn('Для упаковки укажите материал',errors)
        self.assertIn('Для бумажных стаканов укажите объём',errors)
        self.assertTrue(warnings)

    def test_same_errors_are_returned_by_existing_validation_service(self):
        errors,_=validate_characteristics('Упаковка и тара','Бумажные стаканы',{'material':'','volume_ml':-1},1)
        self.assertEqual(len(errors),2)


class PublicationGuardTests(unittest.IsolatedAsyncioTestCase):
    async def test_direct_publish_cannot_bypass_required_technical_fields(self):
        from app.api import products
        product = SimpleNamespace(company_id=uuid.uuid4(),category='Упаковка и тара',subcategory='Бумажные стаканы',characteristics={},moq_units=1)
        db=SimpleNamespace(get=AsyncMock(return_value=product),commit=AsyncMock(),execute=AsyncMock(),refresh=AsyncMock())
        with patch.object(products,'require_company_seller',AsyncMock()), patch.object(products,'require_company_admin',AsyncMock()), patch.object(products,'require_verified_seller',AsyncMock()):
            with self.assertRaises(HTTPException) as caught:
                await products.publish_product(uuid.uuid4(),PublishIn(published=True),SimpleNamespace(id=uuid.uuid4()),db)
        self.assertEqual(caught.exception.status_code,422)
        db.commit.assert_not_awaited()

    async def test_published_patch_cannot_remove_required_fields(self):
        from app.api import products
        product=SimpleNamespace(id=uuid.uuid4(),company_id=uuid.uuid4(),name='Стакан',category='Упаковка и тара',subcategory='Бумажные стаканы',characteristics={'material':'картон','volume_ml':400},moq_units=1,price_rub=10,price_tiers=[],lead_time_days=1,stock_units=None,is_published=True)
        db=SimpleNamespace(get=AsyncMock(return_value=product),refresh=AsyncMock(),commit=AsyncMock())
        with patch.object(products,'require_company_seller',AsyncMock()), patch.object(products,'require_company_admin',AsyncMock()), patch.object(products,'lock_company',AsyncMock()), patch.object(products,'company_admission',AsyncMock(return_value=SimpleNamespace(blocking_open=0))):
            with self.assertRaises(HTTPException) as caught:
                await products.update_product(product.id,ProductPatch(characteristics={}),SimpleNamespace(id=uuid.uuid4()),db)
        self.assertEqual(caught.exception.status_code,422)
        self.assertEqual(product.characteristics,{'material':'картон','volume_ml':400})
        db.commit.assert_not_awaited()

    async def test_need_publish_rechecks_existing_draft_values(self):
        from app.api import needs
        from datetime import timedelta
        need=SimpleNamespace(id=uuid.uuid4(),company_id=uuid.uuid4(),category='Строительство',subcategory='Крепёж',characteristics={'length_mm':-1},status='draft',deadline_date=date.today()+timedelta(days=1),valid_until=None)
        db=SimpleNamespace(scalar=AsyncMock(return_value=need),commit=AsyncMock())
        with patch.object(needs,'require_company_buyer',AsyncMock()), patch.object(needs,'require_company_admin',AsyncMock()):
            with self.assertRaises(HTTPException) as caught:
                await needs.publish_need(need.id,SimpleNamespace(id=uuid.uuid4()),db)
        self.assertEqual(caught.exception.status_code,422)
        self.assertEqual(need.status,'draft')
        db.commit.assert_not_awaited()
