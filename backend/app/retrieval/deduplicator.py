"""
Deduplicator — identity normalization and deduplication.

Normalizes scheme identities across sources so that:
    DB: PM_KISAN
    Graph: SCHEME:PM_KISAN
    Web: PM Kisan
all resolve to the same canonical scheme_id (§145–146).
"""

import re
from typing import Optional

from app.core.logging import get_logger

logger = get_logger(__name__)


def normalize_scheme_id(raw_id: str) -> Optional[str]:
    """
    Normalize a scheme identifier to its canonical form (§145).

    Handles:
    - Graph prefix: "SCHEME:PM_KISAN" → "PM_KISAN"
    - Case normalization: "pm_kisan" → "PM_KISAN"
    - Web candidate IDs: kept as-is (prefixed with WEB_CANDIDATE:)
    """
    if not raw_id:
        return None

    raw_id = raw_id.strip()

    # Keep web candidate IDs as-is
    if raw_id.startswith("WEB_CANDIDATE:"):
        return raw_id

    # Strip graph node prefix
    if raw_id.upper().startswith("SCHEME:"):
        raw_id = raw_id[7:]

    # Normalize: uppercase, strip whitespace
    normalized = raw_id.upper().strip()
    # Replace spaces/hyphens with underscores
    normalized = re.sub(r'[\s\-]+', '_', normalized)

    return normalized if normalized else None


def scheme_ids_match(id_a: Optional[str], id_b: Optional[str]) -> bool:
    """Check if two scheme IDs refer to the same scheme after normalization."""
    if not id_a or not id_b:
        return False
    norm_a = normalize_scheme_id(id_a)
    norm_b = normalize_scheme_id(id_b)
    return norm_a is not None and norm_a == norm_b
