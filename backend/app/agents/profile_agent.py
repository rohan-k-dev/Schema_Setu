"""
Profile Agent — extracts and merges farmer profile from conversation.

Responsibilities (§12–16):
- Extract profile info from recent conversation using LLM structured output
- Merge with existing profile (never erase known fields)
- Detect profile conflicts (old value != new value)
- Apply deterministic normalization
- Never fabricate missing data
"""

from typing import Dict, Any, List

from app.graph.state import SchemeSetuState
from app.models.profile import FarmerProfile
from app.agents.prompts.profile_prompt import PROFILE_PROMPT_V1
from app.core.logging import get_logger
from app.core.config import settings
from app.core.exceptions import LANGUAGE_SERVICE_UNAVAILABLE

logger = get_logger(__name__)


def _detect_conflicts(
    existing: Dict[str, Any], new_data: Dict[str, Any]
) -> List[Dict[str, Any]]:
    """
    Detect profile conflicts where existing non-None value differs
    from a new non-None value (§15).
    """
    conflicts = []
    for field, new_value in new_data.items():
        if new_value is None:
            continue
        old_value = existing.get(field)
        if old_value is not None and old_value != new_value:
            conflicts.append({
                "field": field,
                "old_value": old_value,
                "new_value": new_value,
            })
    return conflicts


async def profile_agent_node(state: SchemeSetuState) -> dict:
    """
    LangGraph node: Extract profile from conversation and merge.
    
    Uses structured LLM output for extraction, then deterministic
    merge/conflict detection.
    """
    logger.info("Executing Profile Agent...")

    messages = state.get("messages", [])
    if not messages:
        return {
            "profile": state.get("profile"),
            "profile_conflicts": [],
        }

    # Capture original query from latest human message
    original_query = None
    for msg in reversed(messages):
        if hasattr(msg, "type") and msg.type == "human":
            original_query = msg.content
            break
        elif isinstance(msg, (list, tuple)) and len(msg) >= 2 and msg[0] == "human":
            original_query = msg[1]
            break

    try:
        # Use the existing LLM service for structured extraction
        from app.services.llm_service import _get_structured_llm
        structured_llm = _get_structured_llm()

        # Use recent messages window
        window = settings.RECENT_MESSAGES_WINDOW
        from app.services.llm_service import recent_history
        recent_messages = recent_history(messages, window)

        chain = PROFILE_PROMPT_V1 | structured_llm
        extracted = await chain.ainvoke({"messages": recent_messages})
        # Structured output may come back as a plain dict (pydantic-v2 schema with this
        # langchain version); validate it into a FarmerProfile so the same canonicalisation
        # applies. Found in the first live run (Phase 8).
        if isinstance(extracted, dict):
            extracted = FarmerProfile(**extracted)

        if not extracted:
            logger.warning("Profile extraction returned None, keeping existing profile.")
            return {
                "profile": state.get("profile"),
                "profile_conflicts": [],
                "original_query": original_query,
                "error": None,
            }

        # Get existing profile
        existing_profile_data = state.get("profile") or {}
        if isinstance(existing_profile_data, dict):
            existing_profile = FarmerProfile(**existing_profile_data)
        else:
            existing_profile = existing_profile_data

        # Detect conflicts BEFORE merging (§15)
        extracted_dict = extracted.model_dump(exclude_none=True)
        existing_dict = existing_profile.model_dump()
        conflicts = _detect_conflicts(existing_dict, extracted_dict)

        if conflicts:
            # Log field names only — never profile values (privacy, Phase 7 BUG-021)
            logger.info(f"Profile conflicts detected for fields: {[c['field'] for c in conflicts]}")
            # Still merge (the new value takes precedence),
            # but flag the conflicts for the question agent
            merged = existing_profile.merge_with(extracted)
            return {
                "profile": merged.model_dump(),
                "profile_conflicts": conflicts,
                "original_query": original_query,
                "error": None,
            }

        # Normal merge — no conflicts
        merged = existing_profile.merge_with(extracted)
        logger.info(f"Profile updated; known fields: {sorted(merged.model_dump(exclude_none=True))}")

        return {
            "profile": merged.model_dump(),
            "profile_conflicts": [],
            "original_query": original_query,
            "error": None,
        }

    except Exception as e:
        # The language service (LLM) failed or is not configured: keep the known
        # profile and flag it, so the user is told instead of being asked the
        # same question again (Phase 8, failure handling).
        logger.error(f"Profile extraction error: {type(e).__name__}: {e}")
        return {
            "profile": state.get("profile"),
            "profile_conflicts": [],
            "original_query": original_query,
            "error": LANGUAGE_SERVICE_UNAVAILABLE,
        }
