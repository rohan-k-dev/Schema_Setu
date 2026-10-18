"""
Human-in-the-loop evaluation (Phase 7 §73–§78, §111, §191).
"""

import copy
from typing import Any, Dict, List

from evaluation.metrics import summarize_checks
from evaluation.runners.common import check, get_client, rules_from


def _review_key():
    from app.core.config import settings
    return getattr(settings, "REVIEW_API_KEY", None)


def run(corpus_db) -> Dict[str, Any]:
    from app.eligibility.evaluator import evaluate_scheme
    from app.models.review import ReviewReason, ReviewStatus, ReviewAction
    from app.services import review_service as rs

    checks: List[Dict[str, Any]] = []

    # ── §73 escalation triggers from REAL engine outputs ──────────
    no_rules = evaluate_scheme("AGMARKNET", "AGMARKNET", [], {"state": "Karnataka"})
    conflict = evaluate_scheme("CF", "CF", rules_from([
        {"field_name": "land_size_acres", "operator": "LTE", "value_json": 5},
        {"field_name": "land_size_acres", "operator": "GTE", "value_json": 10}]), {"land_size_acres": 3})
    clean = evaluate_scheme("OK", "OK", rules_from([
        {"field_name": "state", "operator": "EQ", "value_json": "karnataka"}]), {"state": "Karnataka"})

    cases = [
        ("ESC_UNVERIFIABLE", [no_rules], [], {}, ReviewReason.UNVERIFIABLE),
        ("ESC_RULE_CONFLICT", [conflict], [], {}, ReviewReason.RULE_CONFLICT),
        ("ESC_SOURCE_CONFLICT", [clean], [{"scheme_id": "PM_KISAN", "field": "benefits"}], {}, ReviewReason.SOURCE_CONFLICT),
        ("ESC_SYSTEM_ERROR", [clean], [], {"database": "down", "knowledge_graph": "down"}, ReviewReason.SYSTEM_ERROR),
        ("ESC_NONE", [clean], [], {}, None),
    ]
    for cid, results, src_conf, errs, expected in cases:
        got = rs.should_escalate(results, src_conf, errs)
        checks.append(check(cid, got == expected, expected=getattr(expected, "value", None),
                            actual=getattr(got, "value", None), area="escalation"))

    # INSUFFICIENT_DATA: no automatic trigger by design; manual creation must work.
    manual = rs.create_review_case("eval-manual", "q", ReviewReason.INSUFFICIENT_DATA, {}, [], [], [])
    checks.append(check("ESC_INSUFFICIENT_DATA_MANUAL", manual.reason == ReviewReason.INSUFFICIENT_DATA,
                        area="escalation"))

    # ── §74 lifecycle ─────────────────────────────────────────────
    profile = {"state": "Karnataka", "aadhaar_number": "1234-5678-9012", "phone_number": "9999999999",
               "bank_account": "0001112223", "has_aadhaar": True}
    c1 = rs.create_review_case("eval-s1", "q", ReviewReason.UNVERIFIABLE, dict(profile), ["AGMARKNET"], [no_rules], [])
    step1 = rs.resolve_case(c1.case_id, ReviewAction.REQUEST_INFORMATION, "rev-1", "need land record")
    status1 = step1.status if step1 else None
    step2 = rs.resolve_case(c1.case_id, ReviewAction.APPROVE, "rev-1", "verified")
    status2 = step2.status if step2 else None
    checks.append(check("LIFECYCLE_PENDING_INREVIEW_RESOLVED",
                        status1 == ReviewStatus.IN_REVIEW and status2 == ReviewStatus.RESOLVED,
                        statuses=[getattr(status1, "value", None), getattr(status2, "value", None)],
                        area="lifecycle"))
    c2 = rs.create_review_case("eval-s2", "q", ReviewReason.UNVERIFIABLE, {}, [], [], [])
    d = rs.dismiss_case(c2.case_id, "rev-1", "duplicate")
    checks.append(check("LIFECYCLE_PENDING_DISMISSED", bool(d) and d.status == ReviewStatus.DISMISSED,
                        area="lifecycle"))

    # ── §75 invalid transitions ───────────────────────────────────
    checks.append(check("INVALID_RESOLVED_TO_DISMISSED", rs.dismiss_case(c1.case_id) is None, area="transitions"))
    checks.append(check("INVALID_DISMISSED_TO_RESOLVED",
                        rs.resolve_case(c2.case_id, ReviewAction.APPROVE) is None, area="transitions"))
    checks.append(check("INVALID_UNKNOWN_CASE", rs.resolve_case("nope", ReviewAction.APPROVE) is None,
                        area="transitions"))

    # ── §76 reviewer actions ──────────────────────────────────────
    for action in ReviewAction:
        c = rs.create_review_case("eval-act", "q", ReviewReason.UNVERIFIABLE, {}, [], [], [])
        if action != ReviewAction.REQUEST_INFORMATION:
            rs.resolve_case(c.case_id, ReviewAction.REQUEST_INFORMATION, "rev-2", "start")
        res = rs.resolve_case(c.case_id, action, "rev-2", f"note {action.value}")
        checks.append(check(f"ACTION_{action.value}", bool(res) and res.reviewer_action == action.value,
                            area="actions"))

    # ── §77 audit ─────────────────────────────────────────────────
    audit = rs.get_audit_log(c1.case_id)
    actions = [e.action for e in audit]
    complete = all(e.case_id and e.action and e.reviewer and e.timestamp for e in audit)
    checks.append(check("AUDIT_TRAIL", actions == ["CREATED", "REQUEST_INFORMATION", "APPROVE"] and complete
                        and audit[-1].note == "verified" and audit[-1].reviewer == "rev-1",
                        actions=actions, area="audit"))

    # ── §78 privacy ───────────────────────────────────────────────
    snap = rs.get_case(c1.case_id).profile_snapshot
    leaked = [k for k in ("aadhaar_number", "phone_number", "bank_account") if k in snap]
    checks.append(check("PRIVACY_SENSITIVE_STRIPPED", not leaked, leaked=leaked, area="privacy"))

    # ── §191 no canonical data mutation ───────────────────────────
    before = copy.deepcopy([r.model_dump() for sid in corpus_db.scheme_ids() for r in corpus_db.rules_for(sid)])
    c3 = rs.create_review_case("eval-mut", "q", ReviewReason.UNVERIFIABLE, {}, ["PM_KISAN"], [], [])
    rs.resolve_case(c3.case_id, ReviewAction.REQUEST_INFORMATION, "rev-3")
    rs.resolve_case(c3.case_id, ReviewAction.REJECT, "rev-3", "rule outdated")
    after = [r.model_dump() for sid in corpus_db.scheme_ids() for r in corpus_db.rules_for(sid)]
    checks.append(check("NO_CANONICAL_MUTATION", before == after, area="audit"))

    # ── §111 API authorization ────────────────────────────────────
    client = get_client()
    from app.core.config import settings
    import app.api.review as review_api
    saved_key = getattr(settings, "REVIEW_API_KEY", None)
    key = saved_key or getattr(review_api, "REVIEW_API_KEY", None)
    if hasattr(settings, "REVIEW_API_KEY") and not saved_key:
        key = "eval-temporary-reviewer-key"  # configured only for this check
        settings.REVIEW_API_KEY = key
    try:
        r_none = client.get("/review-cases")
        r_bad = client.get("/review-cases", headers={"X-Review-Key": "guess-1234"})
        r_ok = client.get("/review-cases", headers={"X-Review-Key": key}) if key else None
    finally:
        if hasattr(settings, "REVIEW_API_KEY"):
            settings.REVIEW_API_KEY = saved_key
    checks.append(check("API_NO_KEY_403", r_none.status_code == 403, got=r_none.status_code, area="auth"))
    checks.append(check("API_WRONG_KEY_403", r_bad.status_code == 403, got=r_bad.status_code, area="auth"))
    checks.append(check("API_VALID_KEY_200", r_ok is not None and r_ok.status_code == 200,
                        got=getattr(r_ok, "status_code", None), area="auth"))
    c4 = rs.create_review_case("eval-auth", "q", ReviewReason.UNVERIFIABLE, {}, [], [], [])
    r_res = client.post(f"/review-cases/{c4.case_id}/resolve", json={"action": "APPROVE"})
    checks.append(check("API_UNAUTHORIZED_RESOLVE_BLOCKED",
                        r_res.status_code == 403 and rs.get_case(c4.case_id).status == ReviewStatus.PENDING,
                        got=r_res.status_code, area="auth"))

    summary = summarize_checks(checks)
    by_area: Dict[str, List[bool]] = {}
    for c in checks:
        by_area.setdefault(c["area"], []).append(c["passed"])
    summary["by_area"] = {a: {"passed": sum(v), "total": len(v)} for a, v in by_area.items()}
    summary["automatic_triggers"] = ["UNVERIFIABLE", "RULE_CONFLICT", "SOURCE_CONFLICT", "SYSTEM_ERROR"]
    summary["manual_only_reasons"] = ["INSUFFICIENT_DATA", "AMBIGUOUS_QUERY", "OTHER"]
    return summary
