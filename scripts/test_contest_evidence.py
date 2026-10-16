"""A green duplicate, partial leaf set or JUnit absence cannot close a criterion."""
import importlib.util
from contextlib import contextmanager
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as ET

spec = importlib.util.spec_from_file_location("contest_evidence", Path(__file__).with_name("contest_evidence.py"))
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
REF = module.CRITERIA[3][2][0]
NAME = REF.split("::")[1]


class EvidenceTests(unittest.TestCase):
    @contextmanager
    def isolated_sources(self):
        # Exercise the real input files without changing the developer checkout.
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for relative in ("scripts", "packages/test-fixtures", "services/marketplace",
                             "services/llm-gateway", ".github/workflows"):
                shutil.copytree(module.ROOT / relative, root / relative,
                                ignore=shutil.ignore_patterns(".venv", "__pycache__", ".pytest_cache", ".env"))
            for _, _, _, documents in module.CRITERIA:
                for relative in documents:
                    destination = root / relative
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(module.ROOT / relative, destination)
            with patch.object(module, "ROOT", root), patch.object(module.acceptance, "ROOT", root):
                yield root

    def bound_junit(self, root, service):
        tree = ET.Element("testsuites", {"evidence-service": service,
                          "evidence-source-digest": module.source_digest(service)})
        suite = ET.SubElement(tree, "testsuite")
        if service == "scripts":
            for ref in module.CRITERIA[0][2]:
                ET.SubElement(suite, "testcase", classname="scripts.test_business_analysis.BusinessAnalysis",
                              name=ref.split("::")[1])
        path = root / (service + ".xml")
        ET.ElementTree(tree).write(path)
        return path

    def evidence(self, names, state="passed", service="marketplace"):
        return [(service + ".xml", "tests.test_stage15_acceptance", n, state) for n in names]

    def test_all_exact_working_leaves_required(self):
        names = [f"{NAME}[{leaf}]" for leaf in module.acceptance.working_leaf_ids()]
        self.assertEqual(module.test_status(REF, self.evidence(names))["status"], "passed")
        self.assertEqual(module.test_status(REF, self.evidence(names[:-1] + [names[0]]))["status"], "unverified")
        self.assertEqual(module.test_status(REF, self.evidence([f"{NAME}[unrelated]"]))["status"], "unverified")

    def test_failure_or_skip_cannot_be_erased_by_green_repeat(self):
        names = [f"{NAME}[{leaf}]" for leaf in module.acceptance.working_leaf_ids()]
        passed = self.evidence(names)
        self.assertEqual(module.test_status(REF, passed + self.evidence(names[:1], "failed"))["status"], "failed")
        self.assertEqual(module.test_status(REF, passed + self.evidence(names[:1], "skipped"))["status"], "unverified")

    def test_other_service_does_not_prove_marketplace(self):
        names = [f"{NAME}[{leaf}]" for leaf in module.acceptance.working_leaf_ids()]
        self.assertEqual(module.test_status(REF, self.evidence(names, service="llm-gateway"))["status"], "unverified")

    def test_missing_junit_does_not_award_points_or_video(self):
        report = module.build_report([])
        self.assertEqual([c["weight"] for c in report["criteria"]], [10, 20, 15, 25, 30])
        self.assertTrue(all(c["automated_slice_status"] == "unverified" for c in report["criteria"]))
        self.assertTrue(all(c["readiness"] == "requires_human_review" for c in report["criteria"]))
        self.assertNotIn("score", report)

    def test_both_privacy_permission_branches_are_required(self):
        ref = module.CRITERIA[2][2][0]
        name = ref.split("::")[1]
        evidence = [("llm-gateway.xml", "tests.test_stage13_review_regressions", f"{name}[True]", "passed")]
        self.assertEqual(module.test_status(ref, evidence)["status"], "unverified")

    def test_stale_or_unbound_junit_does_not_prove_current_source(self):
        for attributes in ('', 'evidence-service="scripts" evidence-source-digest="old"'):
            with tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / "scripts.xml"
                path.write_text(f'<testsuites {attributes}><testsuite><testcase classname="scripts.test_business_analysis.BusinessAnalysis" name="test_corrections_retries_and_losses_are_retained"/></testsuite></testsuites>')
                report = module.build_report([path])
                self.assertFalse(report["junit_provenance"][0]["source_matches"])
                self.assertEqual(report["criteria"][0]["automated_slice_status"], "unverified")

    def test_each_catalogue_input_invalidates_previous_k1_junit(self):
        with self.isolated_sources() as root:
            junit = self.bound_junit(root, "scripts")
            self.assertEqual(module.build_report([junit])["criteria"][0]["automated_slice_status"], "passed")
            for relative in ("services/marketplace/app/category_registry.json",
                             "services/marketplace/unit/fixtures/category_stage01.json",
                             "services/marketplace/app/assortment.py"):
                with self.subTest(input=relative):
                    path = root / relative
                    original = path.read_bytes()
                    try:
                        path.write_bytes(original + b"\n")
                        report = module.build_report([junit])
                        self.assertFalse(report["junit_provenance"][0]["source_matches"])
                        self.assertEqual(report["criteria"][0]["automated_slice_status"], "unverified")
                    finally:
                        path.write_bytes(original)

    def test_service_json_and_dependencies_invalidate_previous_junit(self):
        with self.isolated_sources() as root:
            for service in ("marketplace", "llm-gateway"):
                junit = self.bound_junit(root, service)
                self.assertTrue(module.build_report([junit])["junit_provenance"][0]["source_matches"])
                for relative in ("app/evidence-fixture.json", "tests/evidence-fixture.json",
                                 "unit/fixtures/evidence-fixture.json", "requirements.lock", "pytest.ini"):
                    with self.subTest(service=service, input=relative):
                        path = root / "services" / service / relative
                        original = path.read_bytes() if path.exists() else None
                        try:
                            path.parent.mkdir(parents=True, exist_ok=True)
                            path.write_bytes((original or b"{}") + b"\n")
                            report = module.build_report([junit])
                            self.assertFalse(report["junit_provenance"][0]["source_matches"])
                        finally:
                            if original is None:
                                path.unlink()
                            else:
                                path.write_bytes(original)

    def test_ci_change_invalidates_previous_junit(self):
        with self.isolated_sources() as root:
            junit = self.bound_junit(root, "scripts")
            with (root / ".github/workflows/ci.yml").open("a") as stream:
                stream.write("\n# changed test configuration\n")
            self.assertFalse(module.build_report([junit])["junit_provenance"][0]["source_matches"])

    def test_missing_declared_input_cannot_validate_evidence(self):
        with self.isolated_sources() as root:
            junit = self.bound_junit(root, "scripts")
            (root / "services/marketplace/app/category_registry.json").unlink()
            with self.assertRaises(FileNotFoundError):
                module.build_report([junit])

    def test_private_files_do_not_enter_source_digest(self):
        with self.isolated_sources() as root:
            before = {service: module.source_digest(service) for service in ("scripts", "marketplace", "llm-gateway")}
            for relative in (".env", "services/marketplace/.env", "services/llm-gateway/.env", "client-input.json"):
                (root / relative).write_text("private test fixture, never source evidence")
            self.assertEqual(before, {service: module.source_digest(service) for service in before})
