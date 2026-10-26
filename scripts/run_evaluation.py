"""
SchemeSetu Phase 7 — master evaluation script.

Usage (from the Scheme_Setu/ directory):
    python scripts/run_evaluation.py --offline                 # deterministic, no API keys needed
    python scripts/run_evaluation.py --offline --label after   # name the run
    python scripts/run_evaluation.py --live                    # adds live Groq/Tavily/Sarvam measurements
    python scripts/run_evaluation.py --offline --soak-seconds 600
    python scripts/run_evaluation.py --compare before after    # writes before_after.json

Outputs (data/evaluation/reports/<label>/):
    results.json          raw results of every runner
    summary.md            human-readable summary
and data/evaluation/evaluation_manifest.json.

Offline mode mocks every external service (see evaluation/fixtures/). Results
that require live services are reported as NOT_MEASURED, never estimated.
"""

import argparse
import json
import logging
import os
import platform
import subprocess
import sys
import time
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import evaluation  # noqa: E402  (sets up backend import path)
from evaluation import REPORTS_DIR, DATA_EVAL_DIR, DATASETS_DIR  # noqa: E402

EVALUATION_VERSION = "phase7-eval-1.0.0"


def _git_commit():
    try:
        return subprocess.check_output(["git", "-C", ROOT, "rev-parse", "--short", "HEAD"],
                                       stderr=subprocess.DEVNULL, text=True).strip()
    except Exception:
        return None


def _git_dirty():
    try:
        out = subprocess.check_output(["git", "-C", ROOT, "status", "--porcelain"],
                                      stderr=subprocess.DEVNULL, text=True)
        return bool(out.strip())
    except Exception:
        return None


def _dataset_counts():
    counts = {}
    for name in sorted(os.listdir(DATASETS_DIR)):
        if not name.endswith(".json"):
            continue
        with open(os.path.join(DATASETS_DIR, name), encoding="utf-8") as f:
            d = json.load(f)
        if isinstance(d, list):
            # list-format datasets: version bumps are recorded per case in label_history
            versions = [h["dataset_version"] for c in d for h in c.get("label_history", [])]
            version = max(versions) if versions else name.replace("_cases.json", "") + "_v1"
            counts[name] = {"version": version, "count": len(d)}
        else:
            n = 0
            for k in ("cases", "profile_cases", "lookup_cases", "merge_cases", "conflict_cases",
                      "failure_matrix", "pipeline_cases", "session_cases", "failure_cases",
                      "truth_table", "nested_cases"):
                if isinstance(d.get(k), list):
                    n += len(d[k])
            counts[name] = {"version": d.get("version"), "count": n}
    for legacy in ("eligibility_golden_cases.json", "multilingual_cases.json", "human_review_cases.json"):
        p = os.path.join(DATA_EVAL_DIR, legacy)
        if os.path.exists(p):
            with open(p, encoding="utf-8") as f:
                counts["data/evaluation/" + legacy] = {"version": "phase5/6 legacy", "count": len(json.load(f))}
    return counts


