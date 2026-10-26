"""
Phase 5 Tests — Deterministic Eligibility Engine.

Tests cover:
- All operators (EQ, NEQ, IN, NOT_IN, LT, LTE, GT, GTE, BETWEEN, BOOLEAN, CONTAINS)
- Three-valued logic (AND/OR with PASS/FAIL/UNKNOWN)
- Unknown handling
- Numeric safety
- Field normalization
- Conflict detection
- Evidence generation
- XAI explanations
- Recommendation ranking
- Golden dataset replay (§107)
- Security
"""

import json
import os
import time
from unittest import TestCase
from pydantic import BaseModel
from typing import Optional, Any

from app.eligibility.models import (
    RuleStatus, EligibilityStatus, RuleResult,
    EligibilityResult, ELIGIBILITY_ENGINE_VERSION,
)
from app.eligibility.operators import (
    evaluate_eq, evaluate_neq, evaluate_in, evaluate_not_in,
    evaluate_lt, evaluate_lte, evaluate_gt, evaluate_gte,
    evaluate_between, evaluate_boolean, evaluate_contains,
    evaluate_operator,
)
from app.eligibility.logical import logical_and, logical_or, evaluate_logical_groups
from app.eligibility.normalizer import (
    normalize_state, normalize_crop, normalize_category,
    normalize_gender, safe_parse_numeric, normalize_field_value,
)
from app.eligibility.evaluator import evaluate_rule, evaluate_scheme
from app.eligibility.evidence import build_evidence, build_explanation_items
from app.eligibility.validators import validate_rule, validate_profile_value
from app.xai.explainer import explain, explain_for_response, validate_explanation
from app.xai.templates import generate_summary, generate_template_explanation
from app.recommendation.ranker import rank_results


# ─── Mock rule for testing ────────────────────────────────────

class MockRule:
    """Lightweight mock for EligibilityRuleRow."""
    def __init__(self, rule_id="R1", field_name="state", operator="IN",
                 value_json=None, logical_group="AND", required=True,
                 source_text=None, unit=None, original_value=None,
                 original_unit=None, rule_order=0):
        self.id = 1
        self.scheme_id = 1
        self.rule_id = rule_id
        self.field_name = field_name
        self.operator = operator
        self.value_json = value_json
        self.logical_group = logical_group
        self.required = required
        self.source_text = source_text
        self.unit = unit
        self.original_value = original_value
        self.original_unit = original_unit
        self.rule_order = rule_order


# ═══════════════════════════════════════════════════════════════
# OPERATOR TESTS (§12)
# ═══════════════════════════════════════════════════════════════

class TestEqOperator(TestCase):
    def test_pass(self):
        assert evaluate_eq("karnataka", "karnataka") == RuleStatus.PASS

    def test_fail(self):
        assert evaluate_eq("maharashtra", "karnataka") == RuleStatus.FAIL

    def test_unknown_missing(self):
        assert evaluate_eq(None, "karnataka") == RuleStatus.UNKNOWN


class TestNeqOperator(TestCase):
    def test_pass(self):
        assert evaluate_neq("maharashtra", "karnataka") == RuleStatus.PASS

    def test_fail(self):
        assert evaluate_neq("karnataka", "karnataka") == RuleStatus.FAIL


class TestInOperator(TestCase):
    def test_pass(self):
        assert evaluate_in("karnataka", ["karnataka", "tamil nadu"]) == RuleStatus.PASS

    def test_fail(self):
        assert evaluate_in("maharashtra", ["karnataka", "tamil nadu"]) == RuleStatus.FAIL

    def test_unknown(self):
        assert evaluate_in(None, ["karnataka"]) == RuleStatus.UNKNOWN

    def test_case_insensitive(self):
        assert evaluate_in("KARNATAKA", ["karnataka"]) == RuleStatus.PASS


class TestNotInOperator(TestCase):
    def test_pass(self):
        assert evaluate_not_in("obc", ["sc", "st"]) == RuleStatus.PASS

    def test_fail(self):
        assert evaluate_not_in("general", ["general"]) == RuleStatus.FAIL


class TestLtOperator(TestCase):
    def test_pass(self):
        assert evaluate_lt(3, 5) == RuleStatus.PASS

    def test_fail(self):
        assert evaluate_lt(5, 5) == RuleStatus.FAIL


