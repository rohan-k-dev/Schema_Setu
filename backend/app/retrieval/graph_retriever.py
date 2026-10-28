"""
Graph Retriever — Knowledge Graph scheme search via KG service.

Uses existing KnowledgeGraphService (§30). Does NOT access NetworkX directly.
Returns List[RetrievalResult] with source_type=KNOWLEDGE_GRAPH.
"""

from typing import List
from datetime import datetime, timezone

from app.retrieval.models import RetrievalResult, RetrievalRequest, SourceType, SourceTrust
from app.core.logging import get_logger
from app.core.config import settings

logger = get_logger(__name__)


async def search_graph(request: RetrievalRequest) -> List[RetrievalResult]:
    """
    Search the Knowledge Graph for candidate schemes.

    Uses structured profile fields — never feeds free-form text (§104).
    Raises when the graph is unavailable so the retrieval agent records the
    channel as failed and degrades to DB/web (§75, Phase 7 BUG-008).
    """
    from app.services.knowledge_graph_service import is_graph_available, find_graph_candidates

    if not is_graph_available():
        raise RuntimeError("Knowledge Graph unavailable")

    now = datetime.now(timezone.utc).isoformat()
    results: List[RetrievalResult] = []

    # Build profile dict for graph query (structured fields only)
    profile_for_graph = {}
    if request.state:
        profile_for_graph["state"] = request.state
    if request.crop:
        profile_for_graph["primary_crop"] = request.crop
    if request.district:
        profile_for_graph["district"] = request.district
    if request.category:
        profile_for_graph["category"] = request.category
    if request.gender:
        profile_for_graph["gender"] = request.gender
    if request.occupation:
        profile_for_graph["occupation"] = request.occupation

    if not profile_for_graph:
        logger.info("No structured fields for graph search, skipping.")
        return []

    candidates = find_graph_candidates(profile_for_graph)
    max_results = settings.MAX_GRAPH_RESULTS

    for c in candidates[:max_results]:
        results.append(RetrievalResult(
            source_type=SourceType.KNOWLEDGE_GRAPH,
            source_id=f"graph:{c.scheme_id}",
            scheme_id=c.scheme_id,
            title=c.scheme_name,
            source_name="SchemeSetu Knowledge Graph",
            source_trust=SourceTrust.OFFICIAL,
            retrieved_at=now,
            evidence={
                "matched_relations": c.matched_relations,
                "matched_nodes": c.matched_nodes,
                "graph_match_score": c.graph_match_score,
            },
        ))

    logger.info(f"Graph search returned {len(results)} candidates.")
    return results
