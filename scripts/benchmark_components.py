"""
Component latency benchmark against a REAL PostgreSQL database (Phase 8 Step 12).

Measures, over N repetitions of 5 representative profiles:
  DB retrieval (search_db incl. batched detail load), Knowledge Graph retrieval,
  web retrieval (mocked → measures our overhead only), merge, eligibility
  (batch rule load + evaluation), and the full LangGraph pipeline (LLM mocked).

External API latency (Groq, Tavily, Sarvam) is NOT measured here — that needs
`python scripts/run_evaluation.py --live` with keys.

Usage (from Scheme_Setu/, DATABASE_URL set, corpus imported):
    python scripts/benchmark_components.py [--n 30]
Writes data/evaluation/reports/benchmarks/component_latency.json
"""

import argparse
import asyncio
import json
import logging
import os
import platform
import sys
import time
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import evaluation  # noqa: E402,F401
from evaluation import REPORTS_DIR  # noqa: E402
from evaluation.metrics import latency_summary  # noqa: E402
from evaluation.runners.performance_runner import PROFILES  # noqa: E402
from evaluation.fixtures.mock_services import offline_environment, ScriptedProfileLLM, FakeWebSearch  # noqa: E402


async def bench(n: int):
    from langchain_core.messages import HumanMessage
    from app.database.connection import init_db, close_db, is_db_available
    from app.services.knowledge_graph_service import init_knowledge_graph
    from app.retrieval.request_builder import build_retrieval_request
    from app.retrieval.db_retriever import search_db
    from app.retrieval.graph_retriever import search_graph
    from app.retrieval.web_retriever import search_web
    from app.retrieval.merger import merge_results
    from app.agents.eligibility_agent import eligibility_agent
    from app.graph.workflow import kisan_agent

    await init_db()
    if not is_db_available():
        raise SystemExit("DATABASE_URL not reachable")
    init_knowledge_graph()
    t = {k: [] for k in ("db", "graph", "web_mocked", "merge", "eligibility", "pipeline_llm_mocked")}

    for i in range(n):
        utter, extraction = PROFILES[i % len(PROFILES)]
        from app.models.profile import FarmerProfile
        profile = FarmerProfile(**extraction).model_dump()
        req = build_retrieval_request(profile=profile, contextual_query="")

        s = time.perf_counter(); db = await search_db(req); t["db"].append((time.perf_counter() - s) * 1000)
        s = time.perf_counter(); gr = await search_graph(req); t["graph"].append((time.perf_counter() - s) * 1000)
        s = time.perf_counter(); wb = await search_web(req); t["web_mocked"].append((time.perf_counter() - s) * 1000)
        s = time.perf_counter(); merged, _ = merge_results(db, gr, wb); t["merge"].append((time.perf_counter() - s) * 1000)
        state = {"merged_candidates": [c.to_response_dict() for c in merged], "profile": profile}
        s = time.perf_counter(); await eligibility_agent(state); t["eligibility"].append((time.perf_counter() - s) * 1000)
        s = time.perf_counter()
        await kisan_agent.ainvoke({"messages": [HumanMessage(content=utter)], "session_id": f"bench-{i}"},
                                  config={"configurable": {"thread_id": f"bench-{i}-{time.time()}"}})
        t["pipeline_llm_mocked"].append((time.perf_counter() - s) * 1000)
    await close_db()
    return {k: latency_summary(v) for k, v in t.items()}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=30)
    args = ap.parse_args()
    logging.disable(logging.CRITICAL)
    script = ScriptedProfileLLM({u: e for u, e in PROFILES})
    with offline_environment(db=None, profile_llm=script, web=FakeWebSearch([])):
        results = asyncio.run(bench(args.n))
    out = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "database": "PostgreSQL 16 (Docker, local)", "requests_per_component": args.n,
        "machine": {"os": platform.platform(), "python": platform.python_version()},
        "note": "LLM, Tavily and Sarvam mocked: these are SchemeSetu's own processing times, not user-facing latency.",
        "latency_ms": results,
    }
    os.makedirs(os.path.join(REPORTS_DIR, "benchmarks"), exist_ok=True)
    path = os.path.join(REPORTS_DIR, "benchmarks", "component_latency.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2)
    for k, v in results.items():
        print(f"{k:22s} mean {v['mean_ms']:8.1f} ms   p50 {v['p50_ms']:8.1f}   p95 {v['p95_ms']:8.1f}")
    print("written", os.path.relpath(path, ROOT))


if __name__ == "__main__":
    main()
