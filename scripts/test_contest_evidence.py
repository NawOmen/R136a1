"""A green duplicate, partial leaf set or JUnit absence cannot close a criterion."""
import importlib.util
from pathlib import Path
import tempfile
import unittest

spec = importlib.util.spec_from_file_location("contest_evidence", Path(__file__).with_name("contest_evidence.py"))
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
REF = module.CRITERIA[3][2][0]
NAME = REF.split("::")[1]


class EvidenceTests(unittest.TestCase):
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
