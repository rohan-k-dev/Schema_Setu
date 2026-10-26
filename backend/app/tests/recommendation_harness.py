"""
Run the scheme pipeline (retrieval → eligibility → recommendation → response) offline on the
canonical corpus file (evaluation CorpusDB, no PostgreSQL / LLM / web), for recommendation tests
and the baseline of strict eligibility decisions (fixtures/recommendations/baseline_statuses.json).
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from typing import Any, Dict

ROOT = Path(__file__).resolve().parents[3]
BASELINE = Path(__file__).parent / "fixtures" / "recommendations" / "baseline_statuses.json"

# Profiles covering several states, crops, land sizes, occupations and missing information.
PROFILES: Dict[str, Dict[str, Any]] = {
    "ka_ragi_small": {"state": "Karnataka", "primary_crop": "ragi", "land_size_acres": 2.0, "age": 40,
                      "occupation": "farmer", "gender": "male", "annual_income": 90000},
    "mh_cotton_unknown_land": {"state": "Maharashtra", "primary_crop": "cotton", "age": 52, "occupation": "farmer"},
    "tn_paddy_woman": {"state": "Tamil Nadu", "primary_crop": "paddy", "land_size_acres": 1.5, "age": 35,
                       "occupation": "farmer", "gender": "female"},
    "up_wheat_large": {"state": "Uttar Pradesh", "primary_crop": "wheat", "land_size_acres": 30.0, "age": 61,
                       "occupation": "farmer", "income_tax_payer": True},
    "ts_dairy": {"state": "Telangana", "occupation": "dairy farmer", "age": 30, "land_size_acres": 3.0},
    "assam_minimal": {"state": "Assam"},
    "ap_young_tenant": {"state": "Andhra Pradesh", "primary_crop": "groundnut", "age": 19, "occupation": "farmer",
                        "land_size_acres": 0.0},
    "rj_no_state_crop_only": {"primary_crop": "mustard", "age": 45},
}
QUERIES = {"ka_ragi_small": "which schemes can help me", "mh_cotton_unknown_land": "crop insurance for cotton",
           "tn_paddy_woman": "schemes for women farmers", "up_wheat_large": "pension and loan schemes",
           "ts_dairy": "dairy cattle support", "assam_minimal": "government schemes",
           "ap_young_tenant": "irrigation help", "rj_no_state_crop_only": "seed subsidy"}


async def run_pipeline(profile: Dict[str, Any], query: str, db=None) -> Dict[str, Any]:
    """Every node of the scheme answer in order, as the LangGraph graph runs them."""
    from app.agents.recommendation_agent import recommendation_agent
    from app.agents.eligibility_agent import eligibility_agent
    from app.agents.response_formatter import response_formatter_node
    from app.agents.retrieval_agent import retrieval_agent_node
    state: Dict[str, Any] = {"profile": dict(profile), "original_query": query, "contextual_query": query,
                             "query_intent": "scheme_search", "session_id": "recommendation-harness"}
    for node in (retrieval_agent_node, eligibility_agent, recommendation_agent, response_formatter_node):
        state.update(await node(state))
    return state


def offline(db=None):
    sys.path[:0] = [str(ROOT)]
    from evaluation.fixtures.corpus_db import CorpusDB
    from evaluation.fixtures.mock_services import offline_environment
    return offline_environment(db or CorpusDB())


def statuses(state: Dict[str, Any]) -> Dict[str, str]:
    return {r.scheme_id: r.status.value for r in state.get("eligibility_results") or []}


async def _capture() -> Dict[str, Dict[str, str]]:
    out = {}
    with offline():
        for name, profile in PROFILES.items():
            out[name] = statuses(await run_pipeline(profile, QUERIES[name]))
    return out


if __name__ == "__main__":       # py -m app.tests.recommendation_harness  (re-capture only on purpose)
    BASELINE.parent.mkdir(parents=True, exist_ok=True)
    BASELINE.write_text(json.dumps(asyncio.run(_capture()), indent=1, sort_keys=True), encoding="utf-8")
    print("baseline written", BASELINE)
