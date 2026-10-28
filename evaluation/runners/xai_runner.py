"""
XAI evaluation (Phase 7 §42–§47, §102–§104).

Checks every deterministic explanation against the RuleResult evidence it was
built from, and checks that the explanation validator rejects fabricated
content (status flips, invented thresholds, invented URLs, invented criteria).
"""

import inspect
import re
from typing import Any, Dict, List, Set

from evaluation.metrics import safe_ratio, summarize_checks
from evaluation.runners.common import load_dataset, rules_from, check

URL_RE = re.compile(r"https?://[^\s)\]>\"']+")
NUM_RE = re.compile(r"(?<![\w.])\d+(?:,\d{2,3})*(?:\.\d+)?")


def numbers_in(text: str) -> Set[float]:
    out = set()
    for m in NUM_RE.findall(text or ""):
        try:
            out.add(round(float(m.replace(",", "")), 6))
        except ValueError:
            pass
    return out


def _flatten_numbers(value: Any) -> Set[float]:
    out: Set[float] = set()
    if isinstance(value, bool) or value is None:
        return out
    if isinstance(value, (int, float)):
        out.add(round(float(value), 6))
    elif isinstance(value, (list, tuple)):
        for v in value:
            out |= _flatten_numbers(v)
    elif isinstance(value, str):
        out |= numbers_in(value)
    return out


def evidence_numbers(result) -> Set[float]:
    nums: Set[float] = set()
    for r in result.rule_results:
        nums |= _flatten_numbers(r.user_value)
        nums |= _flatten_numbers(r.required_value)
        nums |= numbers_in(r.source_text or "")
    return nums


def _label(field: str) -> str:
    from app.xai.templates import FIELD_LABELS
    return FIELD_LABELS.get(field, field.replace("_", " ").title())


def _evaluate(case, corpus_db):
    from app.eligibility.evaluator import evaluate_scheme
    if case.get("corpus_scheme_id"):
        sid = case["corpus_scheme_id"]
        rules = corpus_db.rules_for(sid)
        name = sid
    else:
        sid = case["case_id"]
        rules = rules_from(case["rules"])
        name = case.get("scheme_name", sid)
    kwargs = {}
    if case.get("source_url") and "source_url" in inspect.signature(evaluate_scheme).parameters:
        kwargs["source_url"] = case["source_url"]
    return evaluate_scheme(scheme_id=sid, scheme_name=name, rules=rules,
                           profile=case["profile"], **kwargs)


def _probes(case, text: str, result) -> List[Dict[str, str]]:
    status = result.status.value
    probes = []
    if status != "ELIGIBLE":
        probes.append({"type": "claim_eligible", "text": text + "\nYou are eligible for this scheme."})
    else:
        probes.append({"type": "claim_not_eligible", "text": text + "\nYou are not eligible for this scheme."})
    probes.append({"type": "new_threshold", "text": text + "\nMaximum land allowed is 37 acres."})
    probes.append({"type": "new_url", "text": text + "\nSource: https://fabricated-scheme-portal.example.org/apply"})
    evidence_fields = {r.field for r in result.rule_results}
    for f in ("primary_crop", "annual_income", "state", "gender"):
        if f not in evidence_fields:
            probes.append({"type": "new_rule", "text": text + f"\n✓ {_label(f)}: matches the scheme requirement"})
            break
    return probes


def run(corpus_db) -> Dict[str, Any]:
    from app.xai.explainer import explain, explain_for_response, validate_explanation
    from app.xai.templates import generate_summary

    ds = load_dataset("xai_cases.json")
    status_checks, claim_checks, numeric_checks, url_checks, genuine_checks = [], [], [], [], []
    probe_checks: List[Dict[str, Any]] = []
    citations, with_url = 0, 0

    for case in ds["cases"]:
        cid = case["case_id"]
        result = _evaluate(case, corpus_db)
        structured = explain(result)
        text = explain_for_response(result)
        status = result.status.value

        # §46 status consistency
        status_checks.append(check(cid, status == case["expected_status"]
                                   and structured.summary == generate_summary(result.status)
                                   and text.startswith(generate_summary(result.status)),
                                   expected=case["expected_status"], actual=status))

        # §43 supported claims: only fields with evidence may appear as criteria
        evidence_fields = {r.field for r in result.rule_results}
        mentioned_bad = [f for f in case.get("must_not_mention", [])
                         if f"{_label(f)}:".lower() in text.lower() and f not in evidence_fields]
        unsupported = [line for line in text.splitlines()
                       if line[:1] in ("✓", "✗", "○")
                       and not any(_label(f).lower() in line.lower() for f in evidence_fields)]
        claim_checks.append(check(cid, not mentioned_bad and not unsupported,
                                  must_not_mention_found=mentioned_bad, unsupported_lines=unsupported))

        # §44 / §104 numeric grounding
        allowed = evidence_numbers(result) | {round(float(n), 6) for n in case.get("allowed_numbers", [])}
        stray = sorted(numbers_in(text) - allowed)
        numeric_checks.append(check(cid, not stray, stray_numbers=stray))

        # §45 / §103 URL grounding
        urls = set(URL_RE.findall(text))
        for s in structured.sources:
            if s.get("url"):
                urls.add(s["url"])
        allowed_urls = {case["source_url"]} if case.get("source_url") else set()
        invented = sorted(u for u in urls if u not in allowed_urls)
        url_checks.append(check(cid, not invented, invented_urls=invented))
        if case.get("source_url"):
            with_url += 1
            if any(s.get("url") == case["source_url"] for s in structured.sources):
                citations += 1

        # validator accepts genuine explanation
        genuine_checks.append(check(cid, validate_explanation(text, result) is True))

        # §102 fabrication probes must be rejected
        for p in _probes(case, text, result):
            rejected = validate_explanation(p["text"], result) is False
            probe_checks.append(check(f"{cid}:{p['type']}", rejected, probe=p["type"]))

    probe_by_type: Dict[str, List[bool]] = {}
    for p in probe_checks:
        probe_by_type.setdefault(p["probe"], []).append(p["passed"])

    # §47 deterministic fallback: explanations need no LLM at all
    from evaluation.fixtures.mock_services import offline_environment, ScriptedTextLLM
    llm = ScriptedTextLLM("unavailable")
    with offline_environment(text_llm=llm):
        first = ds["cases"][0]
        r1 = _evaluate(first, corpus_db)
        fallback_ok = bool(explain_for_response(r1)) and llm.calls == 0

    return {
        "cases": len(ds["cases"]),
        "status_consistency": summarize_checks(status_checks),
        "supported_claims": summarize_checks(claim_checks),
        "numeric_grounding": summarize_checks(numeric_checks),
        "url_grounding": summarize_checks(url_checks),
        "genuine_explanations_accepted": summarize_checks(genuine_checks),
        "fabrication_probe_rejection": summarize_checks(probe_checks),
        "fabrication_rejection_by_type": {k: {"rejected": sum(v), "total": len(v),
                                              "rate": safe_ratio(sum(v), len(v))}
                                          for k, v in probe_by_type.items()},
        "source_citation": {"cases_with_source_url": with_url, "cited": citations,
                            "rate": safe_ratio(citations, with_url)},
        "deterministic_fallback_without_llm": fallback_ok,
    }
