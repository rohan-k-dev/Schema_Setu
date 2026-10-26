"""
Database Retriever — PostgreSQL scheme search via repository layer.

Uses existing SchemeRepository (§29). Does NOT access SQL directly.
Returns List[RetrievalResult] with source_type=DATABASE.

Phase 7 changes:
- Relevance ordering before truncation: schemes specifically targeted at the
  user's state / crop come first, then nationally applicable schemes
  (alphabetical truncation used to drop them — BUG-006).
- Documents, application steps and benefits are batch-loaded for the
  returned schemes so scheme cards can show them (BUG-012).
- Failures are raised, not swallowed, so the retrieval agent can report
  the channel as failed (BUG-008).
"""

from typing import Any, Dict, List
from datetime import datetime, timezone

from app.retrieval.models import RetrievalResult, RetrievalRequest, SourceType, SourceTrust
from app.database.repositories.scheme_repository import SchemeRepository
from app.core.logging import get_logger
from app.core.config import settings

logger = get_logger(__name__)


class DatabaseUnavailableError(RuntimeError):
    """Raised when the canonical database cannot be queried."""


async def search_db(request: RetrievalRequest) -> List[RetrievalResult]:
    """
    Search PostgreSQL for schemes matching the retrieval request.

    Supports:
    - Exact scheme_id lookup (§70)
    - State + crop search
    - State-only search
    - Crop-only search
    - Name search (only when there is query text)

    Raises on database failure (the retrieval agent records it, §75).
    """
    now = datetime.now(timezone.utc).isoformat()

    # 1. Exact scheme lookup if referenced (§70)
    if request.referenced_scheme_id:
        scheme = await SchemeRepository.get_by_scheme_id(request.referenced_scheme_id)
        if scheme:
            details = await SchemeRepository.get_details_for_scheme_ids([scheme.scheme_id])
            logger.info(f"DB exact lookup: found {request.referenced_scheme_id}")
            return [_scheme_row_to_result(scheme, now, details.get(scheme.scheme_id, {}), request)]

    # 2. Profile-aware search
    state, crop = request.state, request.crop
    if state and crop:
        scheme_rows = await SchemeRepository.search_by_state_and_crop(state, crop)
    elif state:
        scheme_rows = await SchemeRepository.search_by_state(state)
    elif crop:
        scheme_rows = await SchemeRepository.search_by_crop(crop)
    elif (request.query or "").strip():
        scheme_rows = await SchemeRepository.search_by_name(request.query.strip())
    else:
        # No profile and no query text: nothing to search for (never return the whole catalogue)
        return []

    if not scheme_rows:
        if not await SchemeRepository.health_check():
            raise DatabaseUnavailableError("Database unavailable")
        logger.info("DB search returned 0 results.")
        return []

    details = await SchemeRepository.get_details_for_scheme_ids([s.scheme_id for s in scheme_rows])

    def relevance(s) -> tuple:
        d = details.get(s.scheme_id, {})
        targets_state = bool(state and d.get("states"))
        targets_crop = bool(crop and d.get("crops"))
        return (-(int(targets_state) + int(targets_crop)), s.name)

    ranked = sorted(scheme_rows, key=relevance)[: settings.MAX_DB_RESULTS]
    results = [_scheme_row_to_result(s, now, details.get(s.scheme_id, {}), request) for s in ranked]
    logger.info(f"DB search returned {len(results)} results.")
    return results


def _benefit_text(benefits) -> str:
    parts = []
    for b in benefits or []:
        text = getattr(b, "description", "") or ""
        amount = getattr(b, "amount", None)
        if amount and amount not in text:
            text = f"{amount}: {text}" if text else str(amount)
        if text:
            parts.append(text)
    return " ".join(parts) or None


def _scheme_row_to_result(scheme, retrieved_at: str, details: Dict[str, Any],
                          request: RetrievalRequest) -> RetrievalResult:
    """Convert a SchemeRow domain model (+ batch-loaded details) to RetrievalResult."""
    targeted = []
    if request.state and details.get("states"):
        targeted.append("state_targeted")
    if request.crop and details.get("crops"):
        targeted.append("crop_targeted")
    return RetrievalResult(
        source_type=SourceType.DATABASE,
        source_id=f"db:{scheme.scheme_id}",
        scheme_id=scheme.scheme_id,
        title=scheme.name,
        description=scheme.description,
        benefits=_benefit_text(details.get("benefits")),
        eligibility_summary=scheme.eligibility_summary,
        documents=[d.name for d in details.get("documents", [])] or None,
        application_steps=[st.description for st in details.get("application_steps", [])] or None,
        official_url=scheme.official_url,
        source_name="SchemeSetu Database",
        source_url=scheme.official_url,
        source_trust=SourceTrust.OFFICIAL,
        retrieved_at=retrieved_at,
        evidence={"source": "postgresql", "scheme_id": scheme.scheme_id, "targeting": targeted,
                  "scheme_meta": _scheme_meta(scheme, details)},
    )


def _scheme_meta(scheme, details: Dict[str, Any]) -> Dict[str, Any]:
    """Stored attributes used to explain relevance and show provenance (docs/RECOMMENDATIONS.md)."""
    verified = scheme.last_verified_at
    return {
        "level": scheme.level, "scheme_type": scheme.scheme_type, "ministry": scheme.ministry,
        "states": list(details.get("states") or []), "crops": list(details.get("crops") or []),
        "benefit_types": list(dict.fromkeys(getattr(b, "benefit_type", None) for b in details.get("benefits") or []
                                            if getattr(b, "benefit_type", None))),
        "application_url": scheme.application_url,
        "last_verified_at": verified.isoformat() if hasattr(verified, "isoformat") else verified,
        "needs_review": bool(scheme.needs_review), "possible_duplicate": bool(scheme.possible_duplicate),
    }
