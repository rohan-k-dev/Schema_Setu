"""
LangGraph routing functions for Phase 4 multi-agent architecture.

Deterministic routing based on state inspection (§9, §199).
No LLM reasoning for routing decisions.
"""

from app.graph.state import SchemeSetuState
from app.core.logging import get_logger

logger = get_logger(__name__)


def route_after_completeness(state: SchemeSetuState) -> str:
    """
    Route after completeness check (§8).

    Priority:
    1. Profile conflicts → question_agent (ask confirmation)
    2. Incomplete profile → question_agent (ask missing field)
    3. Complete profile → query_rewriter (proceed to retrieval)
    """
    # Check for profile conflicts first (§15)
    conflicts = state.get("profile_conflicts", [])
    if conflicts:
        logger.info(f"Routing to question_agent: {len(conflicts)} profile conflict(s)")
        return "question_agent"

    # Check completeness (§17)
    profile_complete = state.get("profile_complete", False)
    missing = state.get("missing_fields", [])

    if not profile_complete or missing:
        logger.info(f"Routing to question_agent: missing={missing}")
        return "question_agent"

    logger.info("Routing to query_rewriter: profile complete")
    return "query_rewriter"


def route_after_query_rewrite(state: SchemeSetuState) -> str:
    """
    Route after query rewriting (§22).

    If the query is ambiguous and needs clarification → question_agent.
    Otherwise → retrieval_agent.
    """
    needs_clarification = state.get("needs_clarification", False)

    if needs_clarification:
        logger.info("Routing to question_agent: query needs clarification")
        return "question_agent"

    logger.info("Routing to retrieval_agent")
    return "retrieval_agent"


# Backward compatibility
def route_based_on_completeness(state: SchemeSetuState) -> str:
    """Legacy routing function — delegates to new route_after_completeness."""
    return route_after_completeness(state)
