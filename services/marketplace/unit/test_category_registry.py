"""Catalogue identity regressions, no database or service dependencies."""
import importlib.util
import json
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[3]


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


registry = load_module("registry_under_test", ROOT / "services/marketplace/app/category_registry.py")
generator = load_module("registry_generator_under_test", ROOT / "scripts/sync_category_registry.py")


class CategoryRegistryTests(unittest.TestCase):
    def test_all_existing_leaves_have_distinct_identity_and_realistic_state(self):
        groups = registry.registry_snapshot()["groups"]
        leaves = [leaf for group in groups for leaf in group["leaves"]]
        self.assertEqual(len(groups), 12)
        self.assertEqual(len(leaves), 47)
        self.assertEqual(len({leaf["id"] for leaf in leaves}), 47)
        self.assertTrue(all(leaf["functional_state"] == "profile_ready" for leaf in leaves))
        self.assertTrue(all("S02.03" in leaf["next_tasks"] and "S15.01" in leaf["next_tasks"] for leaf in leaves))

    def test_every_parent_leaf_pair_resolves_and_legacy_names_are_supported(self):
        for group in registry.registry_snapshot()["groups"]:
            for leaf in group["leaves"]:
                self.assertEqual(registry.resolve_category(group["label"], leaf["label"])["id"], leaf["id"])
        self.assertEqual(registry.resolve_category(" строительство ", " КРЕПЕЖ ")["id"], "construction.fasteners")
        self.assertEqual(registry.resolve_category("Крепёж", None)["id"], "construction.fasteners")

    def test_unknown_parent_leaf_and_cross_branch_are_not_guessed(self):
        for pair in [("Неизвестно", "Крепёж"), ("Строительство", "Металлы"), ("Упаковка и тара", "Выдуманный вид"), ("Строительство", None)]:
            self.assertIsNone(registry.resolve_category(*pair))

    def test_returned_data_cannot_mutate_loaded_registry(self):
        registry.registry_snapshot()["groups"].clear()
        registry.catalogue_tree()["Строительство"].clear()
        registry.resolve_category("Строительство", "Крепёж")["label"] = "Другой вид"
        self.assertEqual(registry.resolve_category("Строительство", "Крепёж")["label"], "Крепёж")

    def test_duplicates_alias_conflicts_and_wrong_parent_fail(self):
        for mutation in ("id", "alias", "parent", "revision", "state"):
            data = registry.registry_snapshot()
            leaf = data["groups"][0]["leaves"][0]
            if mutation == "id":
                leaf["id"] = data["groups"][0]["id"]
            elif mutation == "alias":
                leaf["aliases"] = [data["groups"][0]["leaves"][1]["label"]]
            elif mutation == "parent":
                leaf["parent_id"] = "construction"
            elif mutation == "revision":
                leaf["revision"] = True
            else:
                leaf["admission_state"] = "not_configured"
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                registry.validate_registry(data)

    def test_generated_web_snapshot_contains_same_ids_and_order(self):
        self.assertEqual(generator.TARGET.read_text(encoding="utf-8"), generator.expected_snapshot())
        snapshot = json.loads(generator.expected_snapshot())
        self.assertEqual(snapshot["tree"], registry.catalogue_tree())
        self.assertEqual(snapshot["registry_version"], registry.REGISTRY_VERSION)


if __name__ == "__main__":
    unittest.main()
