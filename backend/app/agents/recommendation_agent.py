"""
Recommendation Agent — LangGraph node for deterministic ranking (§238).

Runs after eligibility_agent. Ranks results and prepares final response data.
"""

from typing import Dict, Any, List

from app.eligibility.models import EligibilityResult, EligibilityStatus
from app.recommendation.ranker import rank_results
from app.recommendation.alternatives import build_sections
from app.core.logging import get_logger

logger = get_logger(__name__)


async def recommendation_agent(state: Dict[str, Any]) -> Dict[str, Any]:
    """
    LangGraph node: rank eligibility results (§59, §238).

    Reads: eligibility_results, graph_evidence
    Writes: recommendation_results
    """
    results: List[EligibilityResult] = state.get("eligibility_results", [])

    if not results:
        logger.info("No eligibility results to rank")
        return {"recommendation_results": [], **(await _review_fields(state, results))}

    # Get graph evidence for ranking boost
    graph_evidence = state.get("graph_evidence")

    # Rank deterministically
    ranked = rank_results(results, graph_evidence=graph_evidence)

    logger.info(f"Ranked {len(ranked)} schemes")

    # Eligible schemes + relevant alternatives (separate from, and never changing, the eligibility decision)
    profile = state.get("profile") or {}
    sections = build_sections(results, state.get("merged_candidates") or [],
                              profile.model_dump() if hasattr(profile, "model_dump") else dict(profile),
                              state.get("contextual_query") or state.get("original_query") or "",
                              rank_order=[r.scheme_id for r in ranked])

    return {
        "recommendation_results": ranked,
        "recommendation_sections": sections,
        **(await _review_fields(state, results)),
    }


async def _review_fields(state: Dict[str, Any], results: list) -> Dict[str, Any]:
    """Human-in-the-loop escalation on deterministic triggers (§56–§58, docs/HUMAN_REVIEW.md)."""
    profile = state.get("profile") or {}
    if hasattr(profile, "model_dump"):
        profile = profile.model_dump()
    try:
        from app.services.review_workflow import escalate
        case = await escalate(
            session_id=state.get("session_id") or "",
            query=state.get("original_query") or "",
            profile=dict(profile),
            results=results,
            candidates=state.get("merged_candidates") or [],
            source_conflicts=state.get("source_conflicts") or [],
            retrieval_errors=state.get("retrieval_errors") or {},
        )
    except Exception as e:  # escalation must never break the user's answer
        logger.error(f"Review escalation failed: {type(e).__name__}: {e}")
        case = None
    if case is None:
        return {"needs_review": False, "review_reason": None, "review_case_id": None}
    logger.info(f"Escalated to human review: case={case['case_id']} reason={case['reason']}")
    return {"needs_review": True, "review_reason": case["reason"], "review_case_id": case["case_id"]}
