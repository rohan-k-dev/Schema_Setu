"""
Expert validation (Phase 7 §90–§95, §157).

1. Builds a deterministic sample of real system outputs (offline pipeline) that
   covers the categories in §91, written to
   data/evaluation/expert_validation/sample_outputs.json for the expert.
2. Reads expert ratings from data/evaluation/expert_validation/ratings.json
   and computes agreement statistics. It never invents ratings: with no
   ratings every metric is NOT_MEASURED.
"""

import json
import os
from collections import Counter
from typing import Any, Dict, List

from evaluation import DATA_EVAL_DIR
from evaluation.metrics import safe_ratio
from evaluation.runners.common import new_thread, get_client
from evaluation.fixtures.mock_services import offline_environment, ScriptedProfileLLM, FakeWebSearch

EXPERT_DIR = os.path.join(DATA_EVAL_DIR, "expert_validation")

SAMPLE_PLAN = [
    ("simple_eligibility", "I am a farmer from Karnataka with 2 acres growing ragi",
     {"state": "Karnataka", "land_size_acres": 2, "primary_crop": "ragi", "occupation": "farmer"},
     ["PM_KISAN", "KCC"]),
    ("multiple_conditions", "I am a 30 year old farmer in Uttar Pradesh with 2 acres of wheat",
     {"state": "Uttar Pradesh", "land_size_acres": 2, "primary_crop": "wheat", "occupation": "farmer", "age": 30},
     ["PM_KMY"]),
    ("state_specific", "I grow groundnut on 4 acres in Andhra Pradesh",
     {"state": "Andhra Pradesh", "land_size_acres": 4, "primary_crop": "groundnut"}, ["STATE_AP_RYTHU"]),
    ("crop_specific", "I grow groundnut on 4 acres in Andhra Pradesh",
     {"state": "Andhra Pradesh", "land_size_acres": 4, "primary_crop": "groundnut"}, ["NMOOP"]),
    ("needs_information", "I am a farmer in Telangana with 3 acres of maize",
     {"state": "Telangana", "land_size_acres": 3, "primary_crop": "maize", "occupation": "farmer"}, ["PM_KMY"]),
    ("not_eligible", "I am a male farmer in Karnataka with 1 acre of ragi",
     {"state": "Karnataka", "land_size_acres": 1, "primary_crop": "ragi", "gender": "male", "occupation": "farmer"},
     ["MKSP"]),
    ("not_eligible", "I am a landless farmer in Karnataka, I own 0 acres and grow ragi",
     {"state": "Karnataka", "land_size_acres": 0, "primary_crop": "ragi", "occupation": "farmer"}, ["PM_KISAN"]),
    ("application_information", "I am a farmer from Karnataka with 2 acres growing ragi",
     {"state": "Karnataka", "land_size_acres": 2, "primary_crop": "ragi", "occupation": "farmer"}, ["SOIL_HEALTH_CARD"]),
    ("uncertain_data", "I am a farmer from Karnataka with 2 acres growing ragi",
     {"state": "Karnataka", "land_size_acres": 2, "primary_crop": "ragi", "occupation": "farmer"}, ["MGNREGA", "AGMARKNET"]),
    ("state_specific", "I am a farmer in Maharashtra with 5 acres of cotton",
     {"state": "Maharashtra", "land_size_acres": 5, "primary_crop": "cotton", "occupation": "farmer"}, ["STATE_MH_NAMO"]),
    ("xai_explanation", "I am a woman farmer in Assam with 1 acre of rice",
     {"state": "Assam", "land_size_acres": 1, "primary_crop": "rice", "gender": "female", "occupation": "farmer"},
     ["MKSP", "MOVCDNER"]),
]


def build_sample(corpus_db) -> List[Dict[str, Any]]:
    client = get_client()
    sample, n = [], 0
    for category, utter, extraction, scheme_ids in SAMPLE_PLAN:
        script = ScriptedProfileLLM({utter: extraction})
        with offline_environment(db=corpus_db, profile_llm=script, web=FakeWebSearch([])):
            body = client.post("/chat", json={"message": utter, "thread_id": new_thread("expert")}).json()
        schemes = {s.get("scheme_id"): s for s in body.get("schemes") or []}
        for sid in scheme_ids:
            s = schemes.get(sid)
            if not s:
                continue
            n += 1
            sample.append({
                "sample_id": f"EX{n:02d}", "category": category, "scheme_id": sid, "scheme_name": s.get("name"),
                "query": utter, "profile_summary": extraction,
                "system_status": s.get("eligibility_status"),
                "matched_criteria": s.get("matched_criteria"), "failed_criteria": s.get("failed_criteria"),
                "missing_information": s.get("missing_information"),
                "explanation": s.get("xai_explanation") or s.get("evidence_summary"),
                "documents": s.get("documents"), "application_steps": s.get("application_steps"),
                "source_url": s.get("official_url"),
            })
    return sample


def run(corpus_db) -> Dict[str, Any]:
    os.makedirs(EXPERT_DIR, exist_ok=True)
    sample = build_sample(corpus_db)
    with open(os.path.join(EXPERT_DIR, "sample_outputs.json"), "w", encoding="utf-8") as f:
        json.dump({"note": "Generated from the offline pipeline. Experts rate each sample in ratings.json.",
                   "samples": sample}, f, indent=2, ensure_ascii=False)

    ratings_path = os.path.join(EXPERT_DIR, "ratings.json")
    ratings = []
    if os.path.exists(ratings_path):
        with open(ratings_path, encoding="utf-8") as f:
            ratings = json.load(f).get("ratings", [])
    report: Dict[str, Any] = {"sample_size": len(sample),
                              "sample_distribution": dict(Counter(s["category"] for s in sample)),
                              "ratings_recorded": len(ratings)}
    if not ratings:
        report.update({"status": "NOT_MEASURED",
                       "reason": "No expert ratings recorded in data/evaluation/expert_validation/ratings.json",
                       "correct_rate": None, "xai_correct_rate": None, "source_correct_rate": None})
    else:
        acc = Counter(r.get("accuracy_rating") for r in ratings)
        disagreements = [r for r in ratings if r.get("expert_status") and r.get("expert_status") != r.get("system_status")]
        report.update({
            "status": "MEASURED",
            "accuracy_ratings": dict(acc),
            "correct_rate": safe_ratio(acc.get("CORRECT", 0), len(ratings)),
            "xai_correct_rate": safe_ratio(sum(1 for r in ratings if r.get("xai_rating") == "XAI_CORRECT"),
                                           sum(1 for r in ratings if r.get("xai_rating"))),
            "source_correct_rate": safe_ratio(sum(1 for r in ratings if r.get("source_rating") == "SOURCE_CORRECT"),
                                              sum(1 for r in ratings if r.get("source_rating"))),
            "disagreements": len(disagreements),
            "disagreement_causes": dict(Counter(r.get("disagreement_cause", "uninvestigated") for r in disagreements)),
            "policy": "Expert disagreement never changes system output automatically (§94).",
        })
    with open(os.path.join(DATA_EVAL_DIR, "expert_validation_report.json"), "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)
    return report
