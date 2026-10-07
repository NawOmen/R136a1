"""Admission regressions for registry integration; no database access."""
import unittest

from app.category_registry import registry_snapshot
from app.category_admission import evaluate_admission, match_profile


class RegistryAdmissionTests(unittest.TestCase):
    def test_registry_references_actual_admission_profiles(self):
        for group in registry_snapshot()["groups"]:
            for leaf in group["leaves"]:
                with self.subTest(category=leaf["id"]):
                    profile = match_profile(group["label"], leaf["label"])
                    self.assertEqual(profile.key if profile else None, leaf["admission_profile_key"])
                    if profile:
                        self.assertEqual(not profile.supported, leaf["admission_state"] == "unsupported")

    def test_unknown_leaf_cannot_inherit_generic_parent_admission(self):
        for group in registry_snapshot()["groups"]:
            with self.subTest(category=group["id"]):
                result = evaluate_admission(category=group["label"], subcategory="Несуществующая подкатегория", characteristics={}, documents=[])
                self.assertEqual(result.state, "needs_classification")
                self.assertEqual(result.blocking_open, 1)
                self.assertEqual(result.rules_version, "categories-4")

    def test_registered_leaves_keep_existing_admission_behavior(self):
        for group in registry_snapshot()["groups"]:
            for leaf in group["leaves"]:
                with self.subTest(category=leaf["id"]):
                    result = evaluate_admission(category=group["label"], subcategory=leaf["label"], characteristics={}, documents=[])
                    if leaf["admission_state"] == "not_configured":
                        self.assertEqual(result.state, "not_configured")
                        self.assertEqual(result.blocking_open, 0)
                    elif leaf["admission_state"] == "unsupported":
                        self.assertFalse(result.supported)
                        self.assertGreater(result.blocking_open, 0)
                    else:
                        self.assertGreater(result.blocking_open, 0)

    def test_legacy_and_wrong_branch_do_not_get_new_permission(self):
        legacy = evaluate_admission(category="Крепёж", subcategory=None, characteristics={}, documents=[])
        self.assertEqual(legacy.state, "not_configured")
        wrong = evaluate_admission(category="Строительство", subcategory="Металлы", characteristics={}, documents=[])
        self.assertEqual(wrong.blocking_open, 1)
        medicine = evaluate_admission(category="Медицинские изделия", subcategory=None, characteristics={}, documents=[])
        self.assertFalse(medicine.supported)
