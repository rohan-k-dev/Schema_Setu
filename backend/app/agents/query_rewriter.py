"""
Query Rewriter — contextual query understanding and reference resolution.

Responsibilities (§21–23):
- Turn follow-up messages into standalone queries
- Resolve scheme references ("the second one" → specific scheme)
- Classify query intent
- Detect ambiguous references
- Never invent context
"""

import json
import re
from typing import List, Optional, Tuple

from app.graph.state import SchemeSetuState
from app.agents.prompts.query_rewrite_prompt import QUERY_REWRITE_PROMPT_V1
from app.retrieval.models import QueryIntent
from app.core.logging import get_logger
from app.core.config import settings
from app.utils.privacy import llm_safe_profile_summary

logger = get_logger(__name__)

_ORDINALS = {
    "first": 1, "1st": 1, "second": 2, "2nd": 2, "third": 3, "3rd": 3, "fourth": 4, "4th": 4,
    "fifth": 5, "5th": 5, "sixth": 6, "6th": 6, "seventh": 7, "7th": 7, "eighth": 8, "8th": 8,
    "ninth": 9, "9th": 9, "tenth": 10, "10th": 10,
}
_ORDINAL_RE = re.compile(
    r"\b(?:the\s+)?(" + "|".join(_ORDINALS) + r")\s+(?:one|scheme|option|item)\b"
    r"|\b(?:scheme|option|number|no\.?)\s*#?\s*(\d{1,2})\b"
    r"|\b(?:the\s+)?(last)\s+(?:one|scheme|option)\b",
    re.IGNORECASE,
)


def resolve_ordinal_reference(
    query: str, previous_scheme_ids: List[str]
) -> Optional[Tuple[str, Optional[str], int]]:
    """
    Deterministically resolve "the second one" / "scheme 2" / "the last one"
    against the schemes listed in the previous answer (§19, §20).

    Returns None when the query has no ordinal reference, otherwise
    ("resolved", scheme_id, n) or ("out_of_range", None, n). Never guesses.
    """
    m = _ORDINAL_RE.search(query or "")
    if not m:
        return None
    if m.group(1):
        n = _ORDINALS[m.group(1).lower()]
    elif m.group(2):
        n = int(m.group(2))
    else:
        n = len(previous_scheme_ids)
    if 1 <= n <= len(previous_scheme_ids):
        return ("resolved", previous_scheme_ids[n - 1], n)
    return ("out_of_range", None, n)


def _previous_scheme_ids(state) -> List[str]:
    return [s.get("scheme_id") for s in (state.get("response_schemes") or [])
            if isinstance(s, dict) and s.get("scheme_id")]