class TestLteOperator(TestCase):
    def test_pass(self):
        assert evaluate_lte(5, 5) == RuleStatus.PASS

    def test_fail(self):
        assert evaluate_lte(6, 5) == RuleStatus.FAIL

    def test_unknown(self):
        assert evaluate_lte(None, 5) == RuleStatus.UNKNOWN


class TestGtOperator(TestCase):
    def test_pass(self):
        assert evaluate_gt(10, 5) == RuleStatus.PASS

    def test_fail(self):
        assert evaluate_gt(5, 5) == RuleStatus.FAIL


class TestGteOperator(TestCase):
    def test_pass(self):
        assert evaluate_gte(5, 5) == RuleStatus.PASS

    def test_fail(self):
        assert evaluate_gte(4, 5) == RuleStatus.FAIL


class TestBetweenOperator(TestCase):
    def test_pass(self):
        assert evaluate_between(3, [1, 5]) == RuleStatus.PASS

    def test_fail_low(self):
        assert evaluate_between(0, [1, 5]) == RuleStatus.FAIL

    def test_fail_high(self):
        assert evaluate_between(7, [1, 5]) == RuleStatus.FAIL

    def test_malformed(self):
        assert evaluate_between(3, [1]) == RuleStatus.UNKNOWN


class TestBooleanOperator(TestCase):
    def test_pass_true(self):
        assert evaluate_boolean(True, True) == RuleStatus.PASS

    def test_fail(self):
        assert evaluate_boolean(False, True) == RuleStatus.FAIL

    def test_unknown(self):
        assert evaluate_boolean(None, True) == RuleStatus.UNKNOWN


class TestContainsOperator(TestCase):
    def test_pass(self):
        assert evaluate_contains("karnataka farmer", "karnataka") == RuleStatus.PASS

    def test_fail(self):
        assert evaluate_contains("maharashtra farmer", "karnataka") == RuleStatus.FAIL


class TestUnknownOperator(TestCase):
    def test_unknown_operator(self):
        """Unknown operator should return UNKNOWN, not silently pass (§79)."""
        assert evaluate_operator("SOMETHING_UNKNOWN", "value", "value") == RuleStatus.UNKNOWN


# ═══════════════════════════════════════════════════════════════
# THREE-VALUED LOGIC TESTS (§31)
# ═══════════════════════════════════════════════════════════════

class TestLogicalAnd(TestCase):
    def test_all_pass(self):
        assert logical_and([RuleStatus.PASS, RuleStatus.PASS]) == RuleStatus.PASS

    def test_pass_unknown(self):
        assert logical_and([RuleStatus.PASS, RuleStatus.UNKNOWN]) == RuleStatus.UNKNOWN

    def test_pass_fail(self):
        assert logical_and([RuleStatus.PASS, RuleStatus.FAIL]) == RuleStatus.FAIL

    def test_unknown_unknown(self):
        assert logical_and([RuleStatus.UNKNOWN, RuleStatus.UNKNOWN]) == RuleStatus.UNKNOWN

    def test_fail_unknown(self):
        assert logical_and([RuleStatus.FAIL, RuleStatus.UNKNOWN]) == RuleStatus.FAIL

    def test_empty(self):
        assert logical_and([]) == RuleStatus.PASS


class TestLogicalOr(TestCase):
    def test_all_fail(self):
        assert logical_or([RuleStatus.FAIL, RuleStatus.FAIL]) == RuleStatus.FAIL

    def test_pass_fail(self):
        assert logical_or([RuleStatus.PASS, RuleStatus.FAIL]) == RuleStatus.PASS

    def test_pass_unknown(self):
        assert logical_or([RuleStatus.PASS, RuleStatus.UNKNOWN]) == RuleStatus.PASS

    def test_fail_unknown(self):
        assert logical_or([RuleStatus.FAIL, RuleStatus.UNKNOWN]) == RuleStatus.UNKNOWN

    def test_unknown_unknown(self):
        assert logical_or([RuleStatus.UNKNOWN, RuleStatus.UNKNOWN]) == RuleStatus.UNKNOWN


