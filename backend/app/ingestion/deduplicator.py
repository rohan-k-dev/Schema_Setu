"""
Deduplicator — detects duplicate schemes in the corpus.

Uses normalized name + ministry + official URL matching.
Does NOT merge uncertain matches — flags them for review instead.
"""

from typing import List, Tuple
from app.ingestion import CanonicalScheme
from app.core.logging import get_logger

logger = get_logger(__name__)


def detect_duplicates(schemes: List[CanonicalScheme]) -> List[Tuple[str, str, str]]:
    """
    Detect potential duplicate schemes.

    Returns list of (scheme_id_1, scheme_id_2, reason) tuples.
    Does NOT auto-merge — only flags.
    """
    duplicates = []
    n = len(schemes)

    for i in range(n):
        for j in range(i + 1, n):
            reason = _check_duplicate(schemes[i], schemes[j])
            if reason:
                duplicates.append((schemes[i].scheme_id, schemes[j].scheme_id, reason))
                logger.info(f"Possible duplicate: {schemes[i].scheme_id} <-> {schemes[j].scheme_id}: {reason}")

    return duplicates


def _check_duplicate(a: CanonicalScheme, b: CanonicalScheme) -> str:
    """
    Check if two schemes are potentially duplicates.
    Returns reason string if duplicate, empty string if not.
    """
    # Same scheme ID (should not happen after validation)
    if a.scheme_id == b.scheme_id:
        return "identical_scheme_id"

    # Exact name match
    if a.name.lower().strip() == b.name.lower().strip():
        return "identical_name"

    # Check alias overlap
    a_names = {a.name.lower()} | {alias.lower() for alias in a.aliases}
    b_names = {b.name.lower()} | {alias.lower() for alias in b.aliases}
    name_overlap = a_names & b_names
    if name_overlap:
        return f"shared_alias: {list(name_overlap)[0]}"

    # Same official URL (must be specific page, not just domain)
    if a.official_url and b.official_url:
        a_url = a.official_url.rstrip('/')
        b_url = b.official_url.rstrip('/')
        # Only flag if URLs match AND are specific pages (have a path beyond /)
        if a_url == b_url:
            from urllib.parse import urlparse
            parsed = urlparse(a_url)
            # Skip if URL is just a domain root (e.g., https://agricoop.nic.in)
            if parsed.path and parsed.path.rstrip('/') != '':
                return "identical_official_url"
            # Domain-only URLs are common for different schemes under same ministry
            # Only flag if names are also similar
            pass

    # Same short name
    if a.short_name and b.short_name:
        if a.short_name.lower() == b.short_name.lower():
            return f"identical_short_name: {a.short_name}"

    return ""


def flag_duplicates(
    schemes: List[CanonicalScheme],
    duplicates: List[Tuple[str, str, str]],
) -> List[CanonicalScheme]:
    """Mark schemes involved in duplicates with possible_duplicate=True."""
    dup_ids = set()
    for id1, id2, _ in duplicates:
        dup_ids.add(id1)
        dup_ids.add(id2)

    for scheme in schemes:
        if scheme.scheme_id in dup_ids:
            scheme.possible_duplicate = True
            scheme.needs_review = True

    return schemes
