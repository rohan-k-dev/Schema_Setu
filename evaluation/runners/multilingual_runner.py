"""
Multilingual evaluation (Phase 7 §55–§61).

Offline: Sarvam Translate is replaced by a lookup table, so these results
measure LANGUAGE INVARIANCE of the pipeline — not translation quality.
"""

from typing import Any, Dict, List

from evaluation.metrics import summarize_checks
from evaluation.runners.common import load_dataset, check, new_thread, get_client, graph_state, value_matches
from evaluation.fixtures.mock_services import (
    offline_environment, ScriptedProfileLLM, FakeTranslator, FakeWebSearch,
)


def _observe(client, corpus_db, language, text, meaning, extraction, translator_fail=""):
    script = ScriptedProfileLLM({meaning: extraction})
    translator = FakeTranslator({text: meaning} if text != meaning else {}, fail=translator_fail)
    thread = new_thread(f"ml-{language}")
    with offline_environment(db=corpus_db, profile_llm=script, translator=translator, web=FakeWebSearch([])):
        r = client.post("/chat", json={"message": text, "thread_id": thread, "language": language})
    body = r.json()
    schemes = body.get("schemes") or []
    prof = {k: v for k, v in (body.get("current_profile") or {}).items() if v is not None}
    prof.pop("CRITICAL_FIELDS", None)
    evidence = {s["scheme_id"]: (s.get("eligibility_status"),
                                 [c.get("field") for c in s.get("matched_criteria") or []],
                                 [c.get("field") for c in s.get("failed_criteria") or []],
                                 [c.get("field") for c in s.get("missing_criteria") or []])
                for s in schemes}
    return {"http": r.status_code, "status": body.get("status"), "profile": prof,
            "candidates": [s["scheme_id"] for s in schemes], "evidence": evidence,
            "reply": body.get("reply") or "", "translator_calls": translator.calls,
            "schemes": schemes}


def run(corpus_db) -> Dict[str, Any]:
    from app.localization.languages import LANGUAGE_REGISTRY, get_sarvam_code
    ds = load_dataset("multilingual_cases.json")
    client = get_client()
    groups = ds["parity_groups"]

    obs = {}
    for case in ds["cases"]:
        g = groups[case["group"]]
        obs[case["case_id"]] = (case, _observe(client, corpus_db, case["language"], case["input"],
                                                g["meaning"], g["extraction"]))

    # English reference per group (same meaning, no translation)
    refs = {}
    for gid, g in groups.items():
        refs[gid] = _observe(client, corpus_db, "en", g["meaning"], g["meaning"], g["extraction"])

    profile_checks, candidate_checks, status_checks, xai_checks, presentation_checks, numeric_checks = \
        [], [], [], [], [], []
    for cid, (case, o) in obs.items():
        ref = refs[case["group"]]
        lang = case["language"]
        profile_checks.append(check(cid, o["profile"] == ref["profile"], language=lang,
                                    profile=o["profile"], reference=ref["profile"]))
        candidate_checks.append(check(cid, o["candidates"] == ref["candidates"], language=lang))
        status_checks.append(check(cid, {k: v[0] for k, v in o["evidence"].items()}
                                   == {k: v[0] for k, v in ref["evidence"].items()}, language=lang))
        xai_checks.append(check(cid, o["evidence"] == ref["evidence"], language=lang))
        # translation is presentation-only: only the user text and the reply are ever translated
        sent = [c["text"] for c in o["translator_calls"]]
        allowed = {case["input"], ref["reply"], o["reply"]}
        structured_leak = [t for t in sent if t not in allowed]
        reply_translated = lang == "en" or any(c["target"] == get_sarvam_code(lang)
                                               for c in o["translator_calls"])
        presentation_checks.append(check(cid, not structured_leak and reply_translated and o["http"] == 200,
                                         language=lang, unexpected_translation_inputs=len(structured_leak)))
        for f, v in groups[case["group"]]["extraction"].items():
            if isinstance(v, (int, float)) and not isinstance(v, bool):
                numeric_checks.append(check(f"{cid}:{f}", value_matches(o["profile"].get(f), v),
                                            language=lang, got=o["profile"].get(f), expected=v))

    # failure cases (§69)
    failure_checks = []
    for fc in ds["failure_cases"]:
        g = groups["G1"]
        o = _observe(client, corpus_db, fc["language"], fc["input"], g["meaning"], g["extraction"],
                     translator_fail=fc["translator"])
        if fc["translator"] == "fail_both":
            ok = o["http"] == 200 and o["status"] != "error" and not o["candidates"]
        else:
            ref = refs["G1"]
            ok = (o["http"] == 200 and o["candidates"] == ref["candidates"]
                  and o["evidence"] == ref["evidence"] and o["reply"] == ref["reply"])
        failure_checks.append(check(fc["case_id"], ok, mode=fc["translator"], status=o["status"],
                                    candidates=len(o["candidates"])))

    # language support matrix (§55)
    g1_by_lang = {obs[c][0]["language"]: obs[c] for c in obs if obs[c][0]["group"] == "G1"}
    parity_by_lang = {}
    for c in profile_checks:
        lang = c["language"]
        parity_by_lang.setdefault(lang, []).append(c["passed"])
    for c in status_checks + xai_checks:
        parity_by_lang.setdefault(c["language"], []).append(c["passed"])
    matrix = []
    for code, cfg in LANGUAGE_REGISTRY.items():
        tested = code in g1_by_lang or code == "en"
        parity = parity_by_lang.get(code, [])
        matrix.append({
            "language": cfg.english_name, "code": code,
            "declared_translation": cfg.translation_support.value,
            "declared_asr": cfg.asr_support.value, "declared_tts": cfg.tts_support.value,
            "text_input_pipeline_offline": "PASS" if parity and all(parity) else ("FAIL" if parity else "NOT_TESTED"),
            "eligibility_parity_offline": "PASS" if parity and all(parity) else ("FAIL" if parity else "NOT_TESTED"),
            "xai_evidence_parity_offline": "PASS" if parity and all(parity) else ("FAIL" if parity else "NOT_TESTED"),
            "live_translation_quality": "NOT_MEASURED",
            "live_asr": "NOT_MEASURED", "live_tts": "NOT_MEASURED",
            "tested_offline": tested,
        })

    return {
        "cases": len(ds["cases"]) + len(ds["failure_cases"]),
        "languages_tested_offline": sorted({c[0]["language"] for c in obs.values()}),
        "profile_parity": summarize_checks(profile_checks),
        "candidate_parity": summarize_checks(candidate_checks),
        "eligibility_parity": summarize_checks(status_checks),
        "xai_evidence_parity": summarize_checks(xai_checks),
        "translation_presentation_only": summarize_checks(presentation_checks),
        "numeric_preservation": summarize_checks(numeric_checks),
        "translation_failure": summarize_checks(failure_checks),
        "language_matrix": matrix,
        "note": "Offline parity uses mocked translation; Sarvam translation quality is NOT_MEASURED without --live.",
    }
