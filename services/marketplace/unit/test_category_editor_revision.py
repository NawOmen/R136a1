import unittest
import uuid
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import AsyncMock,patch
from fastapi import HTTPException
from app.category_registry import registry_snapshot,registry_context
from app.category_profile_snapshot import capture_category_profile
from app.category_profile_revision import revision_preview
from app.api.category_editor import proposed_registry,RulePublicationIn,publish_rules
from app.api.category_profiles import adopt_profile,ProfileAdoptionIn
from app.packaging_conversion import packaging_definition,packaging_equivalent
from app.trust import payload_hash


class CategoryEditorTests(unittest.TestCase):
    def setUp(self):
        self.registry=registry_snapshot()
        self.leaf=self.registry['groups'][0]['leaves'][0]
        self.input=RulePublicationIn(category_id=self.leaf['id'],expected_registry_hash=payload_hash(self.registry),
            technical_profile=deepcopy(self.leaf['technical_profile']),reason='Проверена спецификация новой категории')

    def test_publication_increments_server_version_and_keeps_previous_immutable(self):
        self.input.technical_profile['version']=999
        result=proposed_registry(self.registry,self.input)
        self.assertEqual(result['groups'][0]['leaves'][0]['technical_profile']['version'],self.leaf['technical_profile']['version']+1)
        self.assertEqual(self.registry,registry_snapshot())
        with registry_context(result):
            self.assertEqual(capture_category_profile('Упаковка и тара',self.leaf['label'])['profile_version'],self.leaf['technical_profile']['version']+1)
        self.assertEqual(registry_snapshot(),self.registry)

    def test_editor_cannot_remove_document_review_repeat_guard_or_medical_restriction(self):
        for section,key,value in [('documents','review_required',False),('repeat','copy_approvals',True),('units','allowed',[["шт"]])]:
            data=self.input.model_copy(deep=True)
            data.technical_profile['passport'][section][key]=value
            with self.subTest(section=section),self.assertRaises(HTTPException):proposed_registry(self.registry,data)
        data=self.input.model_copy(deep=True);data.category_id='medical-hygiene.consumables'
        with self.assertRaises(HTTPException) as error:proposed_registry(self.registry,data)
        self.assertEqual(error.exception.status_code,409)

    def test_unrelated_registry_change_is_not_an_update_of_same_leaf(self):
        record=SimpleNamespace(category='Упаковка и тара',subcategory=self.leaf['label'],characteristics={'unit':'шт'},moq_units=100,
                               category_profile=capture_category_profile('Упаковка и тара',self.leaf['label']))
        other=deepcopy(self.registry);other['registry_version']='another-registry-revision'
        with registry_context(other):self.assertEqual(revision_preview(record)['state'],'current')


class AdoptionGuardTests(unittest.IsolatedAsyncioTestCase):
    def record(self):
        return SimpleNamespace(id=uuid.uuid4(),company_id=uuid.uuid4(),category='Упаковка и тара',subcategory='Бумажные стаканы',
            characteristics={'material':'бумага','volume_ml':400,'unit':'шт'},category_profile=None,moq_units=100,is_published=False,quantity_conversion=None)

    async def test_adoption_checks_reviewed_specification_and_never_modifies_active_product(self):
        record=self.record();preview=revision_preview(record)
        self.assertIsNotNone(preview['current'])
        data=ProfileAdoptionIn(approved=True,**{key:preview[key] for key in ['expected_specification_hash','expected_snapshot_hash','expected_current_hash']})
        db=SimpleNamespace(commit=AsyncMock());user=SimpleNamespace(id=uuid.uuid4())
        with patch('app.api.category_profiles.owned_record',AsyncMock(return_value=record)),patch('app.api.category_profiles.require_company_admin',AsyncMock()),patch('app.api.category_profiles.record_human_approval',AsyncMock()) as approval:
            record.characteristics['volume_ml']=500
            with self.assertRaises(HTTPException) as error:await adopt_profile('products',record.id,data,user,db)
            self.assertEqual(error.exception.status_code,409)
            self.assertIsNone(record.category_profile);approval.assert_not_awaited()
            record.characteristics['volume_ml']=400
            record.is_published=True
            with self.assertRaises(HTTPException):await adopt_profile('products',record.id,data,user,db)
            record.is_published=False
            result=await adopt_profile('products',record.id,data,user,db)
            self.assertEqual(result['state'],'current')
            approval.assert_awaited_once();db.commit.assert_awaited_once()
            await adopt_profile('products',record.id,ProfileAdoptionIn(approved=True,**{key:result[key] for key in ['expected_specification_hash','expected_snapshot_hash','expected_current_hash']}),user,db)
            approval.assert_awaited_once()

    async def test_publication_requires_explicit_approval_and_current_hash_after_lock(self):
        registry=registry_snapshot();leaf=registry['groups'][0]['leaves'][0]
        data=RulePublicationIn(category_id=leaf['id'],technical_profile=leaf['technical_profile'],expected_registry_hash='0'*64,reason='Проверено редактором',approved=False)
        db=SimpleNamespace(execute=AsyncMock(),scalar=AsyncMock(return_value=None));user=SimpleNamespace(id=uuid.uuid4())
        with patch('app.api.category_editor.require_category_editor',AsyncMock()):
            with self.assertRaises(HTTPException) as error:await publish_rules(data,user,db)
            self.assertEqual(error.exception.status_code,428);db.execute.assert_not_awaited()
            data.approved=True
            with self.assertRaises(HTTPException) as error:await publish_rules(data,user,db)
            self.assertEqual(error.exception.status_code,409);db.execute.assert_awaited_once()


class PackagingTests(unittest.TestCase):
    def test_only_confirmed_product_specification_can_provide_equivalent(self):
        product=SimpleNamespace(id=uuid.uuid4(),category='Упаковка и тара',subcategory='Бумажные стаканы',
            characteristics={'unit':'упак','material':'бумага','volume_ml':400},category_profile=capture_category_profile('Упаковка и тара','Бумажные стаканы'),quantity_conversion=None)
        with self.assertRaises(ValueError):packaging_equivalent(product,2)
        product.quantity_conversion=packaging_definition(product,'шт',50)
        result=packaging_equivalent(product,2)
        self.assertEqual((result['ordered_quantity'],result['ordered_unit'],result['equivalent_quantity']),(2,'упак',100))
        product.characteristics={**product.characteristics,'volume_ml':500}
        with self.assertRaises(ValueError):packaging_equivalent(product,2)
