"""
Knowledge Graph Service — runtime graph service for the application.

Loads the graph at startup, exposes typed query methods,
and provides graceful degradation if graph is unavailable.

Does NOT:
    - Call Groq/Tavily/Sarvam
    - Evaluate eligibility
    - Mutate the graph
"""

from typing import List, Optional, Dict, Any

from app.knowledge_graph.repository import KnowledgeGraphRepository, GraphCandidate
from app.knowledge_graph.serializer import load_graph_snapshot
from app.core.logging import get_logger

logger = get_logger(__name__)

# Module-level singleton
_graph_repo: Optional[KnowledgeGraphRepository] = None
_graph_available: bool = False
_graph_stale: bool = False


def init_knowledge_graph() -> bool:
    """
    Initialize the Knowledge Graph at application startup.

    Returns True if graph was loaded successfully, False otherwise.
    Does NOT crash the app if graph is unavailable (§102, §103).
    """
    global _graph_repo, _graph_available, _graph_stale

    try:
        graph, metadata = load_graph_snapshot()
        _graph_repo = KnowledgeGraphRepository(graph, metadata)
        _graph_available = True
        _graph_stale = False

        logger.info(
            f"Knowledge Graph loaded: {_graph_repo.node_count} nodes, "
            f"{_graph_repo.edge_count} edges, "
            f"corpus v{_graph_repo.corpus_version}"
        )
        return True

    except FileNotFoundError as e:
        logger.warning(f"Knowledge Graph not available: {e}")
        _graph_available = False
        return False
    except Exception as e:
        logger.error(f"Knowledge Graph load error: {e}")
        _graph_available = False
        return False


def is_graph_available() -> bool:
    """Check if the Knowledge Graph is loaded and available."""
    return _graph_available


def is_graph_stale() -> bool:
    """Check if the loaded graph is stale (older than DB corpus)."""
    return _graph_stale


def mark_graph_stale():
    """Mark the graph as stale (called when DB corpus version doesn't match)."""
    global _graph_stale
    _graph_stale = True
    logger.warning("Knowledge Graph marked as stale.")


def get_graph_repo() -> Optional[KnowledgeGraphRepository]:
    """Get the graph repository (may be None if not available)."""
    return _graph_repo


def graph_health_check() -> dict:
    """Graph health check for the /health endpoint."""
    if not _graph_available or not _graph_repo:
        return {"loaded": False, "stale": False}
    result = _graph_repo.health_check()
    result["stale"] = _graph_stale
    return result


# ─── Typed query methods (§46) ───────────────────────────────

def find_graph_candidates(profile: dict) -> List[GraphCandidate]:
    """
    Find candidate schemes from the Knowledge Graph for a user profile.

    Returns empty list if graph is unavailable (graceful degradation).
    """
    if not _graph_available or not _graph_repo:
        return []

    try:
        candidates = _graph_repo.find_candidates_for_profile(profile)
        logger.info(f"Graph returned {len(candidates)} candidates")
        return candidates
    except Exception as e:
        logger.error(f"Graph query error: {e}")
        return []


def find_schemes_by_state(state: str) -> List[str]:
    """Find scheme IDs for a state."""
    if not _graph_available or not _graph_repo:
        return []
    return sorted(_graph_repo.find_schemes_for_state(state))


def find_schemes_by_crop(crop: str) -> List[str]:
    """Find scheme IDs for a crop."""
    if not _graph_available or not _graph_repo:
        return []
    return sorted(_graph_repo.find_schemes_for_crop(crop))


def find_schemes_by_state_and_crop(state: str, crop: str) -> List[str]:
    """Find scheme IDs for state + crop intersection."""
    if not _graph_available or not _graph_repo:
        return []
    return sorted(_graph_repo.find_schemes_for_state_and_crop(state, crop))


def get_scheme_graph_info(scheme_id: str) -> Optional[dict]:
    """Get graph information for a scheme (for debugging/API)."""
    if not _graph_available or not _graph_repo:
        return None

    node = _graph_repo.get_scheme_node(scheme_id)
    if not node:
        return None

    return {
        "scheme_id": scheme_id,
        "states": _graph_repo.get_related_states(scheme_id),
        "crops": _graph_repo.get_related_crops(scheme_id),
        "documents": _graph_repo.get_related_documents(scheme_id),
        "rules_count": len(_graph_repo.get_related_rules(scheme_id)),
        "sources_count": len(_graph_repo.get_related_sources(scheme_id)),
    }
