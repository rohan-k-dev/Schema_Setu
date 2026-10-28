"""
Retrieval Agent — orchestrates parallel hybrid retrieval.

Runs PostgreSQL, Knowledge Graph, and live official-source discovery in parallel
using asyncio.gather with per-channel timeouts (§24–27), then verifies the most relevant
official pages at query time (docs/LIVE_VERIFICATION.md).
Normalizes, merges, deduplicates, and detects source conflicts.
"""

import asyncio
import time
from datetime import datetime, timezone
from typing import Dict, List, Any

from app.graph.state import SchemeSetuState
from app.retrieval.models import (
    QueryIntent,
    RetrievalMetadata,
    SourceType,
)
from app.retrieval.request_builder import build_retrieval_request
from app.retrieval.db_retriever import search_db
from app.retrieval.graph_retriever import search_graph
from app.retrieval.web_retriever import search_web
from app.retrieval.merger import merge_results
from app.core.logging import get_logger
from app.core.config import settings

logger = get_logger(__name__)


async def _search_with_timeout(coro, timeout: float, source_name: str):
    """Run a search coroutine with a timeout (§26). Returns (results, error)."""
    try:
        result = await asyncio.wait_for(coro, timeout=timeout)
        return result, None
    except asyncio.TimeoutError:
        logger.warning(f"{source_name} search timed out after {timeout}s")
        return [], f"TIMEOUT after {timeout}s"
    except Exception as e:
        logger.error(f"{source_name} search error: {e}")
        return [], str(e)


def _should_search_web(intent: str) -> bool:
    """Determine if web search is needed based on intent (§68–69)."""
    # Skip broad web search for specific detail lookups
    skip_intents = {
        QueryIntent.DOCUMENTS.value,
        QueryIntent.APPLICATION_STEPS.value,
        QueryIntent.PROFILE_UPDATE.value,
    }
    return intent not in skip_intents


