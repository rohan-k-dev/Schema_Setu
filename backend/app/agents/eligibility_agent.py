"""
Eligibility Agent — LangGraph node for deterministic eligibility evaluation (§238).

Runs after retrieval_agent. Loads rules, evaluates candidates, stores results in state.
"""

from typing import Dict, Any

from app.eligibility.evaluator import evaluate_scheme
from app.eligibility.models import EligibilityResult, EligibilityStatus
from app.eligibility.validators import validate_rules
from app.xai.explainer import explain
from app.core.logging import get_logger

logger = get_logger(__name__)


def _sid(candidate) -> str:
    if isinstance(candidate, dict):
        return candidate.get("scheme_id", "")
    return getattr(candidate, "scheme_id", "")


async def eligibility_agent(state: Dict[str, Any]) -> Dict[str, Any]:
    """
    LangGraph node: evaluate eligibility for merged candidates (§238).

    Reads: merged_candidates, profile
    Writes: eligibility_results, missing_eligibility_fields, eligibility_errors
    """
    merged_candidates = state.get("merged_candidates", [])
    profile = state.get("profile") or {}
    profile_dict = profile.model_dump() if hasattr(profile, "model_dump") else (
        profile.dict() if hasattr(profile, "dict") else dict(profile)
    )

    # No candidates → skip (§241)
    if not merged_candidates:
        logger.info("No candidates for eligibility evaluation")
        return {
            "eligibility_results": [],
            "missing_eligibility_fields": [],
            "eligibility_errors": [],
        }

    # Load rules for all candidate schemes from DB in one batch query
    rules_by_scheme: Dict[str, list] = {}
    errors = []
    scheme_ids = [_sid(c) for c in merged_candidates if _sid(c)]
    try:
        from app.database.repositories.rule_repository import RuleRepository
        rules_by_scheme = await RuleRepository.list_for_scheme_ids(scheme_ids)
    except Exception as e:
        # No rules → every scheme becomes UNVERIFIABLE: never a false ELIGIBLE (§128)
        logger.error(f"Database unavailable for rule loading: {e}")
        errors.append("Rule loading failed: database unavailable")

    # Evaluate each candidate
    results = []
    missing_fields = set()

    for candidate in merged_candidates:
        scheme_id = ""
        scheme_name = ""
        if hasattr(candidate, "scheme_id"):
            scheme_id = candidate.scheme_id
            scheme_name = getattr(candidate, "name", "")
        elif isinstance(candidate, dict):
            scheme_id = candidate.get("scheme_id", "")
            scheme_name = candidate.get("name", "")

        if not scheme_id:
            continue

        rules = rules_by_scheme.get(scheme_id, [])
        official_url = candidate.get("official_url") if isinstance(candidate, dict) else None

        try:
            result = evaluate_scheme(
                scheme_id=scheme_id,
                scheme_name=scheme_name,
                rules=rules,
                profile=profile_dict,
                source_url=official_url,
            )
            # Generate explanation
            explanation = explain(result)
            result.evidence_summary = explanation.summary

            results.append(result)

            # Collect missing fields
            if result.status == EligibilityStatus.NEEDS_MORE_INFORMATION:
                missing_fields.update(result.missing_information)

        except Exception as e:
            logger.error(f"Eligibility evaluation failed for {scheme_id}: {e}")
            errors.append(f"Evaluation failed for {scheme_id}: {str(e)}")
            # Create UNVERIFIABLE result on error (§218)
            results.append(EligibilityResult(
                scheme_id=scheme_id,
                scheme_name=scheme_name,
                status=EligibilityStatus.UNVERIFIABLE,
                needs_review=True,
            ))

    logger.info(
        f"Eligibility evaluation: {len(results)} schemes, "
        f"E={sum(1 for r in results if r.status == EligibilityStatus.ELIGIBLE)} "
        f"N={sum(1 for r in results if r.status == EligibilityStatus.NOT_ELIGIBLE)} "
        f"I={sum(1 for r in results if r.status == EligibilityStatus.NEEDS_MORE_INFORMATION)} "
        f"U={sum(1 for r in results if r.status == EligibilityStatus.UNVERIFIABLE)}"
    )

    return {
        "eligibility_results": results,
        "missing_eligibility_fields": sorted(missing_fields),
        "eligibility_errors": errors,
    }
