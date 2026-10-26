"""
Report generation: results.json, summary.md, scorecard, before/after.

Every scorecard value is read from runner output. Nothing is estimated:
missing values become NOT_MEASURED.
"""

import json
import os
from typing import Any, Dict, List, Optional

from evaluation import REPORTS_DIR

# (category, metric, json-path, target, comparator, evidence)
# comparator: ">=" / "<=" / "==" / "info"
SCORECARD_SPEC = [
    ("Profile", "Deterministic profile-layer scenarios pass rate", "profile.pass_rate", 1.0, ">=", "profile_logic_cases.json"),
    ("Profile", "LLM extraction field F1 (live)", "live_profile_extraction.field_f1", 0.9, ">=", "profile_cases.json (--live)"),
    ("Retrieval", "Merged targeted recall@10", "retrieval.merged.mean_targeted_recall_at_k", 0.9, ">=", "retrieval_cases.json"),
    ("Retrieval", "Merged precision@10 (applicable schemes)", "retrieval.merged.mean_precision_at_k", 1.0, ">=", "retrieval_cases.json"),
    ("Retrieval", "DB targeted recall@10", "retrieval.database.mean_targeted_recall_at_k", 0.9, ">=", "retrieval_cases.json"),
    ("Retrieval", "Graph false relationships (out-of-scope schemes)", "retrieval.knowledge_graph.exclusion_violations", 0, "<=", "retrieval_cases.json"),
    ("Retrieval", "Graph crop-filter accuracy", "retrieval.knowledge_graph.crop_filter_accuracy", 1.0, ">=", "retrieval_cases.json"),
    ("Retrieval", "Exact lookup / adversarial query pass rate", "retrieval.lookups.pass_rate", 1.0, ">=", "retrieval_cases.json"),
    ("Retrieval", "Candidate merge correctness", "retrieval.merge.pass_rate", 1.0, ">=", "retrieval_cases.json"),
    ("Retrieval", "Source-conflict handling", "retrieval.source_conflicts.pass_rate", 1.0, ">=", "retrieval_cases.json"),
    ("Retrieval", "Failure matrix (6 combinations)", "retrieval.failure_matrix.pass_rate", 1.0, ">=", "retrieval_cases.json"),
    ("Retrieval", "Tavily pipeline (URL kept, official linked, unrelated dropped)", "retrieval.tavily_pipeline.pass_rate", 1.0, ">=", "retrieval_cases.json"),
    ("Retrieval", "Parallel retrieval (2s+1s+3s mocked) seconds", "retrieval.parallel.measured_s", 4.0, "<=", "parallel benchmark"),
    ("Eligibility", "Scheme-level accuracy", "eligibility.scheme_level.accuracy", 1.0, ">=", "4 eligibility datasets"),
    ("Eligibility", "Rule-level accuracy", "eligibility.rule_level.pass_rate", 1.0, ">=", "phase5 golden"),
    ("Eligibility", "False-positive rate (ELIGIBLE when gold NOT_ELIGIBLE)", "eligibility.false_positive.rate", 0.0, "<=", "4 eligibility datasets"),
    ("Eligibility", "False-negative rate", "eligibility.false_negative.rate", 0.0, "<=", "4 eligibility datasets"),
    ("Eligibility", "Operator coverage probes", "eligibility.operator_coverage.pass_rate", 1.0, ">=", "11 operators + unknown"),
    ("Eligibility", "Three-valued logic truth table", "eligibility.three_valued_logic.pass_rate", 1.0, ">=", "eligibility_logic_cases.json"),
    ("Eligibility", "Rule provenance (source text + URL + version)", "eligibility.rule_provenance.pass_rate", 1.0, ">=", "corpus rules"),
    ("Eligibility", "Determinism (same input -> same result)", "eligibility.determinism.pass_rate", 1.0, ">=", "40 cases x2"),
    ("Eligibility", "UNKNOWNs caused by unsupported profile fields", "eligibility.corpus_status_rates.unknown_causes.unsupported_profile_field", 0, "info", "reference profiles x 40 schemes"),
    ("Eligibility", "NEEDS_MORE_INFORMATION rate (fully stated profiles)", "eligibility.corpus_status_rates.needs_more_information_rate", None, "info", "reference profiles x 40 schemes"),
    ("Eligibility", "UNVERIFIABLE rate (corpus rule coverage)", "eligibility.corpus_status_rates.unverifiable_rate", None, "info", "reference profiles x 40 schemes"),
    ("XAI", "Status consistency", "xai.status_consistency.pass_rate", 1.0, ">=", "xai_cases.json"),
    ("XAI", "Supported-claim grounding", "xai.supported_claims.pass_rate", 1.0, ">=", "xai_cases.json"),
    ("XAI", "Numeric grounding", "xai.numeric_grounding.pass_rate", 1.0, ">=", "xai_cases.json"),
    ("XAI", "URL grounding", "xai.url_grounding.pass_rate", 1.0, ">=", "xai_cases.json"),
    ("XAI", "Genuine explanations accepted by validator", "xai.genuine_explanations_accepted.pass_rate", 1.0, ">=", "xai_cases.json"),
    ("XAI", "Fabrication probes rejected", "xai.fabrication_probe_rejection.pass_rate", 1.0, ">=", "xai_cases.json"),
    ("XAI", "Official source cited when available", "xai.source_citation.rate", 1.0, ">=", "xai_cases.json"),
    ("Recommendation", "Ranking checks", "recommendation.pass_rate", 1.0, ">=", "recommendation_runner"),
    ("Multilingual", "Profile parity across languages (offline)", "multilingual.profile_parity.pass_rate", 1.0, ">=", "multilingual_cases.json"),
    ("Multilingual", "Eligibility parity across languages (offline)", "multilingual.eligibility_parity.pass_rate", 1.0, ">=", "multilingual_cases.json"),
    ("Multilingual", "XAI evidence parity (offline)", "multilingual.xai_evidence_parity.pass_rate", 1.0, ">=", "multilingual_cases.json"),
    ("Multilingual", "Translation is presentation-only", "multilingual.translation_presentation_only.pass_rate", 1.0, ">=", "multilingual_cases.json"),
    ("Multilingual", "Translation-failure fallback", "multilingual.translation_failure.pass_rate", 1.0, ">=", "multilingual_cases.json"),
    ("Multilingual", "Live Sarvam translation quality", "live_translation.score", None, ">=", "--live (not implemented offline)"),
    ("Voice", "Post-ASR pipeline (mocked ASR)", "voice.post_asr_pipeline.pass_rate", 1.0, ">=", "voice_cases.json"),
    ("Voice", "Voice/text session continuity", "voice.session_continuity.pass_rate", 1.0, ">=", "voice_cases.json"),
    ("Voice", "Failure fallbacks + upload security", "voice.failures_and_upload_security.pass_rate", 1.0, ">=", "voice_cases.json"),
    ("Voice", "Word error rate (real audio)", "voice.wer_value", None, "<=", "no ground-truth audio"),
    ("Human Review", "HITL checks (escalation, lifecycle, audit, privacy, auth)", "human_review.pass_rate", 1.0, ">=", "review_runner"),
    ("Security", "Red-team probes passed", "adversarial.pass_rate", 1.0, ">=", "adversarial_cases.json"),
    ("End-to-end", "Golden journeys passed", "e2e.pass_rate", 1.0, ">=", "e2e_cases.json"),
    ("Performance", "Offline text request P95 (ms, external services mocked)", "performance.text_request.p95_ms", 2000, "<=", "performance_runner"),
    ("Performance", "Offline voice round trip P95 (ms, mocked ASR/TTS)", "performance.voice_round_trip.p95_ms", 3000, "<=", "performance_runner"),
    ("Performance", "Review-II live latency target 10-15 s", "live_performance.latency.p95_ms", 15000, "<=", "--live"),
    ("Performance", "Concurrent load error rate (200 req, c=10)", "performance.load_concurrent.error_rate", 0.0, "<=", "performance_runner"),
    ("Performance", "Concurrent load P95 (ms)", "performance.load_concurrent.latency.p95_ms", 5000, "<=", "performance_runner"),
    ("Stability", "Graph reloads during run", "performance.graph_reloads_during_run", 0, "<=", "performance_runner"),
    ("Stability", "RSS growth over last 100 requests at session cap (KB)", "performance.memory.rss_growth_kb_last_100_requests", 10240, "<=", "performance_runner"),
    ("Stability", "Soak test errors", "performance.soak.errors", 0, "<=", "--soak-seconds"),
    ("Accessibility", "Static accessibility audit checks", "accessibility.pass_rate", 1.0, ">=", "accessibility_runner"),
    ("User Study", "Task completion rate", "user_study.task_completion_rate", None, ">=", "data/evaluation/user_study/"),
    ("Expert Validation", "Outputs rated CORRECT", "expert_validation.correct_rate", None, ">=", "data/evaluation/expert_validation/"),
]


