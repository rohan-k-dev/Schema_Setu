"""
Profile, completeness, question, context and follow-up evaluation (Phase 7 §11–§20).

Offline: deterministic profile layer through the real /chat route + LangGraph,
with the structured-extraction LLM scripted (see mock_services docstring).
Live (--live): LLM extraction accuracy on profile_cases.json with real Groq.
"""

import os
from typing import Any, Dict, List

from evaluation.metrics import safe_ratio, summarize_checks
from evaluation.runners.common import (
    load_dataset, check, new_thread, get_client, graph_state,
    value_matches, strict_value_matches,
)
from evaluation.fixtures.mock_services import (
    offline_environment, ScriptedProfileLLM, ScriptedTextLLM, FakeWebSearch,
)

QUESTION_KEYWORDS = {
    "state": ["state"],
    "land_size_acres": ["acre", "land"],
    "primary_crop": ["crop", "grow"],
}


def _question_field(reply: str) -> List[str]:
    text = (reply or "").lower()
    return [f for f, kws in QUESTION_KEYWORDS.items() if any(k in text for k in kws)]


def _chat(client, thread, text, language="en"):
    r = client.post("/chat", json={"message": text, "thread_id": thread, "language": language})
    return r.status_code, (r.json() if r.headers.get("content-type", "").startswith("application/json") else {})


def run_offline(corpus_db) -> Dict[str, Any]:
    from app.graph.workflow import kisan_agent
    ds = load_dataset("profile_logic_cases.json")
    client = get_client()
    checks: List[Dict[str, Any]] = []
    by_area: Dict[str, List[bool]] = {}

    for case in ds["cases"]:
        cid, area, exp = case["case_id"], case["area"], case["expect"]
        script = ScriptedProfileLLM()
        failures: List[str] = []

        if "sessions" in case:
            for turns in case["sessions"].values():
                for t in turns:
                    script.add(t["input"], t["extraction"])
            with offline_environment(db=corpus_db, profile_llm=script, web=FakeWebSearch([])):
                threads = {name: new_thread(cid + name) for name in case["sessions"]}
                for name, turns in case["sessions"].items():
                    for t in turns:
                        _chat(client, threads[name], t["input"])
                for name, expected in exp.items():
                    prof = graph_state(threads[name]).get("profile") or {}
                    for f, v in expected.items():
                        if not value_matches(prof.get(f), v):
                            failures.append(f"session {name}: {f}={prof.get(f)!r} expected {v!r}")
            ok = not failures
            checks.append(check(cid, ok, area=area, failures=failures))
            by_area.setdefault(area, []).append(ok)
            continue

        for t in case["turns"]:
            script.add(t["input"], t["extraction"])
        thread = new_thread(cid)
        replies, statuses = [], []
        with offline_environment(db=corpus_db, profile_llm=script, text_llm=ScriptedTextLLM("unavailable"),
                                 web=FakeWebSearch([])):
            if case.get("previous_schemes"):
                kisan_agent.update_state({"configurable": {"thread_id": thread}}, {
                    "profile": {"state": "Karnataka", "land_size_acres": 2, "primary_crop": "ragi"},
                    "response_schemes": [{"scheme_id": s, "name": s} for s in case["previous_schemes"]],
                    "messages": [],
                }, as_node="response_formatter")
            for t in case["turns"]:
                code, body = _chat(client, thread, t["input"])
                if code != 200:
                    failures.append(f"HTTP {code}")
                    break
                replies.append(body.get("reply") or "")
                statuses.append(body.get("status"))
            st = graph_state(thread)

        prof = st.get("profile") or {}
        matcher = strict_value_matches if area == "normalization" else value_matches
        for f, v in exp.get("profile", {}).items():
            if not matcher(prof.get(f), v):
                failures.append(f"profile.{f}={prof.get(f)!r} expected {v!r}")
        for f in exp.get("profile_absent", []):
            if prof.get(f) is not None:
                failures.append(f"profile.{f} should be absent, got {prof.get(f)!r}")
        if "missing_fields" in exp and list(st.get("missing_fields") or []) != exp["missing_fields"]:
            failures.append(f"missing_fields={st.get('missing_fields')} expected {exp['missing_fields']}")
        if "conflict_field" in exp:
            fields = [c.get("field") for c in (st.get("profile_conflicts") or [])]
            if exp["conflict_field"] not in fields:
                failures.append(f"conflict not detected for {exp['conflict_field']} (conflicts={fields})")
        for s in exp.get("reply_contains", []):
            if s not in (replies[-1] if replies else ""):
                failures.append(f"reply missing {s!r}")
        if "response_status" in exp and (statuses[-1] if statuses else None) != exp["response_status"]:
            failures.append(f"status={statuses[-1] if statuses else None} expected {exp['response_status']}")
        if "response_status_in" in exp and (statuses[-1] if statuses else None) not in exp["response_status_in"]:
            failures.append(f"status={statuses[-1] if statuses else None} expected one of {exp['response_status_in']}")
        if "question_field" in exp:
            fields = _question_field(replies[-1] if replies else "")
            if fields != [exp["question_field"]]:
                failures.append(f"question targets {fields}, expected {exp['question_field']} "
                                f"(reply={(replies[-1] if replies else '')[:80]!r})")
        if "question_sequence_fields" in exp:
            seq = [(_question_field(r) or ["?"])[0] if len(_question_field(r)) == 1 else "ambiguous"
                   for r in replies]
            if seq != exp["question_sequence_fields"]:
                failures.append(f"question sequence {seq} expected {exp['question_sequence_fields']}")
            if exp.get("single_question") and any(r.count("?") != 1 for r in replies):
                failures.append("a turn asked zero or several questions")
            if len(set(replies)) != len(replies):
                failures.append("duplicate question asked")
        if "referenced_ordinal" in exp:
            ref = st.get("referenced_scheme_id")
            idx = exp["referenced_ordinal"] - 1
            prev_ids = _first_turn_scheme_ids(case, corpus_db)
            expected_ref = prev_ids[idx] if len(prev_ids) > idx else None
            if not ref or ref != expected_ref:
                failures.append(f"referenced_scheme_id={ref!r} expected {expected_ref!r}")

        ok = not failures
        checks.append(check(cid, ok, area=area, failures=failures))
        by_area.setdefault(area, []).append(ok)

    summary = summarize_checks(checks)
    summary["by_area"] = {a: {"passed": sum(v), "total": len(v), "rate": safe_ratio(sum(v), len(v))}
                          for a, v in by_area.items()}
    return summary


