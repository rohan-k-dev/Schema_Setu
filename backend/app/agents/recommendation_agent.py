"""
Recommendation Agent — LangGraph node for deterministic ranking (§238).

Runs after eligibility_agent. Ranks results and prepares final response data.
"""

from typing import Dict, Any, List

from app.eligibility.models import EligibilityResult, EligibilityStatus
from app.recommendation.ranker import rank_results
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
        return {"recommendation_results": [], **_review_fields(state, results)}

    # Get graph evidence for ranking boost
    graph_evidence = state.get("graph_evidence")

    # Rank deterministically
    ranked = rank_results(results, graph_evidence=graph_evidence)

    logger.info(f"Ranked {len(ranked)} schemes")

    return {
        "recommendation_results": ranked,
        **_review_fields(state, results),
    }


def _review_fields(state: Dict[str, Any], results: list) -> Dict[str, Any]:
    """Human-in-the-loop escalation on deterministic triggers (§56–§58)."""
    try:
        from app.services.review_service import escalate_if_needed
        case = escalate_if_needed(
            session_id=state.get("session_id") or "",
            query=state.get("original_query") or "",
            profile=state.get("profile") or {},
            eligibility_results=results,
            source_conflicts=state.get("source_conflicts") or [],
            retrieval_errors=state.get("retrieval_errors") or {},
        )
    except Exception as e:  # escalation must never break the user's answer
        logger.error(f"Review escalation failed: {e}")
        case = None
    if case is None:
        return {"needs_review": False, "review_reason": None, "review_case_id": None}
    logger.info(f"Escalated to human review: case={case.case_id} reason={case.reason.value}")
    return {"needs_review": True, "review_reason": case.reason.value, "review_case_id": case.case_id}