def write_manifest(mode):
    from app.core.config import settings
    from app.eligibility.models import ELIGIBILITY_ENGINE_VERSION
    from app.localization.languages import LANGUAGE_REGISTRY
    from app.main import app
    with open(os.path.join(ROOT, "data", "metadata", "corpus_manifest.json"), encoding="utf-8") as f:
        corpus = json.load(f)
    with open(os.path.join(ROOT, "data", "graph", "current", "metadata.json"), encoding="utf-8") as f:
        graph = json.load(f)
    try:
        node = subprocess.check_output(["node", "--version"], text=True, stderr=subprocess.DEVNULL).strip()
    except Exception:
        node = None
    manifest = {
        "evaluation_version": EVALUATION_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "mode": mode,
        "application_version": app.version,
        "git_commit": _git_commit(),
        "git_working_tree_dirty": _git_dirty(),
        "corpus_version": corpus.get("corpus_version"),
        "corpus_content_hash": corpus.get("content_hash"),
        "graph_version": graph.get("graph_version") or graph.get("version"),
        "graph_corpus_version": graph.get("corpus_version"),
        "eligibility_engine_version": ELIGIBILITY_ENGINE_VERSION,
        "dataset_counts": _dataset_counts(),
        "test_environment": {
            "os": platform.platform(), "python": platform.python_version(), "node": node,
            "database": "corpus fixture (offline)" if mode == "offline" else "configured DATABASE_URL",
        },
        "model_configuration": {
            "llm": f"Groq {settings.GROQ_MODEL} (temperature 0)",
            "llm_in_offline_mode": "mocked (scripted structured extraction; text LLM unavailable)",
            "asr_tts_translation": "Sarvam (saarika/bulbul/mayura) — mocked offline",
            "web_search": "Tavily — mocked offline",
            "keys_present": {k: bool(getattr(settings, k, None))
                             for k in ("GROQ_API_KEY", "TAVILY_API_KEY", "SARVAM_API_KEY")},
        },
        "supported_languages_declared": sorted(LANGUAGE_REGISTRY.keys()),
    }
    with open(os.path.join(DATA_EVAL_DIR, "evaluation_manifest.json"), "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2, ensure_ascii=False)
    return manifest


def run_all(live: bool, soak_seconds: int, skip_performance: bool = False):
    from evaluation.fixtures.corpus_db import CorpusDB
    from evaluation.runners import (
        profile_runner, retrieval_runner, eligibility_runner, xai_runner, recommendation_runner,
        multilingual_runner, voice_runner, adversarial_runner, e2e_runner, review_runner,
        performance_runner, accessibility_runner, user_study_runner, expert_runner,
    )
    plan = [
        ("profile", lambda db: profile_runner.run_offline(db)),
        ("retrieval", retrieval_runner.run),
        ("eligibility", eligibility_runner.run),
        ("xai", xai_runner.run),
        ("recommendation", recommendation_runner.run),
        ("multilingual", multilingual_runner.run),
        ("voice", voice_runner.run),
        ("human_review", review_runner.run),
        ("adversarial", adversarial_runner.run),
        ("e2e", e2e_runner.run),
        ("accessibility", accessibility_runner.run),
        ("user_study", user_study_runner.run),
        ("expert_validation", expert_runner.run),
        ("performance", lambda db: performance_runner.run(db, soak_seconds=soak_seconds)),
    ]
    if skip_performance:
        plan = [p for p in plan if p[0] != "performance"]
    results, timings = {}, {}
    for name, fn in plan:
        t0 = time.time()
        print(f"  running {name} ...", flush=True)
        try:
            results[name] = fn(CorpusDB())
        except Exception as e:  # a crashing runner is itself a finding
            import traceback
            results[name] = {"runner_error": repr(e), "traceback": traceback.format_exc()[-2000:]}
        timings[name] = round(time.time() - t0, 1)
    if live:
        results["live_profile_extraction"] = profile_runner.run_live()
        results["live_performance"] = performance_runner.run_live()
    else:
        results["live_profile_extraction"] = {"status": "NOT_MEASURED", "reason": "offline mode"}
        results["live_performance"] = {"status": "NOT_MEASURED", "reason": "offline mode"}
    results["_runner_seconds"] = timings
    return results


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--offline", action="store_true", help="deterministic evaluation (default)")
    g.add_argument("--live", action="store_true", help="also measure live external services")
    g.add_argument("--compare", nargs=2, metavar=("BEFORE", "AFTER"), help="compare two labelled runs")
    ap.add_argument("--label", default=None, help="run label (default: offline/live + timestamp)")
    ap.add_argument("--soak-seconds", type=int, default=0)
    ap.add_argument("--skip-performance", action="store_true",
                    help="skip latency/load/soak measurements (CI); those rows become NOT_MEASURED")
    args = ap.parse_args()

    from evaluation.report import write_reports, compare_runs

    if args.compare:
        out = compare_runs(*args.compare)
        print(f"before/after written: {out}")
        return 0

    logging.disable(logging.CRITICAL)  # keep evaluation output readable; the log audit re-enables it
    mode = "live" if args.live else "offline"
    label = args.label or f"{mode}-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
    print(f"SchemeSetu evaluation [{mode}] label={label}")
    manifest = write_manifest(mode)
    results = run_all(args.live, args.soak_seconds, args.skip_performance)
    out_dir = write_reports(label, manifest, results)
    print(f"reports written to {out_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
