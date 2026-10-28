"""
Eligibility engine evaluation (Phase 7 §29–§41, §51–§54).

Fully deterministic — no external services.
"""

import inspect
from collections import Counter, defaultdict
from typing import Any, Dict, List

from evaluation.metrics import safe_ratio, summarize_checks
from evaluation.runners.common import (
    load_dataset, load_legacy, rules_from, check, DatasetRule,
)

STATUSES = ["ELIGIBLE", "NOT_ELIGIBLE", "NEEDS_MORE_INFORMATION", "UNVERIFIABLE"]


def _evaluate(scheme_id, rules, profile, source_url=None):
    from app.eligibility.evaluator import evaluate_scheme
    kwargs = {}
    if source_url and "source_url" in inspect.signature(evaluate_scheme).parameters:
        kwargs["source_url"] = source_url
    return evaluate_scheme(scheme_id=scheme_id, scheme_name=scheme_id, rules=rules,
                           profile=profile, **kwargs)


def _operator_probes() -> List[Dict[str, Any]]:
    """PASS / FAIL / UNKNOWN probe for every operator the engine implements (§29)."""
    from app.eligibility.operators import OPERATOR_MAP
    from app.eligibility.models import RuleStatus

    probes = {
        "EQ": [("karnataka", "karnataka", "PASS"), ("kerala", "karnataka", "FAIL"), (None, "karnataka", "UNKNOWN")],
        "NEQ": [("kerala", "karnataka", "PASS"), ("karnataka", "karnataka", "FAIL"), (None, "karnataka", "UNKNOWN")],
        "IN": [("sc", ["sc", "st"], "PASS"), ("obc", ["sc", "st"], "FAIL"), (None, ["sc"], "UNKNOWN")],
        "NOT_IN": [("obc", ["sc", "st"], "PASS"), ("sc", ["sc", "st"], "FAIL"), (None, ["sc"], "UNKNOWN")],
        "LT": [(3, 5, "PASS"), (5, 5, "FAIL"), (None, 5, "UNKNOWN")],
        "LTE": [(5, 5, "PASS"), (6, 5, "FAIL"), (None, 5, "UNKNOWN")],
        "GT": [(6, 5, "PASS"), (5, 5, "FAIL"), (None, 5, "UNKNOWN")],
        "GTE": [(5, 5, "PASS"), (4, 5, "FAIL"), (None, 5, "UNKNOWN")],
        "BETWEEN": [(3, [1, 5], "PASS"), (7, [1, 5], "FAIL"), (None, [1, 5], "UNKNOWN")],
        "CONTAINS": [("small farmer", "farmer", "PASS"), ("trader", "farmer", "FAIL"), (None, "farmer", "UNKNOWN")],
        "BOOLEAN": [(True, True, "PASS"), (False, True, "FAIL"), (None, True, "UNKNOWN")],
    }
    out = []
    for op in sorted(OPERATOR_MAP):
        for user, rule, expected in probes.get(op, []):
            got = OPERATOR_MAP[op](user, rule).value
            out.append(check(f"op:{op}:{expected}", got == expected, operator=op,
                             user=user, rule=rule, expected=expected, actual=got))
    # Unknown operator must never pass (§79)
    from app.eligibility.operators import evaluate_operator
    got = evaluate_operator("REGEX_MATCH", "x", "x").value
    out.append(check("op:UNKNOWN_OPERATOR", got == RuleStatus.UNKNOWN.value,
                     operator="REGEX_MATCH", expected="UNKNOWN", actual=got))
    return out


def _truth_table(ds) -> List[Dict[str, Any]]:
    from app.eligibility.logical import logical_and, logical_or
    from app.eligibility.models import RuleStatus
    out = []
    for i, row in enumerate(ds["truth_table"]):
        inputs = [RuleStatus(s) for s in row["inputs"]]
        fn = logical_and if row["op"] == "AND" else logical_or
        got = fn(inputs).value
        out.append(check(f"tv:{row['op']}:{'_'.join(row['inputs'])}", got == row["expected"],
                         expected=row["expected"], actual=got))
    return out


