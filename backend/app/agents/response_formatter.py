"""
Response Formatter Agent — Phase 5 updated.

Transforms eligibility results + candidates into user response (§87–§89).

Key Phase 5 changes:
- Uses EligibilityResult.status as authoritative (§88)
- Includes eligibility evidence in response
- Deterministic fallback uses XAI templates (§58)
- Never overrides engine decision (§128)
"""

import json
from typing import Dict, Any, List

from app.graph.state import SchemeSetuState
from app.agents.prompts.response_prompt import RESPONSE_PROMPT_V1
from app.retrieval.models import ResponseStatus
from app.eligibility.models import EligibilityStatus, EligibilityResult
from app.xai.templates import (
    generate_template_explanation, generate_summary,
    FIELD_LABELS,
)
from app.core.logging import get_logger
from app.core.config import settings
from app.utils.privacy import llm_safe_profile_summary, compact_scheme_for_llm
from app.xai.response_validator import validate_llm_response

logger = get_logger(__name__)

# The LLM rephrases only the top-ranked schemes (keeps prompts small); the full
# ranked list is still returned to the user as structured scheme cards.
LLM_PROMPT_SCHEMES = 5

REVIEW_NOTICE = (
    "\n\nSome results could not be verified automatically and have been flagged "
    "for review by a person. Please treat them as unconfirmed."
)


def _build_deterministic_response(
    candidates: list,
    query: str,
    recommendation_results: list = None,
) -> str:
    """
    Deterministic fallback response (§58, §88).

    When recommendation_results are available, uses eligibility-aware formatting.
    Otherwise falls back to Phase 4 style.
    """
    # Phase 5: use recommendation results if available
    if recommendation_results:
        return _build_eligibility_response(recommendation_results)

    if not candidates:
        return "I could not find matching schemes in the available sources. Please try refining your search criteria."

    lines = [f"I found {len(candidates)} relevant scheme(s) based on your profile:\n"]
    for i, c in enumerate(candidates, 1):
        name = c.get("name", "Unknown Scheme")
        benefit = c.get("benefit_summary", "")
        eligibility = c.get("eligibility_summary", "")
        url = c.get("official_url", "")

        line = f"{i}. **{name}**"
        if benefit:
            line += f"\n   Benefits: {benefit}"
        if eligibility:
            line += f"\n   Eligibility: {eligibility}"
        if url:
            line += f"\n   More info: {url}"
        lines.append(line)

    lines.append("\nPlease note: This information is based on available sources. Actual eligibility may vary.")
    return "\n".join(lines)


def _build_eligibility_response(recommendation_results: list) -> str:
    """
    Build response from ranked eligibility results (§89, §193).
    """
    if not recommendation_results:
        return "I could not find matching schemes in the available sources."

    lines = []

    # Group by status
    eligible = [r for r in recommendation_results
                if getattr(r, 'eligibility_status', None) == EligibilityStatus.ELIGIBLE]
    needs_info = [r for r in recommendation_results
                  if getattr(r, 'eligibility_status', None) == EligibilityStatus.NEEDS_MORE_INFORMATION]
    not_eligible = [r for r in recommendation_results
                    if getattr(r, 'eligibility_status', None) == EligibilityStatus.NOT_ELIGIBLE]

    if eligible:
        lines.append(f"Based on the information you provided, I found {len(eligible)} scheme(s) that match the available criteria:\n")
        for i, r in enumerate(eligible, 1):
            name = getattr(r, 'scheme_name', '') or r.scheme_id
            explanation = getattr(r, 'explanation', '')
            lines.append(f"{i}. **{name}** ✓ Matches available criteria")
            if explanation:
                # Extract just matched criteria lines
                for line in explanation.split('\n'):
                    if line.startswith('✓'):
                        lines.append(f"   {line}")

    if needs_info:
        lines.append(f"\n{len(needs_info)} scheme(s) may match but need more information:\n")
        for r in needs_info:
            name = getattr(r, 'scheme_name', '') or r.scheme_id
            result_dict = getattr(r, 'eligibility_result', {}) or {}
            missing = result_dict.get('missing_information', [])
            lines.append(f"• **{name}** ○ More information needed")
            if missing:
                field_labels = [FIELD_LABELS.get(f, f.replace('_', ' ').title()) for f in missing]
                lines.append(f"   Missing: {', '.join(field_labels)}")

    if not_eligible and not eligible and not needs_info:
        lines.append("The available schemes do not match the current profile criteria.\n")
        for r in not_eligible[:3]:
            name = getattr(r, 'scheme_name', '') or r.scheme_id
            lines.append(f"• **{name}** ✗ Does not match current criteria")

    if not eligible and not needs_info and not not_eligible:
        lines.append("I could not reliably evaluate eligibility for the found schemes.")

    lines.append("\nPlease note: Eligibility is based on available published criteria. Actual eligibility may vary.")
    return "\n".join(lines)


