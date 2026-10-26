"""
Conflict Detector — detects conflicting facts across retrieval sources.

When the same scheme has different values for the same field
from different sources, records the conflict (§76).

DB value is canonical and takes precedence (§40–41).
"""

from typing import List, Dict, Any

from app.retrieval.models import SourceConflict, RetrievalResult, SourceType
from app.core.logging import get_logger

logger = get_logger(__name__)

# Fields to check for conflicts between sources
_CONFLICT_FIELDS = ["benefits", "eligibility_summary", "official_url"]


def detect_conflicts(
    scheme_id: str,
    results_by_source: Dict[str, RetrievalResult],
) -> List[SourceConflict]:
    """
    Detect conflicts for a single scheme across multiple sources (§76).

    Compares field values between DB, Graph, and Web results.
    Only flags conflicts where both sources have non-empty values
    that differ.
    """
    conflicts = []

    # Get results by source type
    db_result = results_by_source.get(SourceType.DATABASE.value)
    web_result = results_by_source.get(SourceType.LIVE_WEB.value)

    # Only check DB vs Web conflicts (Graph doesn't carry these fields)
    if not db_result or not web_result:
        return []

    for field in _CONFLICT_FIELDS:
        db_val = getattr(db_result, field, None)
        web_val = getattr(web_result, field, None)

        if db_val and web_val and str(db_val).strip() != str(web_val).strip():
            conflict = SourceConflict(
                scheme_id=scheme_id,
                field=field,
                values={
                    SourceType.DATABASE.value: str(db_val),
                    SourceType.LIVE_WEB.value: str(web_val),
                },
                sources=[SourceType.DATABASE.value, SourceType.LIVE_WEB.value],
            )
            conflicts.append(conflict)
            logger.info(
                f"Source conflict: {scheme_id}.{field} "
                f"DB='{str(db_val)[:50]}' vs Web='{str(web_val)[:50]}'"
            )

    return conflicts
