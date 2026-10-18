"""
Corpus Loader — filesystem-based scheme corpus adapter.

Loads the validated corpus into memory for runtime use.
This is NOT the database repository — it's a file-based adapter.
Read-only after initialization (thread-safe for FastAPI).

Provides basic deterministic search by:
- scheme_id
- scheme name / alias
- state
- crop
"""

import json
import os
from typing import List, Optional, Dict, Any
from functools import lru_cache

from app.ingestion import CanonicalScheme
from app.core.logging import get_logger

logger = get_logger(__name__)

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
DEFAULT_CORPUS_PATH = os.path.join(PROJECT_ROOT, "data", "validated", "schemes.json")


class SchemeCorpusLoader:
    """
    In-memory corpus loader for runtime scheme search.

    Thread-safe: loaded once at startup, read-only thereafter.
    """

    def __init__(self, corpus_path: str = DEFAULT_CORPUS_PATH):
        self._schemes: List[CanonicalScheme] = []
        self._by_id: Dict[str, CanonicalScheme] = {}
        self._loaded = False
        self._corpus_path = corpus_path

    def load(self) -> int:
        """
        Load the validated corpus from disk.
        Returns the number of schemes loaded.
        """
        if not os.path.exists(self._corpus_path):
            logger.warning(f"Corpus file not found: {self._corpus_path}. Local search unavailable.")
            self._loaded = True
            return 0

        try:
            with open(self._corpus_path, "r", encoding="utf-8") as f:
                data = json.load(f)

            self._schemes = [CanonicalScheme(**item) for item in data]
            self._by_id = {s.scheme_id: s for s in self._schemes}
            self._loaded = True

            logger.info(f"Corpus loaded: {len(self._schemes)} schemes from {self._corpus_path}")
            return len(self._schemes)

        except Exception as e:
            logger.error(f"Failed to load corpus: {e}")
            self._loaded = True
            return 0

    @property
    def is_loaded(self) -> bool:
        return self._loaded

    @property
    def scheme_count(self) -> int:
        return len(self._schemes)

    def get_by_id(self, scheme_id: str) -> Optional[CanonicalScheme]:
        """Retrieve a scheme by its stable ID."""
        return self._by_id.get(scheme_id.upper())

    def search_by_name(self, query: str) -> List[CanonicalScheme]:
        """Search schemes by name or alias (case-insensitive, substring)."""
        query_lower = query.lower().strip()
        results = []
        for scheme in self._schemes:
            # Check name
            if query_lower in scheme.name.lower():
                results.append(scheme)
                continue
            # Check short_name
            if scheme.short_name and query_lower in scheme.short_name.lower():
                results.append(scheme)
                continue
            # Check aliases
            if any(query_lower in alias.lower() for alias in scheme.aliases):
                results.append(scheme)
                continue
        return results

    def search_by_state(self, state: str) -> List[CanonicalScheme]:
        """
        Search schemes applicable to a given state.

        Includes:
        - Schemes explicitly listing the state
        - Central schemes with no state restrictions (applicable_states=None)
        """
        state_lower = state.lower().strip()
        results = []
        for scheme in self._schemes:
            # Central schemes with no state restrictions
            if scheme.applicable_states is None:
                results.append(scheme)
                continue
            # Check if state is in applicable states
            if any(s.lower() == state_lower for s in scheme.applicable_states):
                results.append(scheme)
        return results

    def search_by_crop(self, crop: str) -> List[CanonicalScheme]:
        """
        Search schemes applicable to a given crop.

        Includes:
        - Schemes explicitly listing the crop
        - Schemes with no crop restrictions (applicable_crops=None)
        """
        crop_lower = crop.lower().strip()
        results = []
        for scheme in self._schemes:
            if scheme.applicable_crops is None:
                results.append(scheme)
                continue
            if any(c.lower() == crop_lower for c in scheme.applicable_crops):
                results.append(scheme)
        return results

    def search(
        self,
        state: Optional[str] = None,
        crop: Optional[str] = None,
        query: Optional[str] = None,
    ) -> List[CanonicalScheme]:
        """
        Combined search with optional filters.
        Intersects results when multiple filters are provided.
        """
        candidates = set(range(len(self._schemes)))

        if state:
            state_matches = {
                i for i, s in enumerate(self._schemes)
                if s.applicable_states is None
                or any(st.lower() == state.lower().strip() for st in s.applicable_states)
            }
            candidates &= state_matches

        if crop:
            crop_matches = {
                i for i, s in enumerate(self._schemes)
                if s.applicable_crops is None
                or any(c.lower() == crop.lower().strip() for c in s.applicable_crops)
            }
            candidates &= crop_matches

        if query:
            query_lower = query.lower().strip()
            name_matches = set()
            for i, s in enumerate(self._schemes):
                if query_lower in s.name.lower():
                    name_matches.add(i)
                elif s.short_name and query_lower in s.short_name.lower():
                    name_matches.add(i)
                elif any(query_lower in alias.lower() for alias in s.aliases):
                    name_matches.add(i)
            candidates &= name_matches

        return [self._schemes[i] for i in sorted(candidates)]

    def get_all(self) -> List[CanonicalScheme]:
        """Return all schemes in the corpus."""
        return list(self._schemes)

    def to_dicts(self, schemes: Optional[List[CanonicalScheme]] = None) -> List[Dict[str, Any]]:
        """Convert schemes to dicts for API responses (backward compatible)."""
        target = schemes or self._schemes
        results = []
        for s in target:
            results.append({
                "title": s.name,
                "scheme_id": s.scheme_id,
                "ministry": s.ministry or "",
                "benefits_details": "; ".join(b.description for b in s.benefits) if s.benefits else "",
                "eligibility_criteria_raw": s.eligibility_summary or "",
                "state_specific": ", ".join(s.applicable_states) if s.applicable_states else "All India",
                "application_link": s.application_url or s.official_url or "",
                "source": "local_corpus",
            })
        return results


# Singleton instance
_corpus_loader: Optional[SchemeCorpusLoader] = None


def get_corpus_loader() -> SchemeCorpusLoader:
    """Get or create the singleton corpus loader."""
    global _corpus_loader
    if _corpus_loader is None:
        _corpus_loader = SchemeCorpusLoader()
        _corpus_loader.load()
    return _corpus_loader
