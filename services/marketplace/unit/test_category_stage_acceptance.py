"""Stage 01 profiles and guards for every offered leaf, not S15 end-to-end acceptance."""
import json
import unittest
import uuid
from datetime import date,datetime,timedelta,timezone
from pathlib import Path
from types import SimpleNamespace
from app.category_registry import registry_snapshot,validate_registry,resolve_category
from app.category_characteristics import validate_profile_values
from app.category_compatibility import compare_specifications
from app.category_admission import evaluate_admission,match_profile
from app.models import Document
from app.category_profile_snapshot import capture_category_profile
from app.assortment import ASSORTMENT

FIXTURES=json.loads(Path(__file__).with_name('fixtures').joinpath('category_stage01.json').read_text())


class Stage01AcceptanceTests(unittest.TestCase):
    def test_fixture_covers_exactly_every_offered_leaf(self):
        data=registry_snapshot(); validate_registry(data)
        leaves={leaf['id'] for group in data['groups'] for leaf in group['leaves']}
        self.assertEqual(leaves,{item['category_id'] for item in FIXTURES})
        self.assertEqual(len(leaves),len(FIXTURES))

    def test_subject_identification_positive_negative_unknown_and_document_guard(self):
        for item in FIXTURES:
            with self.subTest(category_id=item['category_id']):
                self.assertFalse(validate_profile_values(item['category'],item['subcategory'],item['positive'],require_product_fields=True))
                snapshot=capture_category_profile(item['category'],item['subcategory'])
                product=SimpleNamespace(category=item['category'],subcategory=item['subcategory'],characteristics=item['positive'],category_profile=snapshot)
                need=SimpleNamespace(category=item['category'],subcategory=item['subcategory'],characteristics=dict(item['positive']),category_profile=snapshot,volume_units=100)
                self.assertEqual(compare_specifications(product,need).state,'match')
                need.characteristics=item['negative']
                self.assertEqual(compare_specifications(product,need).state,'mismatch')
                missing=dict(item['positive']);del missing[item['missing_field']]
                self.assertTrue(validate_profile_values(item['category'],item['subcategory'],missing,require_product_fields=True))
                product.characteristics=missing;need.characteristics=item['positive']
                self.assertEqual(compare_specifications(product,need).state,'unknown')
                admission=evaluate_admission(category=item['category'],subcategory=item['subcategory'],characteristics=item['positive'],documents=[],moq_units=100)
                self.assertGreater(admission.blocking_open,0)
                self.assertEqual(admission.supported,item['admission_without_documents']!='unsupported')
                if item['admission_without_documents']!='unsupported':
                    profile=match_profile(item['category'],item['subcategory'],item['positive'])
                    documents=[Document(id=uuid.uuid4(),company_id=uuid.uuid4(),name='Синтетическое доказательство для теста',
                        document_type=requirement.document_types[0],file_key='synthetic/local-only',content_type='text/plain',
                        verification_status='verified',scope_category=item['category'],scope_subcategory=item['subcategory'],
                        valid_until=date.today()+timedelta(days=1),verified_by_user_id=uuid.uuid4(),verified_at=datetime.now(timezone.utc),
                        confirms={key:[str(value)] for key,value in item['positive'].items()}) for requirement in profile.requirements]
                    proven=evaluate_admission(category=item['category'],subcategory=item['subcategory'],characteristics=item['positive'],documents=documents,moq_units=100)
                    self.assertEqual(proven.blocking_open,0)
                    for document in documents:document.verification_status='rejected'
                    revoked=evaluate_admission(category=item['category'],subcategory=item['subcategory'],characteristics=item['positive'],documents=documents,moq_units=100)
                    self.assertGreater(revoked.blocking_open,0)
                self.assertEqual(set(item['route']),{'seller','sku','need','match','offer','approval','resource','execution','report','repeat'})
                root=Path(__file__).resolve().parents[3] / 'apps/web/app'
                for route in item['route'].values():
                    self.assertTrue((root / route.lstrip('/').replace('{id}','[id]') / 'page.tsx').exists(), route)
                self.assertIn('S15.01',item['remaining_acceptance_tasks'])

    def test_existing_synthetic_assortment_has_complete_subject_specifications(self):
        for row in ASSORTMENT:
            with self.subTest(sku=row[0]):
                self.assertIsNotNone(resolve_category(row[2],row[3]))
                self.assertFalse(validate_profile_values(row[2],row[3],row[5],require_product_fields=True))

    def test_conditional_properties_do_not_confuse_bolts_washers_and_bulk_mixtures(self):
        washer={'material':'сталь','product_kind':'шайба','standard':'СИН-Ш01','diameter_mm':16,'inner_diameter_mm':8,'thickness_mm':1.5}
        self.assertFalse(validate_profile_values('Строительство','Крепёж',washer,require_product_fields=True))
        del washer['inner_diameter_mm']
        self.assertTrue(validate_profile_values('Строительство','Крепёж',washer,require_product_fields=True))
        mix={'material':'цементная смесь','product_kind':'сухая смесь','purpose':'кладка','composition':'СИН-С01','unit':'мешок'}
        self.assertFalse(validate_profile_values('Строительство','Отделочные материалы',mix,require_product_fields=True))
