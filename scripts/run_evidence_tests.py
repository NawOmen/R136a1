"""Run pytest and bind its JUnit to unchanged local source; never print env."""
import argparse
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

from contest_evidence import ROOT, source_digest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--service", choices=["scripts", "marketplace", "llm-gateway"], required=True)
    parser.add_argument("--python", required=True)
    parser.add_argument("--junit", type=Path, required=True)
    parser.add_argument("tests", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    tests = args.tests[1:] if args.tests[:1] == ["--"] else args.tests
    before = source_digest(args.service)
    junit = args.junit.resolve()
    # Never annotate stale output after an interrupted/uncollected run.
    if junit.exists():
        raise ValueError("JUnit destination must be new")
    cwd = ROOT if args.service == "scripts" else ROOT / "services" / args.service
    code = subprocess.call([args.python, "-m", "pytest", "-q", *tests, "--junitxml=" + str(junit)], cwd=cwd)
    if source_digest(args.service) != before:
        print("Source changed during proof run; JUnit is unverified", file=sys.stderr)
        return 1
    if not junit.exists():
        return code or 1
    tree = ET.parse(junit)
    tree.getroot().set("evidence-service", args.service)
    tree.getroot().set("evidence-source-digest", before)
    tree.write(junit, encoding="utf-8", xml_declaration=True)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
