"""Catalogue coverage is derived from the independent category registry."""
from collections import Counter, defaultdict
from decimal import Decimal
import json
import unittest

from app.assortment import ASSORTMENT
from app.category_admission import evaluate_admission
from app.category_registry import registry_snapshot, resolve_category
from seed_assortment import comparison_assortment, LEGACY_COMPARISON_KEYS


class AssortmentCoverageTests(unittest.TestCase):
    def test_every_supported_leaf_has_two_distinct_specifications(self):
        registry = registry_snapshot()
        expected = {leaf["id"] for group in registry["groups"] for leaf in group["leaves"]
                    if leaf["admission_state"] != "unsupported"}
        specifications = defaultdict(set)
        for row in ASSORTMENT:
            leaf = resolve_category(row[2], row[3])
            specifications[leaf["id"]].add(json.dumps(row[5], sort_keys=True, ensure_ascii=False))
            self.assertEqual(row[1], row[2])
            self.assertGreater(Decimal(str(row[6])), 0)
            self.assertGreaterEqual(row[8] // 2, row[7])
        self.assertEqual(set(specifications), expected)
        self.assertNotIn("medical-hygiene.consumables", specifications)
        self.assertTrue(all(len(values) >= 2 for values in specifications.values()))
        self.assertEqual({row[2] for row in ASSORTMENT}, {group["label"] for group in registry["groups"]})

    def test_second_seller_covers_every_leaf_and_preserves_old_skus(self):
        compared = comparison_assortment()
        self.assertTrue(set(LEGACY_COMPARISON_KEYS).issubset({row[0] for row in compared}))
        self.assertEqual({(row[2], row[3]) for row in compared}, {(row[2], row[3]) for row in ASSORTMENT})
        counts = Counter(row[0] for row in ASSORTMENT)
        self.assertTrue(all(count == 1 for count in counts.values()))
        self.assertEqual(len({row[0] for row in compared}), len(compared))

    def test_expanded_sku_does_not_claim_admission_without_documents(self):
        for row in ASSORTMENT:
            with self.subTest(sku=row[0]):
                report = evaluate_admission(category=row[2], subcategory=row[3], characteristics=row[5],
                                            moq_units=row[7], documents=[])
                self.assertTrue(report.supported)
                self.assertGreater(report.blocking_open, 0)