# Follow-up questions about documents / how to apply / benefits are answered from the
# stored scheme data when the LLM is unavailable (Phase 8: demo and no-key runs).
_DETAIL_INTENTS = {
    "documents": ("documents", "Documents required for"),
    "application_steps": ("application_steps", "How to apply for"),
    "benefits": ("benefit_summary", "Benefits of"),
}
_DETAIL_SCHEMES = 3


def _build_detail_section(intent: str, response_schemes: List[Dict[str, Any]],
                          referenced_scheme_id: str = None) -> str:
    """Deterministic answer to a documents / application-steps / benefits question.

    Uses only the corpus fields on the scheme cards (never invents content). Covers the
    referenced scheme, otherwise the top-ranked eligible schemes.
    """
    field, heading = _DETAIL_INTENTS.get(intent or "", (None, None))
    if not field or not response_schemes:
        return ""
    if referenced_scheme_id:
        targets = [s for s in response_schemes if s.get("scheme_id") == referenced_scheme_id]
    else:
        targets = [s for s in response_schemes
                   if s.get("eligibility_status") == EligibilityStatus.ELIGIBLE.value][:_DETAIL_SCHEMES]
    parts = []
    for s in targets:
        value = s.get(field)
        name = s.get("name") or s.get("scheme_id")
        if not value:
            parts.append(f"{heading} **{name}**: not available in the scheme database. "
                         f"Please check the official source.")
            continue
        if isinstance(value, list):
            items = "\n".join(f"   {i}. {v}" for i, v in enumerate(value, 1))
            parts.append(f"{heading} **{name}**:\n{items}")
        else:
            parts.append(f"{heading} **{name}**: {value}")
        if s.get("official_url"):
            parts.append(f"   Official source: {s['official_url']}")
    return "\n".join(parts)


_CANDIDATE_FIELDS = (
    "description", "benefit_summary", "eligibility_summary", "documents", "application_steps",
    "official_url", "sources", "retrieval_sources", "matched_fields", "graph_evidence",
)


def _build_response_schemes(
    candidates: list,
    recommendation_results: list = None,
) -> List[Dict[str, Any]]:
    """
    Build structured scheme cards for the API response (§92, §50).

    Each card combines the ranked eligibility evidence with the retrieved
    scheme details (documents, application steps, official source, graph
    evidence) so the frontend can show them (Phase 7 BUG-012).
    """
    by_id = {c.get("scheme_id"): c for c in candidates or [] if isinstance(c, dict)}
    if recommendation_results:
        schemes = []
        for r in recommendation_results[:settings.MAX_RESPONSE_SCHEMES]:
            sid = getattr(r, 'scheme_id', '')
            candidate = by_id.get(sid, {})
            scheme = {k: candidate.get(k) for k in _CANDIDATE_FIELDS}
            scheme["documents"] = scheme.get("documents") or []
            scheme["application_steps"] = scheme.get("application_steps") or []
            scheme["sources"] = scheme.get("sources") or []
            scheme["graph_evidence"] = scheme.get("graph_evidence") or []
            if getattr(r, 'eligibility_result', None):
                scheme.update(r.eligibility_result)
            scheme['scheme_id'] = sid
            scheme['name'] = getattr(r, 'scheme_name', '') or candidate.get("name", "")
            scheme['eligibility_status'] = getattr(r, 'eligibility_status', EligibilityStatus.UNVERIFIABLE).value
            scheme['profile_match_score'] = getattr(r, 'profile_match_score', 0.0)
            scheme['rank'] = getattr(r, 'rank', 0)
            scheme['rank_reasons'] = getattr(r, 'rank_reasons', [])
            scheme['xai_explanation'] = getattr(r, 'explanation', None)
            schemes.append(scheme)
        return schemes

    return candidates


