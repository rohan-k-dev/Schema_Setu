"""
Retrieval Request Builder — constructs typed retrieval requests.

Creates a deterministic RetrievalRequest from profile + contextual query + intent (§101).
Avoids each retrieval tool building its own inconsistent query.
"""

from app.retrieval.models import RetrievalRequest, QueryIntent
from app.core.logging import get_logger

logger = get_logger(__name__)


def build_retrieval_request(
    profile: dict,
    contextual_query: str,
    intent: str = "scheme_search",
    referenced_scheme_id: str = None,
) -> RetrievalRequest:
    """
    Build a typed RetrievalRequest from profile, query, and intent (§101).
    
    Only includes fields that are present in the profile.
    Does not insert assumptions (§102).
    """
    try:
        query_intent = QueryIntent(intent)
    except ValueError:
        query_intent = QueryIntent.SCHEME_SEARCH

    request = RetrievalRequest(
        query=contextual_query or "",
        contextual_query=contextual_query or "",
        state=profile.get("state"),
        district=profile.get("district"),
        crop=profile.get("primary_crop"),
        category=profile.get("category"),
        gender=profile.get("gender"),
        occupation=profile.get("occupation"),
        intent=query_intent,
        referenced_scheme_id=referenced_scheme_id,
    )

    logger.debug(
        f"Built retrieval request: state={request.state}, "
        f"crop={request.crop}, intent={request.intent.value}"
    )
    return request
