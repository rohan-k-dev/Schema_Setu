#!/usr/bin/env python3
"""
Phase 5 Eligibility Evaluation Script — CLI runner.

Replays golden test cases against the deterministic engine
and generates a quality report (§288).

Usage:
    python scripts/evaluate_eligibility.py
    python scripts/evaluate_eligibility.py --verbose
"""

import json
import os
import sys
import time

# Fix Windows encoding
sys.stdout.reconfigure(encoding='utf-8', errors='replace')


# Add backend to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

from app.eligibility.evaluator import evaluate_scheme
from app.eligibility.models import RuleStatus, EligibilityStatus, ELIGIBILITY_ENGINE_VERSION
from app.eligibility.validators import generate_rule_quality_report
from app.xai.explainer import explain_for_response


class MockRule:
    """Lightweight rule mock for offline evaluation."""
    def __init__(self, **kwargs):
        self.id = 1
        self.scheme_id = 1
        self.rule_id = kwargs.get("rule_id", "R1")
        self.field_name = kwargs.get("field_name", "state")
        self.operator = kwargs.get("operator", "IN")
        self.value_json = kwargs.get("value_json")
        self.logical_group = kwargs.get("logical_group", "AND")
        self.required = kwargs.get("required", True)
        self.source_text = kwargs.get("source_text")
        self.unit = kwargs.get("unit")
        self.original_value = kwargs.get("original_value")
        self.original_unit = kwargs.get("original_unit")
        self.rule_order = kwargs.get("rule_order", 0)


def run_evaluation():
    verbose = "--verbose" in sys.argv or "-v" in sys.argv

    # Load golden cases
    golden_path = os.path.join(
        os.path.dirname(__file__), "..", "data", "evaluation",
        "eligibility_golden_cases.json"
    )
    golden_path = os.path.normpath(golden_path)

    if not os.path.exists(golden_path):
        print(f"[FAIL] Golden dataset not found: {golden_path}")
        sys.exit(1)

    with open(golden_path, "r") as f:
        cases = json.load(f)

    print(f"═══════════════════════════════════════════════════")
    print(f"  Phase 5 — Eligibility Engine Evaluation")
    print(f"  Engine Version: {ELIGIBILITY_ENGINE_VERSION}")
    print(f"  Golden Cases: {len(cases)}")
    print(f"═══════════════════════════════════════════════════\n")

    passed = 0
    failed = 0
    errors = []
    total_time = 0
    status_counts = {s.value: 0 for s in EligibilityStatus}

    for case in cases:
        test_id = case["test_id"]
        profile = case["profile"]
        rules = [MockRule(**{
            "rule_id": r.get("rule_id", "R1"),
            "field_name": r["field_name"],
            "operator": r["operator"],
            "value_json": r["value_json"],
            "logical_group": r.get("logical_group", "AND"),
            "required": r.get("required", True),
            "source_text": r.get("source_text"),
        }) for r in case["rules"]]

        start = time.time()
        result = evaluate_scheme(
            scheme_id=test_id,
            scheme_name=case.get("description", ""),
            rules=rules,
            profile=profile,
        )
        elapsed = (time.time() - start) * 1000
        total_time += elapsed

        status_counts[result.status.value] += 1

        # Check result
        expected = case["expected_status"]
        actual = result.status.value

        if actual == expected:
            passed += 1
            symbol = "✓"
        else:
            failed += 1
            symbol = "✗"
            errors.append(f"  {test_id}: expected {expected}, got {actual}")

        if verbose:
            print(f"  {symbol} {test_id}: {actual} ({elapsed:.1f}ms)")
            if actual != expected:
                print(f"    EXPECTED: {expected}")

    # Summary
    print(f"\n═══════════════════════════════════════════════════")
    print(f"  RESULTS")
    print(f"═══════════════════════════════════════════════════")
    print(f"  Passed:  {passed}/{len(cases)}")
    print(f"  Failed:  {failed}/{len(cases)}")
    print(f"  Accuracy: {passed/len(cases)*100:.1f}%")
    print(f"  Total time: {total_time:.1f}ms")
    print(f"  Avg per case: {total_time/len(cases):.2f}ms")
    print()
    print(f"  Status Distribution:")
    for status, count in status_counts.items():
        print(f"    {status}: {count}")

    if errors:
        print(f"\n  Failures:")
        for e in errors:
            print(e)

    print()

    if failed > 0:
        print(f"[FAIL] {failed} golden cases failed")
        sys.exit(1)
    else:
        print(f"[OK] All {passed} golden cases passed ✓")


if __name__ == "__main__":
    run_evaluation()
