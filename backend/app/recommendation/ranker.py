"""
Deterministic recommendation ranker — Phase 5 (§59, §95).

Ranks schemes by eligibility status, then by profile match strength.
NO ML, NO probability, NO reinforcement learning (§98).

Ranking precedence (§59):
1. ELIGIBLE (highest)
2. NEEDS_MORE_INFORMATION
3. NOT_ELIGIBLE
4. UNVERIFIABLE (lowest)

Within same status, prefer (§95):
- More matched profile criteria
- More graph evidence
- Official source availability
"""

from typing import List, Dict, Any, Optional

from app.eligibility.models import EligibilityResult, EligibilityStatus
from app.recommendation.models import RankedScheme
from app.xai.explainer import explain_for_response
from app.core.logging import get_logger

logger = get_logger(__name__)

# Status priority (lower = higher rank)
_STATUS_PRIORITY = {
    EligibilityStatus.ELIGIBLE: 0,
    EligibilityStatus.NEEDS_MORE_INFORMATION: 1,
    EligibilityStatus.NOT_ELIGIBLE: 2,
    EligibilityStatus.UNVERIFIABLE: 3,
}


def _compute_match_score(result: EligibilityResult) -> float:
    """
    Compute a transparent profile match score (§60, §96).

    profile_match_score = passed / (passed + failed + unknown)

    NOT eligibility probability. Just a ranking signal.
    """
    total_evaluable = result.passed_rules + result.failed_rules + result.unknown_rules
    if total_evaluable == 0:
        return 0.0
    return round(result.passed_rules / total_evaluable, 3)


def _build_rank_reasons(result: EligibilityResult) -> List[str]:
    """Build explainable rank reasons (§97)."""
    reasons = []

    if result.passed_rules > 0:
        reasons.append(f"{result.passed_rules} criteria matched")

    has_official = any(
        s.get("type") == "OFFICIAL" or "gov" in s.get("text", "").lower()
        for s in result.source_references
    )
    if has_official:
        reasons.append("Official source available")

    if result.unknown_rules == 0 and result.failed_rules == 0:
        reasons.append("All available criteria verified")

    return reasons


def _graph_evidence_ids(graph_evidence) -> set:
    if not graph_evidence:
        return set()
    if isinstance(graph_evidence, dict):
        return set(graph_evidence)
    ids = set()
    for item in graph_evidence:
        if isinstance(item, dict) and item.get("scheme_id"):
            ids.add(item["scheme_id"])
        elif isinstance(item, str):
            ids.add(item)
    return ids


def rank_results(
    results: List[EligibilityResult],
    graph_evidence: Optional[Dict[str, Any]] = None,
) -> List[RankedScheme]:
    """
    Rank eligibility results deterministically (§59).

    Returns ranked list with position, score, and explanations.
    """
    if not results:
        return []

    # Graph evidence arrives from the retrieval agent as a list of
    # {"scheme_id", "evidence", "matched_fields"} dicts (or a dict keyed by id).
    graph_ids = _graph_evidence_ids(graph_evidence)

    # Build ranked items with computed scores
    ranked_items = []
    for result in results:
        score = _compute_match_score(result)
        reasons = _build_rank_reasons(result)

        # Boost score slightly if graph evidence exists
        if result.scheme_id in graph_ids:
            score += 0.01  # Minor boost, not dominant
            reasons.append("Knowledge graph match")

        explanation = explain_for_response(result)

        ranked_items.append(RankedScheme(
            scheme_id=result.scheme_id,
            scheme_name=result.scheme_name,
            eligibility_status=result.status,
            profile_match_score=score,
            rank_reasons=reasons,
            eligibility_result=result.to_response_dict(),
            explanation=explanation,
        ))

    # Sort: status priority first, then match score descending
    # scheme_id is the final tie-breaker: identical inputs give an identical
    # order regardless of candidate order (§49, Phase 7 BUG-019)
    # Documented order (§95): status → match ratio → MORE matched criteria
    # (Phase 8 fix: the count was not used, so a 1-criterion scheme could outrank
    # a 2-criterion one) → scheme_id as the stable tie-breaker (§49).
    passed = {r.scheme_id: r.passed_rules for r in results}
    ranked_items.sort(key=lambda x: (
        _STATUS_PRIORITY.get(x.eligibility_status, 99),
        -x.profile_match_score,
        -passed.get(x.scheme_id, 0),
        x.scheme_id,
    ))

    # Assign ranks
    for i, item in enumerate(ranked_items):
        item.rank = i + 1

    logger.info(
        f"Ranked {len(ranked_items)} schemes: "
        f"ELIGIBLE={sum(1 for r in ranked_items if r.eligibility_status == EligibilityStatus.ELIGIBLE)}, "
        f"NEEDS_INFO={sum(1 for r in ranked_items if r.eligibility_status == EligibilityStatus.NEEDS_MORE_INFORMATION)}, "
        f"NOT_ELIGIBLE={sum(1 for r in ranked_items if r.eligibility_status == EligibilityStatus.NOT_ELIGIBLE)}, "
        f"UNVERIFIABLE={sum(1 for r in ranked_items if r.eligibility_status == EligibilityStatus.UNVERIFIABLE)}"
    )

    return ranked_items