class TestLogicalGroups(TestCase):
    def test_and_group(self):
        results = [
            RuleResult(field="state", operator="IN", status=RuleStatus.PASS, logical_group="AND"),
            RuleResult(field="crop", operator="IN", status=RuleStatus.PASS, logical_group="AND"),
        ]
        assert evaluate_logical_groups(results) == RuleStatus.PASS

    def test_or_group(self):
        results = [
            RuleResult(field="category", operator="IN", status=RuleStatus.FAIL, logical_group="category_or"),
            RuleResult(field="category", operator="IN", status=RuleStatus.PASS, logical_group="category_or"),
        ]
        assert evaluate_logical_groups(results) == RuleStatus.PASS

    def test_mixed_and_or(self):
        """A AND B AND (C OR D) — §29."""
        results = [
            RuleResult(field="state", operator="IN", status=RuleStatus.PASS, logical_group="AND"),
            RuleResult(field="crop", operator="IN", status=RuleStatus.PASS, logical_group="AND"),
            RuleResult(field="category", operator="IN", status=RuleStatus.FAIL, logical_group="category_or"),
            RuleResult(field="category", operator="IN", status=RuleStatus.PASS, logical_group="category_or"),
        ]
        assert evaluate_logical_groups(results) == RuleStatus.PASS


# ═══════════════════════════════════════════════════════════════
# NORMALIZER TESTS (§15)
# ═══════════════════════════════════════════════════════════════

class TestNormalization(TestCase):
    def test_state_alias(self):
        assert normalize_state("KA") == "karnataka"
        assert normalize_state("Karnatak") == "karnataka"

    def test_crop_alias(self):
        assert normalize_crop("finger millet") == "ragi"
        assert normalize_crop("paddy") == "rice"

    def test_category_alias(self):
        assert normalize_category("Scheduled Caste") == "sc"
        assert normalize_category("OBC") == "obc"

    def test_gender(self):
        assert normalize_gender("F") == "female"
        assert normalize_gender("Male") == "male"

    def test_numeric_lakh(self):
        assert safe_parse_numeric("1.5 lakh") == 150000
        assert safe_parse_numeric("₹2,00,000") == 200000

    def test_numeric_negative_invalid(self):
        """Negative values invalid for land/income (§184)."""
        assert safe_parse_numeric(-5) is None

    def test_numeric_string_invalid(self):
        """'a lot' is not a number (§185)."""
        assert safe_parse_numeric("a lot") is None

    def test_boolean_normalization(self):
        assert normalize_field_value("has_aadhaar", "yes") is True
        assert normalize_field_value("has_aadhaar", "no") is False
        assert normalize_field_value("has_aadhaar", None) is None


# ═══════════════════════════════════════════════════════════════
# EVALUATOR TESTS (§13)
# ═══════════════════════════════════════════════════════════════

class TestEvaluateRule(TestCase):
    def test_state_pass(self):
        rule = MockRule(field_name="state", operator="IN", value_json=["Karnataka"])
        result = evaluate_rule(rule, {"state": "Karnataka"})
        assert result.status == RuleStatus.PASS

    def test_state_fail(self):
        rule = MockRule(field_name="state", operator="IN", value_json=["Karnataka"])
        result = evaluate_rule(rule, {"state": "Maharashtra"})
        assert result.status == RuleStatus.FAIL

    def test_state_unknown(self):
        rule = MockRule(field_name="state", operator="IN", value_json=["Karnataka"])
        result = evaluate_rule(rule, {})
        assert result.status == RuleStatus.UNKNOWN

    def test_land_lte_pass(self):
        rule = MockRule(field_name="land_size_acres", operator="LTE", value_json=5)
        result = evaluate_rule(rule, {"land_size_acres": 2})
        assert result.status == RuleStatus.PASS

    def test_land_lte_fail(self):
        rule = MockRule(field_name="land_size_acres", operator="LTE", value_json=5)
        result = evaluate_rule(rule, {"land_size_acres": 10})
        assert result.status == RuleStatus.FAIL

    def test_field_name_mapping(self):
        """Rule uses 'land', profile uses 'land_size_acres' (§78)."""
        rule = MockRule(field_name="land", operator="LTE", value_json=5)
        result = evaluate_rule(rule, {"land_size_acres": 2})
        assert result.status == RuleStatus.PASS


