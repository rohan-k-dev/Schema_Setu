"""
Completeness Agent — deterministic profile completeness check.

This is purely deterministic logic, NOT free-form LLM reasoning (§17–18).
Checks required discovery fields in configurable priority order.
"""

from app.graph.state import SchemeSetuState
from app.models.profile import FarmerProfile
from app.core.logging import get_logger
from app.core.config import settings

logger = get_logger(__name__)


async def completeness_agent_node(state: SchemeSetuState) -> dict:
    """
    LangGraph node: Deterministic completeness check.
    
    Checks if the profile has all critical fields populated.
    Uses configurable PROFILE_PRIORITY from settings.
    
    Returns:
        profile_complete: True/False
        missing_fields: list of missing field names in priority order
    """
    logger.info("Executing Completeness Agent...")

    profile_data = state.get("profile")
    priority = settings.PROFILE_PRIORITY

    if not profile_data:
        logger.info(f"No profile data — all critical fields missing: {priority}")
        return {
            "profile_complete": False,
            "missing_fields": list(priority),
        }

    if isinstance(profile_data, dict):
        profile = FarmerProfile(**profile_data)
    else:
        profile = profile_data

    # Deterministic check against configurable priority fields (§18)
    missing = []
    for field_name in priority:
        value = getattr(profile, field_name, None)
        if value is None:
            missing.append(field_name)

    profile_complete = len(missing) == 0
    logger.info(
        f"Completeness: complete={profile_complete}, missing={missing}"
    )

    return {
        "profile_complete": profile_complete,
        "missing_fields": missing,
    }
