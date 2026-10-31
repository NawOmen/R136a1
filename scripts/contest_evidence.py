"""S17: link criteria to actual test outcomes without awarding jury points.

Missing/skipped/failed evidence cannot be promoted by another passing repeat.
The report is a technical slice, never a claim of complete contest readiness.
"""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("acceptance_report", Path(__file__).with_name("acceptance-report.py"))
acceptance = importlib.util.module_from_spec(spec)
spec.loader.exec_module(acceptance)

CRITERIA = [
    ("K1", 10, [
        "scripts/test_business_analysis.py::test_all_current_categories_have_exact_profile_and_example_coverage",
        "scripts/test_business_analysis.py::test_full_cost_and_first_use_training_without_waiting_in_labour",
        "scripts/test_business_analysis.py::test_corrections_retries_and_losses_are_retained"],
     ["README.md", "docs/acceptance.md", "docs/business-analysis.md"]),
    ("K2", 20, [
        "services/llm-gateway/tests/test_stage17_trace.py::test_actual_task_trace_denial_recovery_and_artifact",
        "services/marketplace/tests/test_stage12.py::test_role_quality_gates_scoping_and_versions",
        "services/marketplace/tests/test_stage12.py::test_scorecard_empty_denominator_none_and_buyer_access"],
     ["README.md"]),
    ("K3", 15, [
        "services/llm-gateway/tests/test_stage13_review_regressions.py::test_external_boundary_has_only_counters_and_separate_permission",
        "services/marketplace/tests/test_commerce.py::test_control_example_partial_delivery_return_profit_and_privacy",
        "services/marketplace/tests/test_resource_ledger.py::test_concurrent_buyers_cannot_reserve_same_stock"],
     ["README.md"]),
    ("K4", 25, [
        "services/marketplace/tests/test_stage15_acceptance.py::test_working_leaf_order_report_repeat_and_denials",
        "services/marketplace/tests/test_stage5_supplier.py::test_catalog_import_tiers_external_id_diff_and_rollback",
        "services/marketplace/tests/test_stage5_supplier.py::test_unknown_delivery_is_not_zero_and_blocks_select"],
     ["README.md"]),
    ("K5", 30, [], ["docs/contest/Porukam-pitch.pptx", "README.md"]),
]


def source_paths(service):
    """Public test inputs only; missing declared inputs must fail closed."""
    if service not in {"scripts", "marketplace", "llm-gateway"}:
        raise ValueError("Неизвестный источник JUnit")
    paths = set((ROOT / "scripts").glob("*.py"))
    paths.update((ROOT / "packages/test-fixtures").rglob("*.json"))
    # business_analysis.catalogue_analysis and acceptance.working_leaf_ids read
    # these directly, including when the tests run outside the service package.
    paths.update(ROOT / relative for relative in (
        "services/marketplace/app/category_registry.json",
        "services/marketplace/app/assortment.py",
        "services/marketplace/unit/fixtures/category_stage01.json",
        ".github/workflows/ci.yml",
        "docs/acceptance.md",
        "docs/business-analysis.md",
    ))
    runtime = "marketplace" if service == "scripts" else service
    service_root = ROOT / "services" / runtime
    paths.update(service_root / name for name in ("requirements.lock", "requirements.txt", "pytest.ini"))
    if service != "scripts":
        for directory in ("app", "tests", "unit", "alembic"):
            for pattern in ("*.py", "*.json"):
                paths.update((service_root / directory).rglob(pattern))
        paths.update(service_root.glob("alembic.ini"))
    return sorted(paths)


def source_digest(service):
    """Bind JUnit to its inputs and dependency lock, never to .env/private files."""
    digest = hashlib.sha256(f"contest-evidence-source-2\0{service}\0".encode())
    for path in source_paths(service):
        digest.update(str(path.relative_to(ROOT)).encode() + b"\0" + path.read_bytes() + b"\0")
    return digest.hexdigest()


def test_status(ref, evidence):
    source, name = ref.split("::")
    code = (ROOT / source).read_text()
    if not re.search(r"(?:async )?def " + re.escape(name) + r"\(", code):
        raise ValueError("Не найден тест: " + ref)
    module = Path(source).stem
    service = Path(source).parts[1] if source.startswith("services/") else "scripts"
    cases = {}
    for report, cls, case, status in evidence:
        if service in report and module in cls.split(".") and case.split("[")[0] == name:
            cases.setdefault(case, set()).add(status)
    if name == "test_working_leaf_order_report_repeat_and_denials":
        required = {f"{name}[{leaf}]" for leaf in acceptance.working_leaf_ids()}
    elif name == "test_external_boundary_has_only_counters_and_separate_permission":
        required = {f"{name}[False]", f"{name}[True]"}
    else:
        required = set(cases)
    states = {s for case in required for s in cases.get(case, set())}
    missing = sorted(required - cases.keys())
    status = "failed" if "failed" in states else "passed" if required and not missing and states == {"passed"} else "unverified"
    return {"test": ref, "status": status, "cases": len(required & cases.keys()), "missing_cases": missing}


def build_report(paths):
    valid_paths, provenance = [], []
    for path in dict.fromkeys(Path(p).resolve() for p in paths):
        tree = acceptance.ET.parse(path).getroot()
        service = tree.get("evidence-service")
        matches = service in {"scripts", "marketplace", "llm-gateway"} and tree.get("evidence-source-digest") == source_digest(service)
        provenance.append({"report": path.name, "service": service, "source_matches": matches})
        if matches:
            valid_paths.append(path)
    evidence = acceptance.test_evidence(valid_paths)
    criteria = []
    digests = {}
    for key, weight, tests, documents in CRITERIA:
        checks = [test_status(ref, evidence) for ref in tests]
        missing_documents = [path for path in documents if not (ROOT / path).is_file()]
        for path in documents + [ref.split("::")[0] for ref in tests]:
            if path in missing_documents:
                continue
            digests[path] = hashlib.sha256((ROOT / path).read_bytes()).hexdigest()
        states = {c["status"] for c in checks}
        status = "failed" if "failed" in states else "passed" if checks and states == {"passed"} else "unverified"
        if missing_documents and status != "failed":
            status = "unverified"
        criteria.append({"id": key, "weight": weight, "automated_slice_status": status,
                         "checks": checks, "documents": documents, "missing_documents": missing_documents,
                         "readiness": "requires_human_review"})
    return {"schema": "contest-evidence-1", "scope": "Синтетическая программная проверка, не оценка жюри и не полная приёмка критериев.",
            "source_digests": dict(sorted(digests.items())), "criteria": criteria,
            "junit_provenance": provenance,
            "implementation_digests": {s: source_digest(s) for s in ("scripts", "marketplace", "llm-gateway")},
            "working_leaf_ids": sorted(acceptance.working_leaf_ids()),
            "unverified": ["Финальное ревью NeTRUPPER", "Функциональное видео и резерв S18.03–S18.04", "Физические условия S15.03"]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("junit", nargs="*", type=Path)
    parser.add_argument("--require", nargs="*", choices=[c[0] for c in CRITERIA], default=[])
    args = parser.parse_args()
    report = build_report(args.junit)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return int(any(c["id"] in args.require and c["automated_slice_status"] != "passed" for c in report["criteria"]))


if __name__ == "__main__":
    raise SystemExit(main())