def _scheme_cases(corpus_db) -> List[Dict[str, Any]]:
    """All scheme-level golden cases: (case_id, source, rules, profile, expected, url)."""
    cases = []
    for c in load_dataset("eligibility_cases.json"):
        cases.append((c["case_id"], "eligibility_v1", rules_from(c["rules"]), c["profile"],
                      c["expected_status"], None, c.get("expected_rule_statuses")))
    for c in load_legacy("eligibility_golden_cases.json"):
        cases.append((c["test_id"], "phase5_golden", rules_from(c["rules"]), c["profile"],
                      c["expected_status"], None, c.get("expected_rule_statuses")))
    for c in load_dataset("corpus_eligibility_cases.json")["cases"]:
        sid = c["scheme_id"]
        cases.append((c["case_id"], "corpus_eligibility_v1", corpus_db.rules_for(sid), c["profile"],
                      c["expected_status"], corpus_db.official_url(sid), None))
    for c in load_dataset("eligibility_logic_cases.json")["nested_cases"]:
        cases.append((c["case_id"], "eligibility_logic_v1", rules_from(c["rules"]), c["profile"],
                      c["expected_status"], None, None))
    return cases


def run(corpus_db) -> Dict[str, Any]:
    from app.eligibility.models import ELIGIBILITY_ENGINE_VERSION

    logic = load_dataset("eligibility_logic_cases.json")

    # ── scheme-level + rule-level accuracy (§30, §31) ──────────────
    scheme_checks, rule_checks = [], []
    confusion = defaultdict(Counter)
    by_dataset = defaultdict(lambda: [0, 0])
    for cid, src, rules, profile, expected, url, exp_rules in _scheme_cases(corpus_db):
        res = _evaluate(cid, rules, profile, url)
        actual = res.status.value
        confusion[expected][actual] += 1
        ok = actual == expected
        by_dataset[src][0] += int(ok)
        by_dataset[src][1] += 1
        scheme_checks.append(check(cid, ok, dataset=src, expected=expected, actual=actual))
        if exp_rules:
            got = {r.rule_id: r.status.value for r in res.rule_results}
            for rid, exp in exp_rules.items():
                rule_checks.append(check(f"{cid}:{rid}", got.get(rid) == exp,
                                         expected=exp, actual=got.get(rid)))

    total = sum(sum(v.values()) for v in confusion.values())
    fp = confusion["NOT_ELIGIBLE"]["ELIGIBLE"]
    fn = confusion["ELIGIBLE"]["NOT_ELIGIBLE"]
    gold_not_eligible = sum(confusion["NOT_ELIGIBLE"].values())
    gold_eligible = sum(confusion["ELIGIBLE"].values())
    any_false_eligible = sum(confusion[g]["ELIGIBLE"] for g in STATUSES if g != "ELIGIBLE")

    # ── three-valued + nested logic (§32, §33) ────────────────────
    tv_checks = _truth_table(logic)

    # ── missing info → re-evaluation (§34, §41) ───────────────────
    m = logic["missing_info_case"]
    before = _evaluate("M01", rules_from(m["rules"]), m["profile_before"]).status.value
    after = _evaluate("M01", rules_from(m["rules"]), m["profile_after"]).status.value
    reeval = check("M01", before == m["expected_before"] and after == m["expected_after"],
                   before=before, after=after)

    # ── conflicting rules (§38) ───────────────────────────────────
    cf = logic["conflict_case"]
    cf_statuses = [_evaluate("CF01", rules_from(cf["rules"]), p).status.value for p in cf["profiles"]]
    conflict = check("CF01", all(s == cf["expected_status"] for s in cf_statuses), actual=cf_statuses)

    # ── rule source / provenance (§39) ────────────────────────────
    prov_checks = []
    for sid in corpus_db.scheme_ids():
        rules = corpus_db.rules_for(sid)
        if not rules:
            continue
        url = corpus_db.official_url(sid)
        res = _evaluate(sid, rules, {"state": "Karnataka"}, url)
        for i, r in enumerate(res.rule_results):
            prov_checks.append(check(
                f"{sid}:rule{i}",
                bool(r.source_text) and res.scheme_id == sid and bool(res.corpus_version)
                and (url is None or r.source_url == url),
                has_source_text=bool(r.source_text), source_url=r.source_url,
                expected_url=url, corpus_version=res.corpus_version))

    # ── version / determinism (§40) ───────────────────────────────
    det_checks = []
    for cid, src, rules, profile, expected, url, _ in _scheme_cases(corpus_db)[:40]:
        a = _evaluate(cid, rules, profile, url).model_dump()
        b = _evaluate(cid, rules, profile, url).model_dump()
        det_checks.append(check(cid, a == b and a["engine_version"] == ELIGIBILITY_ENGINE_VERSION))

    # ── UNKNOWN / UNVERIFIABLE rates over the real corpus (§53, §54) ──
    rates = unknown_breakdown(corpus_db)

    sc = summarize_checks(scheme_checks)
    return {
        "engine_version": ELIGIBILITY_ENGINE_VERSION,
        "operator_coverage": summarize_checks(_operator_probes()),
        "scheme_level": {
            "cases": sc["total"], "correct": sc["passed"], "accuracy": sc["pass_rate"],
            "by_dataset": {k: {"correct": v[0], "total": v[1], "accuracy": safe_ratio(v[0], v[1])}
                           for k, v in by_dataset.items()},
            "failures": sc["failures"],
        },
        "rule_level": summarize_checks(rule_checks),
        "confusion_matrix": {g: dict(confusion[g]) for g in STATUSES},
        "false_positive": {"count": fp, "gold_not_eligible": gold_not_eligible,
                           "rate": safe_ratio(fp, gold_not_eligible),
                           "any_false_eligible_count": any_false_eligible},
        "false_negative": {"count": fn, "gold_eligible": gold_eligible,
                           "rate": safe_ratio(fn, gold_eligible)},
        "three_valued_logic": summarize_checks(tv_checks),
        "re_evaluation": reeval,
        "conflicting_rules": conflict,
        "rule_provenance": summarize_checks(prov_checks),
        "determinism": summarize_checks(det_checks),
        "corpus_status_rates": rates,
        "dataset_sizes": {k: v[1] for k, v in by_dataset.items()},
    }