class TestEvaluateScheme(TestCase):
    def test_all_pass_eligible(self):
        rules = [
            MockRule("R1", "state", "IN", ["Karnataka"]),
            MockRule("R2", "land_size_acres", "LTE", 5),
        ]
        result = evaluate_scheme("TEST", "Test Scheme", rules, {"state": "Karnataka", "land_size_acres": 2})
        assert result.status == EligibilityStatus.ELIGIBLE
        assert result.passed_rules == 2
        assert result.failed_rules == 0

    def test_one_fail_not_eligible(self):
        rules = [
            MockRule("R1", "state", "IN", ["Karnataka"]),
            MockRule("R2", "land_size_acres", "LTE", 5),
        ]
        result = evaluate_scheme("TEST", "Test Scheme", rules, {"state": "Karnataka", "land_size_acres": 10})
        assert result.status == EligibilityStatus.NOT_ELIGIBLE
        assert result.failed_rules == 1

    def test_unknown_needs_info(self):
        rules = [
            MockRule("R1", "state", "IN", ["Karnataka"]),
            MockRule("R2", "annual_income", "LTE", 200000),
        ]
        result = evaluate_scheme("TEST", "Test Scheme", rules, {"state": "Karnataka"})
        assert result.status == EligibilityStatus.NEEDS_MORE_INFORMATION
        assert "annual_income" in result.missing_information

    def test_no_rules_unverifiable(self):
        result = evaluate_scheme("TEST", "Test Scheme", [], {"state": "Karnataka"})
        assert result.status == EligibilityStatus.UNVERIFIABLE

    def test_complete_evaluation(self):
        """All rules evaluated even after first FAIL (§70)."""
        rules = [
            MockRule("R1", "state", "IN", ["Karnataka"]),
            MockRule("R2", "land_size_acres", "LTE", 5),
            MockRule("R3", "annual_income", "LTE", 200000),
        ]
        result = evaluate_scheme("TEST", "Test", rules,
                                 {"state": "Maharashtra", "land_size_acres": 10, "annual_income": 150000})
        # All 3 rules evaluated
        assert len(result.rule_results) == 3
        assert result.passed_rules == 1  # income passes
        assert result.failed_rules == 2  # state + land fail

    def test_conflict_detection(self):
        """Contradictory rules → UNVERIFIABLE (§37)."""
        rules = [
            MockRule("R1", "land_size_acres", "LTE", 5),
            MockRule("R2", "land_size_acres", "GTE", 10),
        ]
        result = evaluate_scheme("TEST", "Test", rules, {"land_size_acres": 3})
        assert result.status == EligibilityStatus.UNVERIFIABLE
        assert len(result.conflicts) > 0

    def test_or_group_eligible(self):
        """OR group: SC OR ST — ST passes (§74)."""
        rules = [
            MockRule("R1", "state", "IN", ["Karnataka"]),
            MockRule("R2", "category", "IN", ["SC"], logical_group="category_or"),
            MockRule("R3", "category", "IN", ["ST"], logical_group="category_or"),
        ]
        result = evaluate_scheme("TEST", "Test", rules,
                                 {"state": "Karnataka", "category": "ST"})
        assert result.status == EligibilityStatus.ELIGIBLE

    def test_optional_unknown_doesnt_block(self):
        """Optional rule UNKNOWN doesn't block eligibility (§35)."""
        rules = [
            MockRule("R1", "state", "IN", ["Karnataka"], required=True),
            MockRule("R2", "gender", "EQ", "female", required=False),
        ]
        result = evaluate_scheme("TEST", "Test", rules, {"state": "Karnataka"})
        assert result.status == EligibilityStatus.ELIGIBLE


# ═══════════════════════════════════════════════════════════════
# EVIDENCE TESTS (§46)
# ═══════════════════════════════════════════════════════════════

class TestEvidence(TestCase):
    def test_evidence_categorization(self):
        result = EligibilityResult(
            scheme_id="TEST", status=EligibilityStatus.NOT_ELIGIBLE,
            rule_results=[
                RuleResult(field="state", operator="IN", status=RuleStatus.PASS,
                           user_value="karnataka", required_value=["Karnataka"]),
                RuleResult(field="land_size_acres", operator="LTE", status=RuleStatus.FAIL,
                           user_value=10, required_value=5, source_text="Up to 5 acres"),
            ],
            passed_rules=1, failed_rules=1,
        )
        evidence = build_evidence(result)
        assert len(evidence["matched_criteria"]) == 1
        assert len(evidence["failed_criteria"]) == 1
        assert evidence["failed_criteria"][0]["field"] == "land_size_acres"


# ═══════════════════════════════════════════════════════════════
# XAI TESTS (§48, §57)
# ═══════════════════════════════════════════════════════════════