async def response_formatter_node(state: SchemeSetuState) -> dict:
    """
    LangGraph node: Format structured candidates into user-facing response.

    Phase 5: Uses eligibility results and recommendations as authoritative (§88).
    Falls back to deterministic formatting on LLM failure (§58).
    """
    logger.info("Executing Response Formatter (Phase 5)...")

    candidates = state.get("merged_candidates", [])
    original_query = state.get("original_query", "")
    contextual_query = state.get("contextual_query", original_query)
    profile = state.get("profile") or {}
    retrieval_errors = state.get("retrieval_errors", {})
    retrieval_metadata = state.get("retrieval_metadata", {})

    # Phase 5: get eligibility and recommendation results
    recommendation_results = state.get("recommendation_results", [])
    eligibility_results = state.get("eligibility_results", [])
    missing_eligibility_fields = state.get("missing_eligibility_fields", [])

    # No candidates → no results
    if not candidates:
        response_text = "I could not find matching schemes in the available sources."
        if profile.get("state") or profile.get("primary_crop"):
            response_text += " You could try checking other crops or confirming your state."

        return {
            "messages": [("assistant", response_text)],
            "response_text": response_text,
            "response_status": ResponseStatus.NO_RESULTS.value,
            "response_schemes": [],
        }

    # Determine response status: partial only when a channel actually failed
    # (an empty-but-healthy channel is not a failure) — Phase 7 BUG-028
    status = (ResponseStatus.PARTIAL_RESULTS.value if retrieval_errors
              else ResponseStatus.SCHEMES_FOUND.value)

    # Minimal profile summary for the external LLM (§114)
    profile_summary = llm_safe_profile_summary(profile) or "No profile details"

    # Build retrieval status
    channels = ("database", "knowledge_graph", "live_web")
    retrieval_status = "; ".join(
        f"{ch}: {'unavailable' if ch in retrieval_errors else 'available'}" for ch in channels
    )

    # Build response schemes with eligibility data (§92)
    response_schemes = _build_response_schemes(candidates, recommendation_results)

    # Try LLM formatting
    try:
        from app.services.llm_service import _get_llm
        from langchain_core.output_parsers import StrOutputParser

        # Prepare candidates data with eligibility info
        candidates_for_prompt = [compact_scheme_for_llm(s) for s in response_schemes[:LLM_PROMPT_SCHEMES]]
        candidates_data = json.dumps(candidates_for_prompt, ensure_ascii=False, default=str)

        llm = _get_llm()
        chain = RESPONSE_PROMPT_V1 | llm | StrOutputParser()

        response_text = await chain.ainvoke({
            "user_query": contextual_query or original_query,
            "profile_summary": profile_summary,
            "retrieval_status": retrieval_status,
            "candidates_data": candidates_data,
        })

        if not response_text or len(response_text.strip()) < 10:
            raise ValueError("LLM returned empty/insufficient response")

        # The engine's statuses are authoritative: reject unsupported LLM content (§99–§105)
        valid, reasons = validate_llm_response(response_text, response_schemes)
        if not valid:
            raise ValueError(f"LLM reply rejected by grounding validator: {reasons[:3]}")

        logger.info(f"Response formatted via LLM ({len(response_text)} chars)")

    except Exception as e:
        logger.warning(f"LLM response formatting failed, using deterministic fallback: {e}")
        response_text = _build_deterministic_response(
            candidates[:settings.MAX_CANDIDATES],
            contextual_query,
            recommendation_results=recommendation_results,
        )
        detail = _build_detail_section(state.get("query_intent"), response_schemes,
                                       state.get("referenced_scheme_id"))
        if detail:
            response_text = f"{detail}\n\n{response_text}"

    if state.get("needs_review"):
        response_text += REVIEW_NOTICE

    return {
        "messages": [("assistant", response_text)],
        "response_text": response_text,
        "response_status": status,
        "response_schemes": response_schemes,
    }