def get_path(d: Dict[str, Any], path: str) -> Any:
    cur: Any = d
    for part in path.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return None
        cur = cur[part]
    return cur


def _status(actual, target, comp) -> str:
    if actual is None:
        return "NOT_MEASURED"
    if comp == "info" or target is None:
        return "INFO"
    try:
        a, t = float(actual), float(target)
    except (TypeError, ValueError):
        return "INFO"
    if comp == ">=":
        if a >= t:
            return "PASS"
        return "PARTIAL" if a >= 0.8 * t and t > 0 else "FAIL"
    if comp == "<=":
        if a <= t:
            return "PASS"
        return "PARTIAL" if t > 0 and a <= 1.5 * t else "FAIL"
    return "PASS" if a == t else "FAIL"


def build_scorecard(results: Dict[str, Any]) -> List[Dict[str, Any]]:
    rows = []
    for cat, metric, path, target, comp, evidence in SCORECARD_SPEC:
        actual = get_path(results, path)
        rows.append({"category": cat, "metric": metric, "target": target if comp != "info" else "info",
                     "comparator": comp, "actual": actual, "status": _status(actual, target, comp),
                     "evidence": evidence, "path": path})
    return rows


def _fmt(v):
    if v is None:
        return "—"
    if isinstance(v, float):
        return f"{v:.4g}"
    return str(v)