class TestXAI(TestCase):
    def test_eligible_explanation(self):
        result = EligibilityResult(
            scheme_id="TEST", scheme_name="Test Scheme",
            status=EligibilityStatus.ELIGIBLE,
            rule_results=[
                RuleResult(field="state", operator="IN", status=RuleStatus.PASS,
                           user_value="karnataka", required_value=["Karnataka"]),
            ],
            passed_rules=1,
        )
        explanation = explain(result)
        assert "matches" in explanation.summary.lower()
        assert len(explanation.matched_criteria) == 1

    def test_not_eligible_explanation(self):
        result = EligibilityResult(
            scheme_id="TEST", status=EligibilityStatus.NOT_ELIGIBLE,
            rule_results=[
                RuleResult(field="land_size_acres", operator="LTE", status=RuleStatus.FAIL,
                           user_value=10, required_value=5),
            ],
            failed_rules=1,
        )
        explanation = explain(result)
        assert len(explanation.failed_criteria) == 1

    def test_template_fallback(self):
        text = generate_template_explanation(
            EligibilityStatus.NEEDS_MORE_INFORMATION,
            matched=[{"field": "state", "user_value": "Karnataka"}],
            failed=[],
            missing=[{"field": "annual_income", "required_value": 200000}],
        )
        assert "Annual income" in text
        assert "State" in text

    def test_validation_catches_contradiction(self):
        """XAI validator: explanation must not contradict status (§119)."""
        result = EligibilityResult(
            scheme_id="TEST", status=EligibilityStatus.NOT_ELIGIBLE,
            rule_results=[], failed_rules=1,
        )
        # Good explanation
        assert validate_explanation("Does not match current criteria", result) is True
        # Bad explanation — claims eligible
        assert validate_explanation("You are fully eligible for this scheme", result) is False


# ═══════════════════════════════════════════════════════════════
# RECOMMENDATION TESTS (§59)
# ═══════════════════════════════════════════════════════════════

class TestRanking(TestCase):
    def test_eligible_before_needs_info(self):
        results = [
            EligibilityResult(
                scheme_id="B", scheme_name="B",
                status=EligibilityStatus.NEEDS_MORE_INFORMATION,
                passed_rules=1, unknown_rules=1,
            ),
            EligibilityResult(
                scheme_id="A", scheme_name="A",
                status=EligibilityStatus.ELIGIBLE,
                passed_rules=2,
            ),
        ]
        ranked = rank_results(results)
        assert ranked[0].scheme_id == "A"
        assert ranked[1].scheme_id == "B"

    def test_not_eligible_last(self):
        results = [
            EligibilityResult(scheme_id="C", status=EligibilityStatus.NOT_ELIGIBLE, failed_rules=1),
            EligibilityResult(scheme_id="A", status=EligibilityStatus.ELIGIBLE, passed_rules=2),
            EligibilityResult(scheme_id="B", status=EligibilityStatus.NEEDS_MORE_INFORMATION, passed_rules=1, unknown_rules=1),
        ]
        ranked = rank_results(results)
        assert ranked[0].scheme_id == "A"
        assert ranked[1].scheme_id == "B"
        assert ranked[2].scheme_id == "C"

    def test_no_probability_in_output(self):
        """Score is profile_match_score, NOT eligibility_probability (§61)."""
        results = [
            EligibilityResult(scheme_id="A", status=EligibilityStatus.ELIGIBLE, passed_rules=3),
        ]
        ranked = rank_results(results)
        assert hasattr(ranked[0], "profile_match_score")
        assert not hasattr(ranked[0], "eligibility_probability")


# ═══════════════════════════════════════════════════════════════
# VALIDATOR TESTS (§79, §184)
# ═══════════════════════════════════════════════════════════════

class TestValidators(TestCase):
    def test_unknown_operator(self):
        rule = MockRule(operator="SOMETHING_UNKNOWN")
        issues = validate_rule(rule)
        assert len(issues) > 0
        assert issues[0]["type"] == "UNKNOWN_OPERATOR"

    def test_malformed_between(self):
        rule = MockRule(operator="BETWEEN", value_json=[1])
        issues = validate_rule(rule)
        assert any(i["type"] == "INVALID_BETWEEN" for i in issues)

    def test_negative_land(self):
        is_valid, _ = validate_profile_value("land_size_acres", -5)
        # -5 has safe_parse_numeric returning None, so validation passes (treated as unknown)
        assert is_valid is True


# ═══════════════════════════════════════════════════════════════
# SECURITY TESTS (§132, §220)
# ═══════════════════════════════════════════════════════════════

