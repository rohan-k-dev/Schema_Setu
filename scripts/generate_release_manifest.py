"""
Generate release_manifest.json for a release candidate (Phase 7 §176–§177).

Usage (from Scheme_Setu/):
    python scripts/generate_release_manifest.py --label after --rc SchemeSetu-RC-1

Runs the backend test suite and reads the labelled evaluation run; nothing is
hand-entered.
"""

import argparse
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


def _run(cmd, cwd):
    p = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)
    return p.returncode, (p.stdout + p.stderr)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--label", default="after")
    ap.add_argument("--rc", default="SchemeSetu-RC-1")
    ap.add_argument("--tag", default="v1.0.0")
    args = ap.parse_args()

    code, out = _run([sys.executable, "-m", "pytest", "app/tests", "-q", "-p", "no:cacheprovider"],
                     os.path.join(ROOT, "backend"))
    m = re.search(r"(\d+) passed", out)
    f = re.search(r"(\d+) failed", out)
    s = re.search(r"(\d+) skipped", out)
    tests = {"exit_code": code, "passed": int(m.group(1)) if m else 0,
             "failed": int(f.group(1)) if f else 0, "skipped": int(s.group(1)) if s else 0}

    with open(os.path.join(ROOT, "data", "evaluation", "reports", args.label, "results.json"), encoding="utf-8") as fh:
        run = json.load(fh)
    manifest = run["manifest"]
    counts = {}
    for row in run["scorecard"]:
        counts[row["status"]] = counts.get(row["status"], 0) + 1

    try:
        commit = subprocess.check_output(["git", "-C", ROOT, "rev-parse", "--short", "HEAD"], text=True).strip()
        dirty = bool(subprocess.check_output(["git", "-C", ROOT, "status", "--porcelain"], text=True).strip())
    except Exception:
        commit, dirty = None, None

    release = {
        "release_candidate": args.rc,
        "recommended_git_tag": args.tag,
        "tag_created": False,
        "application_version": manifest["application_version"],
        "corpus_version": manifest["corpus_version"],
        "graph_version": manifest["graph_version"],
        "graph_corpus_version": manifest["graph_corpus_version"],
        "eligibility_engine_version": manifest["eligibility_engine_version"],
        "evaluation_version": manifest["evaluation_version"],
        "evaluation_run": args.label,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "git_commit": commit,
        "git_working_tree_dirty": dirty,
        "note_on_commit": "Phase 7 changes are uncommitted; commit them and regenerate before tagging.",
        "test_status": {"backend_pytest": tests},
        "scorecard_status_counts": counts,
        "graph_corpus_matches_db_corpus": manifest["graph_corpus_version"] == manifest["corpus_version"],
        "classification": "release candidate — not a production release",
    }
    with open(os.path.join(ROOT, "release_manifest.json"), "w", encoding="utf-8") as fh:
        json.dump(release, fh, indent=2)
    print(json.dumps(release, indent=2))
    return 0 if tests["failed"] == 0 and code == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