async def retrieval_agent_node(state: SchemeSetuState) -> dict:
    """
    LangGraph node: Parallel hybrid retrieval.

    Flow:
    1. Build retrieval request from profile + context
    2. Run DB + Graph + Web searches in parallel (§25)
    3. Merge + deduplicate (§38)
    4. Detect source conflicts (§76)
    5. Return merged candidates with metadata
    """
    logger.info("Executing Retrieval Agent...")
    start_time = time.time()

    profile = state.get("profile") or {}
    contextual_query = state.get("contextual_query", "")
    intent = state.get("query_intent", QueryIntent.SCHEME_SEARCH.value)
    referenced_scheme_id = state.get("referenced_scheme_id")

    # 1. Build typed request (§101)
    request = build_retrieval_request(
        profile=profile,
        contextual_query=contextual_query,
        intent=intent,
        referenced_scheme_id=referenced_scheme_id,
    )

    # 2. Parallel retrieval with timeouts (§25, §26)
    retrieval_errors: Dict[str, str] = {}
    timings: Dict[str, float] = {}

    # Prepare coroutines
    db_coro = _search_with_timeout(
        search_db(request),
        settings.DB_SEARCH_TIMEOUT,
        "Database",
    )
    graph_coro = _search_with_timeout(
        search_graph(request),
        settings.GRAPH_SEARCH_TIMEOUT,
        "Knowledge Graph",
    )

    # Conditionally include web search (§68)
    include_web = _should_search_web(intent)
    live = settings.LIVE_VERIFICATION_ENABLED and intent != QueryIntent.PROFILE_UPDATE.value
    if live:
        return await _retrieve_with_live_check(request, include_web, db_coro, graph_coro, referenced_scheme_id,
                                               start_time)
    if include_web:
        web_coro = _search_with_timeout(
            search_web(request),
            settings.TAVILY_SEARCH_TIMEOUT,
            "Tavily Web",
        )
        # Run all three in parallel (§25)
        t_start = time.time()
        db_result, graph_result, web_result = await asyncio.gather(
            db_coro, graph_coro, web_coro
        )
    else:
        t_start = time.time()
        db_result, graph_result = await asyncio.gather(db_coro, graph_coro)
        web_result = ([], None)

    # Unpack results and errors
    db_results, db_error = db_result
    graph_results, graph_error = graph_result
    web_results, web_error = web_result

    total_retrieval_ms = (time.time() - t_start) * 1000

    if db_error:
        retrieval_errors["database"] = db_error
    if graph_error:
        retrieval_errors["knowledge_graph"] = graph_error
    if web_error:
        retrieval_errors["live_web"] = web_error

    # 3. Check for total failure (§27, §118)
    if not db_results and not graph_results and not web_results:
        logger.warning("All retrieval sources failed or returned empty.")
        return {
            "db_candidates": [],
            "graph_candidates": [],
            "web_candidates": [],
            "merged_candidates": [],
            "retrieval_errors": retrieval_errors,
            "source_conflicts": [],
            "graph_evidence": [],
            "retrieval_metadata": {
                "total_retrieval_ms": round(total_retrieval_ms, 1),
                "retrieval_success": {
                    "database": "database" not in retrieval_errors,
                    "knowledge_graph": "knowledge_graph" not in retrieval_errors,
                    "live_web": include_web and "live_web" not in retrieval_errors,
                },
                "candidate_count": 0,
            },
        }

    # 4. Merge and deduplicate (§38–39)
    merged_candidates, source_conflicts = merge_results(
        db_results, graph_results, web_results
    )

    # A follow-up about one specific scheme answers about that scheme only;
    # profile-wide graph matches would otherwise replace the list the user is
    # referring to (Phase 7 BUG-034).
    if referenced_scheme_id:
        focused = [c for c in merged_candidates if c.scheme_id == referenced_scheme_id]
        if focused:
            merged_candidates = focused
            source_conflicts = [c for c in source_conflicts if c.scheme_id == referenced_scheme_id]

    # 5. Serialize for LangGraph state
    merged_dicts = [c.to_response_dict() for c in merged_candidates]
    db_dicts = [r.model_dump() for r in db_results]
    graph_dicts = [r.model_dump() for r in graph_results]
    web_dicts = [r.model_dump() for r in web_results]
    conflict_dicts = [c.model_dump() for c in source_conflicts]

    # Extract graph evidence
    graph_evidence = []
    for c in merged_candidates:
        if c.graph_evidence:
            graph_evidence.append({
                "scheme_id": c.scheme_id,
                "evidence": c.graph_evidence,
                "matched_fields": c.matched_fields,
            })

    metadata = {
        "total_retrieval_ms": round(total_retrieval_ms, 1),
        # success = the channel answered without error (an empty answer is not a failure)
        "retrieval_success": {
            "database": "database" not in retrieval_errors,
            "knowledge_graph": "knowledge_graph" not in retrieval_errors,
            "live_web": include_web and "live_web" not in retrieval_errors,
        },
        "candidate_count": len(merged_candidates),
        "conflict_count": len(source_conflicts),
    }

    elapsed = time.time() - start_time
    logger.info(
        f"Retrieval complete: {len(merged_candidates)} candidates, "
        f"{len(source_conflicts)} conflicts in {elapsed:.2f}s"
    )

    return {
        "db_candidates": db_dicts,
        "graph_candidates": graph_dicts,
        "web_candidates": web_dicts,
        "merged_candidates": merged_dicts,
        "retrieval_errors": retrieval_errors,
        "source_conflicts": conflict_dicts,
        "graph_evidence": graph_evidence,
        "retrieval_metadata": metadata,
    }


# ─── query-time discovery and verification (docs/LIVE_VERIFICATION.md) ────────