async def query_rewriter_node(state: SchemeSetuState) -> dict:
    """
    LangGraph node: Rewrite the user's query for retrieval.
    
    Uses LLM to resolve contextual references and classify intent.
    Falls back to original query if rewriting fails (§81).
    """
    logger.info("Executing Query Rewriter...")

    original_query = state.get("original_query", "")
    profile = state.get("profile") or {}
    messages = state.get("messages", [])

    # Build profile summary for context (minimal info, §67, §114)
    profile_summary = llm_safe_profile_summary(profile) or "No profile information yet"

    # Deterministic ordinal follow-up resolution takes precedence over the LLM (§19, §20)
    previous_ids = _previous_scheme_ids(state)
    ordinal = resolve_ordinal_reference(original_query, previous_ids)
    if ordinal is not None:
        kind, scheme_id, n = ordinal
        base = _fallback_result(original_query, profile)
        if kind == "resolved":
            logger.info(f"Ordinal reference #{n} resolved to {scheme_id}")
            intent = base["query_intent"]
            if intent == QueryIntent.SCHEME_SEARCH.value:
                intent = QueryIntent.SCHEME_DETAILS.value
            return {**base, "referenced_scheme_id": scheme_id, "query_intent": intent}
        count = len(previous_ids)
        if count:
            question = (f"I listed {count} scheme{'s' if count != 1 else ''} in my last answer. "
                        f"Which one do you mean?")
        else:
            question = "I haven't listed any schemes yet. Which scheme would you like to know about?"
        logger.info(f"Ordinal reference #{n} out of range ({count} previous schemes) — asking")
        return {**base, "needs_clarification": True, "contextual_query": question,
                "referenced_scheme_id": None}

    # Use recent messages for context (§55)
    window = settings.RECENT_MESSAGES_WINDOW
    from app.services.llm_service import recent_history
    recent = recent_history(messages, window)

    try:
        from app.services.llm_service import _get_llm
        from langchain_core.output_parsers import StrOutputParser

        llm = _get_llm()
        chain = QUERY_REWRITE_PROMPT_V1 | llm | StrOutputParser()

        result_text = await chain.ainvoke({
            "messages": recent,
            "profile_summary": profile_summary,
        })

        # Parse structured output
        clean = result_text.strip()
        if clean.startswith("```"):
            clean = clean.split("```")[1]
            if clean.startswith("json"):
                clean = clean[4:]
            clean = clean.strip()

        parsed = json.loads(clean)

        standalone_query = parsed.get("standalone_query", original_query)
        intent_str = parsed.get("intent", "scheme_search")
        referenced_scheme = parsed.get("referenced_scheme_id")
        # Never act on a scheme reference the user was not shown (do not guess, §19)
        if referenced_scheme and referenced_scheme not in previous_ids:
            logger.info("Ignoring LLM scheme reference not present in the previous answer")
            referenced_scheme = None
        needs_clarification = parsed.get("needs_clarification", False)
        clarification_reason = parsed.get("clarification_reason")

        # Validate intent
        try:
            intent = QueryIntent(intent_str)
        except ValueError:
            intent = QueryIntent.UNKNOWN

        logger.info(
            f"Query rewrite: intent={intent.value}, "
            f"scheme_ref={referenced_scheme}, "
            f"clarify={needs_clarification}"
        )

        return {
            "contextual_query": standalone_query,
            "normalized_query": standalone_query,
            "query_intent": intent.value,
            "referenced_scheme_id": referenced_scheme,
            "needs_clarification": needs_clarification,
        }

    except json.JSONDecodeError as e:
        logger.warning(f"Query rewrite JSON parse failed: {e}")
        return _fallback_result(original_query, profile)
    except Exception as e:
        logger.warning(f"Query rewrite failed, using original query: {e}")
        return _fallback_result(original_query, profile)


def _fallback_result(original_query: str, profile: dict) -> dict:
    """Deterministic fallback when LLM query rewriting fails (§81)."""
    # Detect simple intent from keywords
    query_lower = (original_query or "").lower()
    intent = QueryIntent.SCHEME_SEARCH.value

    if any(w in query_lower for w in ("document", "paper", "certificate")):
        intent = QueryIntent.DOCUMENTS.value
    elif any(w in query_lower for w in ("apply", "application", "how to")):
        intent = QueryIntent.APPLICATION_STEPS.value
    elif any(w in query_lower for w in ("benefit", "money", "amount", "rupee")):
        intent = QueryIntent.BENEFITS.value
    elif any(w in query_lower for w in ("eligible", "eligibility", "qualify")):
        intent = QueryIntent.ELIGIBILITY_INFORMATION.value
    elif any(w in query_lower for w in ("detail", "more about", "tell me about")):
        intent = QueryIntent.SCHEME_DETAILS.value

    # Build a standalone query from profile + original
    parts = []
    state = profile.get("state")
    crop = profile.get("primary_crop")
    if state:
        parts.append(state)
    if crop:
        parts.append(crop)
    parts.append("farmer government schemes")

    standalone = original_query or " ".join(parts)

    return {
        "contextual_query": standalone,
        "normalized_query": standalone,
        "query_intent": intent,
        "referenced_scheme_id": None,
        "needs_clarification": False,
    }
