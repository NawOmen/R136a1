"""Map JUnit evidence to T01–T46 without treating missing/skipped tests as passed.

The output is an automated slice only. Manual hardware/contest acceptance remains
in NEXT_STEPS.md and must not be inferred from test collection or route existence.
"""
import argparse
import ast
import json
from pathlib import Path
import re
import xml.etree.ElementTree as ET

ROOT=Path(__file__).resolve().parents[1]

def working_leaf_ids():
    # Read the literal catalogue without importing the web service/configuration.
    tree = ast.parse((ROOT / 'services/marketplace/app/assortment.py').read_text())
    value = next(node.value for node in tree.body if isinstance(node, ast.Assign)
                 and any(isinstance(t, ast.Name) and t.id == 'ASSORTMENT' for t in node.targets))
    rows = ast.literal_eval(value)
    return set({(r[2], r[3]): r[0] for r in reversed(rows)}.values())


def test_evidence(paths):
    """Read actual JUnit outcomes; repeated reports never add coverage."""
    evidence=[]
    for path in dict.fromkeys(Path(p).resolve() for p in paths):
        for case in ET.parse(path).iter('testcase'):
            status='failed' if case.find('failure') is not None or case.find('error') is not None else 'skipped' if case.find('skipped') is not None else 'passed'
            evidence.append((path.name,case.attrib.get('classname',''),case.attrib.get('name',''),status))
    return evidence


def build_report(paths):
    matrix=json.loads((ROOT/'docs/operations/acceptance-tests.json').read_text())
    ids=[r['id'] for r in matrix['conditions']]
    assert ids==[f'T{i:02d}' for i in range(1,47)]
    evidence=test_evidence(paths)
    expected={parts[1].strip():parts[3].strip() for line in (ROOT/'NEXT_STEPS.md').read_text().splitlines()
              if line.startswith('| T') and len(parts:=line.split('|'))>=5}
    rows=[]
    for row in matrix['conditions']:
        states=[]
        missing_cases={}
        for node in row['tests']:
            source,name=node.split('::')
            assert re.search(r'(?:async )?def '+re.escape(name)+r'\(', (ROOT/source).read_text()),node
            service=Path(source).parts[1]
            module=Path(source).stem
            cases = {}
            for report, cls, case_name, status in evidence:
                if service in report and module in cls.split('.') and case_name.split('[')[0] == name:
                    cases.setdefault(case_name, set()).add(status)
            if row.get('case_set') == 'working_assortment_leaves':
                required = {f'{name}[{leaf}]' for leaf in working_leaf_ids()}
                missing_cases[node] = sorted(required - cases.keys())
                hits = [status for case in required for status in cases.get(case, set())]
                complete = not missing_cases[node]
            else:
                if row.get('case_set'):
                    raise ValueError('Неизвестный набор параметров приёмки')
                hits = [status for statuses in cases.values() for status in statuses]
                complete = len(cases) >= row.get('minimum_cases', 1)
            states.append('failed' if 'failed' in hits else 'unverified' if not complete or 'skipped' in hits else 'passed')
        state='failed' if 'failed' in states else 'passed' if states and all(s=='passed' for s in states) else 'unverified'
        rows.append({**row,'expected':expected[row['id']],'automated_slice_status':state,
                     **({'missing_cases': missing_cases} if missing_cases else {})})
    return {'format':1,'scope':'Только указанные автоматические инварианты. Не полная приёмка T/этапа.','conditions':rows}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('junit', nargs='*', type=Path)
    args = p.parse_args()
    print(json.dumps(build_report(args.junit), ensure_ascii=False, indent=2))

if __name__=='__main__':main()