async def _retrieve_with_live_check(request, include_web: bool, db_coro, graph_coro, referenced_scheme_id,
                                    start_time: float) -> dict:
    """DB + graph + live discovery in parallel, then live verification of the best official pages."""
    from app.live import discovery as disc
    from app.live.discovery import topic_keywords
    from app.live.service import live_service, stored_freshness

    t_start = time.monotonic()
    started_at = datetime.now(timezone.utc)
    deadline = t_start + settings.LIVE_BUDGET_SECONDS
    topic = topic_keywords(request.contextual_query or request.query)      # never the question itself

    async def no_discovery():
        return disc.Discovery(started_at=started_at)

    discovery_coro = live_service.discover(topic, request.state, request.crop) if include_web else no_discovery()
    (db_results, db_error), (graph_results, graph_error), discovery = await asyncio.gather(
        db_coro, graph_coro, discovery_coro)
    retrieval_errors: Dict[str, str] = {}
    if db_error:
        retrieval_errors["database"] = db_error
    if graph_error:
        retrieval_errors["knowledge_graph"] = graph_error

    # the referenced scheme's own official page first when the farmer asks about one scheme
    ordered = sorted(db_results, key=lambda r: r.scheme_id != referenced_scheme_id) if referenced_scheme_id else db_results
    try:
        outcome = await live_service.verify(discovery, ordered, started=t_start, deadline=deadline,
                                            started_at=started_at,
                                            question=request.contextual_query or request.query)  # local ranking only
    except Exception as exc:                       # the live check must never break the answer
        logger.error(f"Live verification failed: {type(exc).__name__}: {exc}")
        from app.live.service import Outcome
        outcome = Outcome(report={"performed": False, "warnings": [
            "The live check of official sources failed; everything shown comes from our stored records."]})
    web_results = outcome.web_results
    report = outcome.report
    if include_web and report.get("discovery", {}).get("status") not in ("OK", None):
        retrieval_errors["live_web"] = report["discovery"]["status"]
    total_retrieval_ms = (time.monotonic() - t_start) * 1000

    if not db_results and not graph_results and not web_results:
        logger.warning("All retrieval sources failed or returned empty.")
        merged_dicts, conflict_dicts, graph_evidence, db_dicts, graph_dicts, web_dicts = [], [], [], [], [], []
        candidate_count = conflict_count = 0
    else:
        merged_candidates, source_conflicts = merge_results(db_results, graph_results, web_results)
        if referenced_scheme_id:
            focused = [c for c in merged_candidates if c.scheme_id == referenced_scheme_id]
            if focused:
                merged_candidates = focused
                source_conflicts = [c for c in source_conflicts if c.scheme_id == referenced_scheme_id]
        live_conflicts = [c for c in outcome.conflicts
                          if not referenced_scheme_id or c.scheme_id == referenced_scheme_id]
        source_conflicts = list(source_conflicts) + live_conflicts
        merged_dicts = [c.to_response_dict() for c in merged_candidates]
        reason = ("live checking of official sources didn't run for this question"
                  if not report.get("performed") else "its official page wasn't checked for this question")
        for d in merged_dicts:
            d["freshness"] = (outcome.freshness.get(d["scheme_id"])
                              or stored_freshness(d["scheme_id"], outcome.stored_dates, reason))
        db_dicts = [r.model_dump() for r in db_results]
        graph_dicts = [r.model_dump() for r in graph_results]
        web_dicts = [r.model_dump() for r in web_results]
        conflict_dicts = [c.model_dump() for c in source_conflicts]
        graph_evidence = [{"scheme_id": c.scheme_id, "evidence": c.graph_evidence, "matched_fields": c.matched_fields}
                          for c in merged_candidates if c.graph_evidence]
        candidate_count, conflict_count = len(merged_candidates), len(source_conflicts)

    metadata = {
        "total_retrieval_ms": round(total_retrieval_ms, 1),
        "retrieval_success": {
            "database": "database" not in retrieval_errors,
            "knowledge_graph": "knowledge_graph" not in retrieval_errors,
            "live_web": bool(report.get("sources_accessed")) or (include_web and "live_web" not in retrieval_errors),
        },
        "candidate_count": candidate_count,
        "conflict_count": conflict_count,
    }
    logger.info(f"Retrieval with live check: {candidate_count} candidates, "
                f"{report.get('sources_accessed', 0)} official page(s) read live in {time.time() - start_time:.2f}s")
    return {
        "db_candidates": db_dicts,
        "graph_candidates": graph_dicts,
        "web_candidates": web_dicts,
        "merged_candidates": merged_dicts,
        "retrieval_errors": retrieval_errors,
        "source_conflicts": conflict_dicts,
        "graph_evidence": graph_evidence,
        "retrieval_metadata": metadata,
        "live_check": report,
    }

