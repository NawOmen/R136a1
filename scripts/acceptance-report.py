"""Map JUnit evidence to T01–T46 without treating missing/skipped tests as passed.

The output is an automated slice only. Manual hardware/contest acceptance remains
in NEXT_STEPS.md and must not be inferred from test collection or route existence.
"""
import argparse
import json
from pathlib import Path
import re
import xml.etree.ElementTree as ET

ROOT=Path(__file__).resolve().parents[1]

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('junit',nargs='*',type=Path)
    args=p.parse_args()
    matrix=json.loads((ROOT/'docs/operations/acceptance-tests.json').read_text())
    ids=[r['id'] for r in matrix['conditions']]
    assert ids==[f'T{i:02d}' for i in range(1,47)]
    evidence=[]
    for path in args.junit:
        for case in ET.parse(path).iter('testcase'):
            status='failed' if case.find('failure') is not None or case.find('error') is not None else 'skipped' if case.find('skipped') is not None else 'passed'
            evidence.append((path.name,case.attrib.get('classname',''),case.attrib.get('name',''),status))
    expected={parts[1].strip():parts[3].strip() for line in (ROOT/'NEXT_STEPS.md').read_text().splitlines()
              if line.startswith('| T') and len(parts:=line.split('|'))>=5}
    rows=[]
    for row in matrix['conditions']:
        states=[]
        for node in row['tests']:
            source,name=node.split('::')
            assert re.search(r'(?:async )?def '+re.escape(name)+r'\(', (ROOT/source).read_text()),node
            service=Path(source).parts[1]
            module=Path(source).stem
            hits=[status for report,cls,n,status in evidence if service in report and module in cls.split('.') and n.split('[')[0]==name]
            states.append('failed' if 'failed' in hits else 'unverified' if len(hits)<row.get('minimum_cases',1) or 'skipped' in hits else 'passed')
        state='failed' if 'failed' in states else 'passed' if states and all(s=='passed' for s in states) else 'unverified'
        rows.append({**row,'expected':expected[row['id']],'automated_slice_status':state})
    print(json.dumps({'format':1,'scope':'Только указанные автоматические инварианты. Не полная приёмка T/этапа.','conditions':rows},ensure_ascii=False,indent=2))

if __name__=='__main__':main()