class TestSecurity(TestCase):
    def test_no_eval_in_operators(self):
        """Operators use typed comparison, never eval() (§132)."""
        import app.eligibility.operators as ops
        source = open(ops.__file__).read()
        assert "eval(" not in source
        assert "exec(" not in source

    def test_no_eval_in_evaluator(self):
        import app.eligibility.evaluator as ev
        source = open(ev.__file__).read()
        assert "eval(" not in source
        assert "exec(" not in source


# ═══════════════════════════════════════════════════════════════
# GOLDEN DATASET REPLAY (§107, §261)
# ═══════════════════════════════════════════════════════════════

class TestGoldenDataset(TestCase):
    """Replay all golden cases and assert exact behavior."""

    @classmethod
    def setUpClass(cls):
        # Navigate from backend/app/tests/ → Scheme_Setu/data/evaluation/
        test_dir = os.path.dirname(os.path.abspath(__file__))
        project_root = os.path.normpath(os.path.join(test_dir, "..", "..", ".."))
        golden_path = os.path.join(
            project_root, "data", "evaluation", "eligibility_golden_cases.json"
        )
        with open(golden_path, "r") as f:
            cls.golden_cases = json.load(f)

    def _run_golden_case(self, case):
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

        result = evaluate_scheme(
            scheme_id=case["test_id"],
            scheme_name=case.get("description", ""),
            rules=rules,
            profile=profile,
        )

        # Assert final status
        self.assertEqual(
            result.status.value, case["expected_status"],
            f"[{case['test_id']}] Expected {case['expected_status']}, got {result.status.value}"
        )

        # Assert individual rule statuses
        expected_rules = case.get("expected_rule_statuses", {})
        actual_rules = {r.rule_id: r.status.value for r in result.rule_results if r.rule_id}
        for rule_id, expected_status in expected_rules.items():
            self.assertIn(rule_id, actual_rules,
                          f"[{case['test_id']}] Missing rule {rule_id}")
            self.assertEqual(
                actual_rules[rule_id], expected_status,
                f"[{case['test_id']}] Rule {rule_id}: expected {expected_status}, got {actual_rules[rule_id]}"
            )

        # Assert missing information
        expected_missing = set(case.get("expected_missing", []))
        actual_missing = set(result.missing_information)
        self.assertEqual(
            expected_missing, actual_missing,
            f"[{case['test_id']}] Missing fields: expected {expected_missing}, got {actual_missing}"
        )

    def test_golden_cases(self):
        """Run ALL golden test cases (§107)."""
        for case in self.golden_cases:
            with self.subTest(test_id=case["test_id"]):
                self._run_golden_case(case)


# ═══════════════════════════════════════════════════════════════
# PERFORMANCE BENCHMARK (§154)
# ═══════════════════════════════════════════════════════════════

class TestPerformance(TestCase):
    def test_single_scheme_latency(self):
        """Single scheme evaluation should be < 10ms."""
        rules = [MockRule(f"R{i}", "state", "IN", ["Karnataka"]) for i in range(10)]
        profile = {"state": "Karnataka"}

        start = time.time()
        for _ in range(100):
            evaluate_scheme("PERF", "Perf Test", rules, profile)
        elapsed = (time.time() - start) / 100

        assert elapsed < 0.01, f"Single scheme evaluation took {elapsed*1000:.1f}ms"

    def test_batch_latency(self):
        """50 scheme evaluation should be < 100ms."""
        rules = [MockRule("R1", "state", "IN", ["Karnataka"])]
        profile = {"state": "Karnataka"}

        start = time.time()
        for _ in range(50):
            evaluate_scheme("PERF", "Perf", rules, profile)
        elapsed = time.time() - start

        assert elapsed < 0.1, f"50 schemes took {elapsed*1000:.0f}ms"


# ═══════════════════════════════════════════════════════════════
# DETERMINISTIC REPRODUCIBILITY (§153)
# ═══════════════════════════════════════════════════════════════

class TestDeterminism(TestCase):
    def test_same_input_same_output(self):
        """Same profile + rules must always produce same result (§153)."""
        rules = [
            MockRule("R1", "state", "IN", ["Karnataka"]),
            MockRule("R2", "land_size_acres", "LTE", 5),
        ]
        profile = {"state": "Karnataka", "land_size_acres": 2}

        results = [
            evaluate_scheme("TEST", "Test", rules, profile)
            for _ in range(10)
        ]

        for r in results:
            assert r.status == results[0].status
            assert r.passed_rules == results[0].passed_rules
            assert r.failed_rules == results[0].failed_rules