def write_reports(label: str, manifest: Dict[str, Any], results: Dict[str, Any]) -> str:
    out = os.path.join(REPORTS_DIR, label)
    os.makedirs(out, exist_ok=True)
    scorecard = build_scorecard(results)
    with open(os.path.join(out, "results.json"), "w", encoding="utf-8") as f:
        json.dump({"label": label, "manifest": manifest, "results": results, "scorecard": scorecard},
                  f, indent=2, ensure_ascii=False, default=str)

    lines = [f"# SchemeSetu evaluation — {label}", "",
             f"- Generated: {manifest['generated_at']}",
             f"- Mode: {manifest['mode']}",
             f"- App {manifest['application_version']} · corpus {manifest['corpus_version']} · "
             f"graph {manifest['graph_version']} · engine {manifest['eligibility_engine_version']}",
             f"- Commit: {manifest.get('git_commit')} (dirty working tree: {manifest.get('git_working_tree_dirty')})",
             "", "## Scorecard", "",
             "| Category | Metric | Target | Actual | Status |", "|---|---|---|---|---|"]
    for r in scorecard:
        tgt = r["target"] if r["target"] == "info" else f"{r['comparator']} {_fmt(r['target'])}"
        lines.append(f"| {r['category']} | {r['metric']} | {tgt} | {_fmt(r['actual'])} | {r['status']} |")
    counts: Dict[str, int] = {}
    for r in scorecard:
        counts[r["status"]] = counts.get(r["status"], 0) + 1
    lines += ["", "Status counts: " + ", ".join(f"{k}={v}" for k, v in sorted(counts.items())), "",
              "## Failing checks (first 15 per area)", ""]
    for area, res in results.items():
        if not isinstance(res, dict):
            continue
        fails = _collect_failures(res)
        if fails:
            lines.append(f"### {area}")
            for f_ in fails[:15]:
                detail = {k: v for k, v in f_.items() if k not in ("id", "passed")}
                lines.append(f"- `{f_.get('id')}` — {json.dumps(detail, ensure_ascii=False, default=str)[:300]}")
            lines.append("")
    with open(os.path.join(out, "summary.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    return out


def _collect_failures(res: Dict[str, Any]) -> List[Dict[str, Any]]:
    fails = []
    if isinstance(res.get("failures"), list):
        fails += res["failures"]
    for v in res.values():
        if isinstance(v, dict) and isinstance(v.get("failures"), list):
            fails += v["failures"]
    return fails


def load_run(label: str) -> Dict[str, Any]:
    with open(os.path.join(REPORTS_DIR, label, "results.json"), encoding="utf-8") as f:
        return json.load(f)


def compare_runs(before: str, after: str) -> str:
    b, a = load_run(before), load_run(after)
    rows = []
    for rb, ra in zip(b["scorecard"], a["scorecard"]):
        change = None
        if isinstance(rb["actual"], (int, float)) and isinstance(ra["actual"], (int, float)):
            change = round(ra["actual"] - rb["actual"], 4)
        rows.append({"category": rb["category"], "metric": rb["metric"], "before": rb["actual"],
                     "after": ra["actual"], "change": change,
                     "status_before": rb["status"], "status_after": ra["status"]})
    out = os.path.join(REPORTS_DIR, "before_after.json")
    with open(out, "w", encoding="utf-8") as f:
        json.dump({"before_label": before, "after_label": after,
                   "before_generated_at": b["manifest"]["generated_at"],
                   "after_generated_at": a["manifest"]["generated_at"], "metrics": rows},
                  f, indent=2, ensure_ascii=False, default=str)
    return out
