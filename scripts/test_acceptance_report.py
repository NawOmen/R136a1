"""Evidence must identify each required leaf; retries cannot fabricate coverage."""
import importlib.util
from pathlib import Path
import tempfile
import unittest
import xml.etree.ElementTree as ET

spec = importlib.util.spec_from_file_location('acceptance_report', Path(__file__).with_name('acceptance-report.py'))
report = importlib.util.module_from_spec(spec)
spec.loader.exec_module(report)
NAME = 'test_working_leaf_order_report_repeat_and_denials'


class AcceptanceEvidence(unittest.TestCase):
    def evidence(self, directory, cases, filename='marketplace.xml'):
        suite = ET.Element('testsuite')
        for leaf, status in cases:
            case = ET.SubElement(suite, 'testcase', classname='tests.test_stage15_acceptance', name=f'{NAME}[{leaf}]')
            if status != 'passed':
                ET.SubElement(case, 'failure' if status == 'failed' else 'skipped')
        path = Path(directory) / filename
        ET.ElementTree(suite).write(path)
        return path

    def t35(self, paths):
        return next(row for row in report.build_report(paths)['conditions'] if row['id'] == 'T35')

    def test_duplicate_cases_files_and_foreign_ids_cannot_pass(self):
        for cases, copies in [([('box', 'passed')] * 9, 1), ([('box', 'passed')], 9),
                              ([(f'unrelated{i}', 'passed') for i in range(9)], 1)]:
            with self.subTest(cases=cases, copies=copies), tempfile.TemporaryDirectory() as tmp:
                path = self.evidence(tmp, cases)
                result = self.t35([path] * copies)
                self.assertEqual(result['automated_slice_status'], 'unverified')
                self.assertTrue(next(iter(result['missing_cases'].values())))

    def test_all_expected_leaves_across_shards_pass(self):
        leaves = sorted(report.working_leaf_ids())
        with tempfile.TemporaryDirectory() as tmp:
            first = self.evidence(tmp, [(leaf, 'passed') for leaf in leaves[:4]], 'marketplace-1.xml')
            second = self.evidence(tmp, [(leaf, 'passed') for leaf in leaves[4:]], 'marketplace-2.xml')
            self.assertEqual(self.t35([first, second, first])['automated_slice_status'], 'passed')
            self.assertEqual(self.t35([first])['automated_slice_status'], 'unverified')

    def test_failed_or_skipped_required_case_never_passes(self):
        leaves = sorted(report.working_leaf_ids())
        for status, expected in [('failed', 'failed'), ('skipped', 'unverified')]:
            with self.subTest(status=status), tempfile.TemporaryDirectory() as tmp:
                cases = [(leaf, 'passed') for leaf in leaves]
                cases[0] = (leaves[0], status)
                self.assertEqual(self.t35([self.evidence(tmp, cases)])['automated_slice_status'], expected)

    def test_no_evidence_stays_unverified(self):
        self.assertEqual(self.t35([])['automated_slice_status'], 'unverified')


if __name__ == '__main__':
    unittest.main()
