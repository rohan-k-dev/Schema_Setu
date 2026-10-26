"""
User-study analysis (Phase 7 §79–§89, §155–§156).

Reads anonymised records from data/evaluation/user_study/records.json and
computes the study metrics. It NEVER generates participant data: with no
records every metric is NOT_MEASURED.

Record format: see data/evaluation/user_study/README.md
"""

import json
import os
from collections import Counter, defaultdict
from typing import Any, Dict

from evaluation import DATA_EVAL_DIR
from evaluation.metrics import mean, safe_ratio

STUDY_DIR = os.path.join(DATA_EVAL_DIR, "user_study")
TASKS = {
    "T1": "Provide farmer profile", "T2": "Find relevant schemes", "T3": "Understand why one scheme matches",
    "T4": "Find required documents", "T5": "Find application steps", "T6": "Ask a follow-up question",
    "T7": "Use voice", "T8": "Change language", "T9": "Interpret eligibility result",
}
FORBIDDEN_KEYS = {"name", "phone", "phone_number", "aadhaar", "aadhaar_number", "email", "address"}


def run(_corpus_db=None) -> Dict[str, Any]:
    path = os.path.join(STUDY_DIR, "records.json")
    data = {"participants": [], "task_results": []}
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    parts, results = data.get("participants", []), data.get("task_results", [])

    privacy_violations = sorted({k for rec in parts + results for k in rec if k.lower() in FORBIDDEN_KEYS})
    report: Dict[str, Any] = {
        "participants": len(parts),
        "task_results": len(results),
        "tasks": TASKS,
        "privacy_violations": privacy_violations,
    }
    if not parts or not results:
        report.update({"status": "NOT_MEASURED",
                       "reason": "No participant records in data/evaluation/user_study/records.json. "
                                 "The protocol is in docs/phase7-user-study-report.md.",
                       "task_completion_rate": None, "average_task_time_s": None,
                       "comprehension_score": None, "average_trust": None, "average_ease_of_use": None,
                       "average_voice_rating": None})
    else:
        by_task = defaultdict(list)
        for r in results:
            by_task[r["task_id"]].append(r)
        themes = Counter(t for r in results for t in r.get("themes", []))
        report.update({
            "status": "MEASURED",
            "language_distribution": dict(Counter(p.get("language") for p in parts)),
            "group_distribution": dict(Counter(p.get("group") for p in parts)),
            "task_completion_rate": safe_ratio(sum(1 for r in results if r.get("completed")), len(results)),
            "average_task_time_s": mean([r.get("completion_time_s") for r in results if r.get("completed")]),
            "comprehension_score": mean([r.get("comprehension_score") for r in results]),
            "average_trust": mean([r.get("trust_rating") for r in results]),
            "average_ease_of_use": mean([r.get("usability_rating") for r in results]),
            "average_voice_rating": mean([r.get("voice_rating") for r in results if r.get("voice_rating")]),
            "per_task": {t: {"attempts": len(v), "completion_rate": safe_ratio(sum(1 for r in v if r.get("completed")), len(v)),
                             "mean_time_s": mean([r.get("completion_time_s") for r in v if r.get("completed")])}
                         for t, v in sorted(by_task.items())},
            "qualitative_themes": dict(themes),
            "caveat": "Small capstone sample; descriptive statistics only, no significance claims.",
        })
    with open(os.path.join(DATA_EVAL_DIR, "user_study_report.json"), "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)
    return report