_FIRST_TURN_CACHE: Dict[str, List[str]] = {}


def _first_turn_scheme_ids(case, corpus_db) -> List[str]:
    """Scheme order of the answer the follow-up refers to (re-run of turn 1 in a fresh thread)."""
    key = case["case_id"]
    if key in _FIRST_TURN_CACHE:
        return _FIRST_TURN_CACHE[key]
    t = case["turns"][0]
    script = ScriptedProfileLLM({t["input"]: t["extraction"]})
    client = get_client()
    with offline_environment(db=corpus_db, profile_llm=script, web=FakeWebSearch([])):
        _, body = _chat(client, new_thread(key + "-ref"), t["input"])
    ids = [s.get("scheme_id") for s in (body.get("schemes") or [])]
    _FIRST_TURN_CACHE[key] = ids
    return ids


# ─── Live LLM extraction accuracy (§11–§13) ──────────────────────

def run_live() -> Dict[str, Any]:
    """Requires GROQ_API_KEY. Measures real LLM structured extraction on profile_cases.json."""
    import asyncio
    from app.core.config import settings
    if not settings.GROQ_API_KEY:
        return {"status": "NOT_MEASURED", "reason": "GROQ_API_KEY not configured"}

    from app.agents.prompts.profile_prompt import PROFILE_PROMPT_V1
    from app.services.llm_service import _get_structured_llm
    from app.eligibility.normalizer import normalize_field_value

    cases = load_dataset("profile_cases.json")
    chain = PROFILE_PROMPT_V1 | _get_structured_llm()
    fields = ["state", "district", "land_size_acres", "primary_crop", "annual_income",
              "category", "gender", "has_aadhaar", "occupation"]
    tp = fp = fn = 0
    exact_cases = 0
    hallucinations = 0
    rows = []
    for c in cases:
        try:
            out = asyncio.run(chain.ainvoke({"messages": [("human", c["input"])]}))
            if isinstance(out, dict):            # JSON-mode models return a dict (as in profile_agent)
                from app.models.profile import FarmerProfile
                out = FarmerProfile(**out)
            got = out.model_dump(exclude_none=True) if out else {}
        except Exception as e:
            got = {"_error": repr(e)}
        got.pop("CRITICAL_FIELDS", None)
        expected = c["expected"]
        case_ok = True
        for f in fields:
            g = normalize_field_value(f, got.get(f)) if got.get(f) is not None else None
            e = normalize_field_value(f, expected.get(f)) if expected.get(f) is not None else None
            if e is not None and g is not None and value_matches(g, e):
                tp += 1
            elif e is not None and g is None:
                fn += 1
                case_ok = False
            elif g is not None and (e is None or not value_matches(g, e)):
                fp += 1
                case_ok = False
                if e is None:
                    hallucinations += 1
                else:
                    fn += 1
        exact_cases += int(case_ok)
        rows.append({"id": c["case_id"], "extracted": got, "expected": expected, "exact": case_ok})
    precision = safe_ratio(tp, tp + fp)
    recall = safe_ratio(tp, tp + fn)
    f1 = round(2 * precision * recall / (precision + recall), 4) if precision and recall else None
    return {
        "status": "MEASURED", "cases": len(cases), "field_precision": precision, "field_recall": recall,
        "field_f1": f1, "complete_profile_accuracy": safe_ratio(exact_cases, len(cases)),
        "hallucinated_fields": hallucinations, "rows": rows,
    }
