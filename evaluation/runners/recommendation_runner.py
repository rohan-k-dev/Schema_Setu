"""
Recommendation ranking evaluation (Phase 7 §48–§50).
"""

import itertools
from typing import Any, Dict, List

from evaluation.metrics import summarize_checks
from evaluation.runners.common import check, rules_from, load_dataset, new_thread, get_client
from evaluation.fixtures.mock_services import offline_environment, ScriptedProfileLLM, FakeWebSearch


def _result(sid, status, passed=0, failed=0, unknown=0):
    from app.eligibility.models import EligibilityResult, EligibilityStatus
    return EligibilityResult(scheme_id=sid, scheme_name=sid, status=EligibilityStatus(status),
                             passed_rules=passed, failed_rules=failed, unknown_rules=unknown)


def run(corpus_db) -> Dict[str, Any]:
    from app.recommendation.ranker import rank_results
    checks: List[Dict[str, Any]] = []

    # §48 status precedence
    base = [_result("U", "UNVERIFIABLE"), _result("N", "NOT_ELIGIBLE", 1, 1),
            _result("I", "NEEDS_MORE_INFORMATION", 1, 0, 1), _result("E", "ELIGIBLE", 2)]
    order = [r.eligibility_status.value for r in rank_results(base)]
    checks.append(check("STATUS_PRECEDENCE",
                        order == ["ELIGIBLE", "NEEDS_MORE_INFORMATION", "NOT_ELIGIBLE", "UNVERIFIABLE"],
                        order=order))

    # §48 within-status: higher profile_match_score first
    within = [_result("A", "NEEDS_MORE_INFORMATION", 1, 0, 3), _result("B", "NEEDS_MORE_INFORMATION", 3, 0, 1)]
    ids = [r.scheme_id for r in rank_results(within)]
    checks.append(check("WITHIN_STATUS_SCORE", ids == ["B", "A"], order=ids))

    # §49 same input set in ANY order → same ranking (ties must be broken deterministically)
    tie_set = [_result("PM_KISAN", "ELIGIBLE", 2), _result("KCC", "ELIGIBLE", 2),
               _result("PMFBY", "ELIGIBLE", 2), _result("AGMARKNET", "UNVERIFIABLE")]
    orders = {tuple(r.scheme_id for r in rank_results(list(p))) for p in itertools.permutations(tie_set)}
    checks.append(check("ORDER_INDEPENDENT_TIES", len(orders) == 1, distinct_orders=len(orders)))
    repeat = {tuple(r.scheme_id for r in rank_results(list(tie_set))) for _ in range(20)}
    checks.append(check("REPEATABLE", len(repeat) == 1))

    # graph evidence (as produced by retrieval_agent: list of dicts) must influence ranking reasons
    ge = [{"scheme_id": "KCC", "evidence": ["state"], "matched_fields": ["state"]}]
    ranked = rank_results([_result("PMFBY", "ELIGIBLE", 2), _result("KCC", "ELIGIBLE", 2)], graph_evidence=ge)
    kcc = [r for r in ranked if r.scheme_id == "KCC"][0]
    checks.append(check("GRAPH_EVIDENCE_USED", "Knowledge graph match" in kcc.rank_reasons,
                        reasons=kcc.rank_reasons))

    # §50 recommendation evidence retained end-to-end
    required = ["eligibility_status", "matched_criteria", "failed_criteria", "missing_criteria",
                "graph_evidence", "rank_reasons", "official_url", "sources"]
    utter = "I am a farmer from Karnataka with 2 acres growing ragi"
    script = ScriptedProfileLLM({utter: {"state": "Karnataka", "land_size_acres": 2,
                                         "primary_crop": "ragi", "occupation": "farmer"}})
    client = get_client()
    with offline_environment(db=corpus_db, profile_llm=script, web=FakeWebSearch([])):
        body = client.post("/chat", json={"message": utter, "thread_id": new_thread("rec")}).json()
    schemes = body.get("schemes") or []
    missing_keys = sorted({k for s in schemes for k in required if k not in s})
    checks.append(check("EVIDENCE_FIELDS_PRESENT", bool(schemes) and not missing_keys,
                        missing_keys=missing_keys, schemes=len(schemes)))
    with_graph = sum(1 for s in schemes if s.get("graph_evidence"))
    checks.append(check("GRAPH_EVIDENCE_IN_RESPONSE", with_graph > 0, schemes_with_graph_evidence=with_graph))

    return summarize_checks(checks)
