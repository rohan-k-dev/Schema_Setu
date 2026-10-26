"""
Web Retriever — Tavily live web search for scheme discovery.

Uses existing search_service.py (§31). Minimal profile data in queries (§67, §182).
Returns List[RetrievalResult] with source_type=LIVE_WEB.
"""

import hashlib
from typing import List
from datetime import datetime, timezone

from app.retrieval.models import RetrievalResult, RetrievalRequest, SourceType, SourceTrust
from app.core.logging import get_logger
from app.core.config import settings

logger = get_logger(__name__)

# Known scheme name → ID mapping for identity resolution (§36)
_KNOWN_SCHEME_NAMES = {
    "pm-kisan": "PM_KISAN",
    "pm kisan": "PM_KISAN",
    "pradhan mantri kisan": "PM_KISAN",
    "pmfby": "PMFBY",
    "pradhan mantri fasal bima": "PMFBY",
    "kusum": "PM_KUSUM",
    "pm kusum": "PM_KUSUM",
    "pm-kusum": "PM_KUSUM",
    "kcc": "KCC",
    "kisan credit card": "KCC",
    "soil health card": "SOIL_HEALTH_CARD",
    "mgnrega": "MGNREGA",
    "nrega": "MGNREGA",
}


def _try_resolve_scheme_id(title: str) -> str:
    """Try to map a web result title to a known scheme_id (§36)."""
    if not title:
        return ""
    title_lower = title.lower().strip()
    for pattern, scheme_id in _KNOWN_SCHEME_NAMES.items():
        if pattern in title_lower:
            return scheme_id
    return ""


def _make_web_candidate_id(url: str, title: str) -> str:
    """Generate a stable candidate ID for web-only results (§36)."""
    content = f"{url}:{title}"
    return f"WEB_CANDIDATE:{hashlib.md5(content.encode()).hexdigest()[:12]}"


async def search_web(request: RetrievalRequest) -> List[RetrievalResult]:
    """
    Search Tavily for government scheme information.

    Uses minimal profile data (state, crop) — never sends income,
    Aadhaar, or other sensitive fields to external services (§67, §182).
    Raises on failure so the retrieval agent can record it (§75).
    """
    from app.services.search_service import search_web_schemes

    # Build concise search query from profile + intent (§105)
    parts = []
    if request.state:
        parts.append(request.state)
    if request.crop:
        parts.append(request.crop)
    parts.append("farmer government schemes India")

    query = " ".join(parts)
    max_results = settings.MAX_WEB_RESULTS
    now = datetime.now(timezone.utc).isoformat()

    raw_results = await search_web_schemes(query, max_results=max_results)
    results: List[RetrievalResult] = []

    for raw in raw_results:
        content = raw.get("content", "")
        url = raw.get("url", "")
        title = raw.get("title", "")

        # Try to resolve to a known scheme (§36)
        scheme_id = _try_resolve_scheme_id(title) or _try_resolve_scheme_id(content)
        if not scheme_id:
            scheme_id = _make_web_candidate_id(url or content, title or content[:50])

        # Determine source trust (§32)
        trust = SourceTrust.UNKNOWN
        if url:
            url_lower = url.lower()
            if any(d in url_lower for d in (
                ".gov.in", ".nic.in", "myscheme.gov", "pmkisan.gov",
                "pmfby.gov", "agriculture.gov",
            )):
                trust = SourceTrust.OFFICIAL
            elif any(d in url_lower for d in (
                "vikaspedia", "pib.gov", "rajasthan.gov", "karnataka.gov",
            )):
                trust = SourceTrust.SECONDARY

        results.append(RetrievalResult(
            source_type=SourceType.LIVE_WEB,
            source_id=f"web:{scheme_id}",
            scheme_id=scheme_id if not scheme_id.startswith("WEB_CANDIDATE:") else None,
            title=title or content[:100],
            description=content[:500] if content else None,
            source_url=url,
            source_name=title or "Web Source",
            source_trust=trust,
            retrieved_at=now,
            evidence={"query": query, "url": url},
            raw_reference=raw,
        ))

    logger.info(f"Web search returned {len(results)} results.")
    return results