REFERENCE_PROFILES = [
    {"state": "Karnataka", "land_size_acres": 2, "primary_crop": "ragi", "occupation": "farmer", "age": 34, "gender": "male", "category": "General"},
    {"state": "Maharashtra", "land_size_acres": 6, "primary_crop": "cotton", "occupation": "farmer", "age": 45, "gender": "female", "category": "OBC"},
    {"state": "Assam", "land_size_acres": 1, "primary_crop": "rice", "occupation": "farmer", "age": 28, "gender": "female", "category": "ST"},
    {"state": "Uttar Pradesh", "land_size_acres": 0, "primary_crop": "wheat", "occupation": "farmer", "age": 52, "gender": "male", "category": "SC"},
    {"state": "Andhra Pradesh", "land_size_acres": 4, "primary_crop": "groundnut", "occupation": "farmer", "age": 39, "gender": "male", "category": "General"},
]


def unknown_breakdown(corpus_db) -> Dict[str, Any]:
    """
    Evaluate every corpus scheme against fully-stated reference profiles and
    classify each NEEDS_MORE_INFORMATION by root cause (§53):
      - missing_user_information: field exists in FarmerProfile but user did not state it
      - unsupported_profile_field: rule field that FarmerProfile cannot hold (parser/data gap)
    Profiles are first passed through FarmerProfile so fields the model drops are dropped.
    """
    from app.models.profile import FarmerProfile
    from app.eligibility.evaluator import _resolve_field_name

    supported = set(FarmerProfile.model_fields.keys()) - {"CRITICAL_FIELDS"}
    status_counter = Counter()
    cause_counter = Counter()
    unsupported_fields = Counter()
    unverifiable_schemes = set()
    evaluations = 0
    for prof in REFERENCE_PROFILES:
        try:
            canonical = FarmerProfile(**prof).model_dump(exclude_none=True)
        except Exception:
            canonical = {}
        canonical.pop("CRITICAL_FIELDS", None)
        for sid in corpus_db.scheme_ids():
            res = _evaluate(sid, corpus_db.rules_for(sid), canonical, corpus_db.official_url(sid))
            evaluations += 1
            status_counter[res.status.value] += 1
            if res.status.value == "UNVERIFIABLE":
                unverifiable_schemes.add(sid)
            if res.status.value == "NEEDS_MORE_INFORMATION":
                for f in res.missing_information:
                    canon = _resolve_field_name(f)
                    if canon == "has_land" and canonical.get("land_size_acres") is not None:
                        cause_counter["derivation_gap"] += 1
                        unsupported_fields[canon] += 1
                    elif canon in supported:
                        cause_counter["missing_user_information"] += 1
                    else:
                        cause_counter["unsupported_profile_field"] += 1
                        unsupported_fields[canon] += 1
    no_rule_schemes = [sid for sid in corpus_db.scheme_ids() if not corpus_db.rules_for(sid)]
    return {
        "evaluations": evaluations,
        "reference_profiles": len(REFERENCE_PROFILES),
        "status_distribution": dict(status_counter),
        "needs_more_information_rate": safe_ratio(status_counter["NEEDS_MORE_INFORMATION"], evaluations),
        "unverifiable_rate": safe_ratio(status_counter["UNVERIFIABLE"], evaluations),
        "unknown_causes": dict(cause_counter),
        "unsupported_fields": dict(unsupported_fields),
        "schemes_without_structured_rules": len(no_rule_schemes),
        "unverifiable_schemes": sorted(unverifiable_schemes),
        "profile_fields_supported": sorted(supported),
    }
