"""
Merger — merges and deduplicates retrieval results from all sources.

Deduplicates by scheme_id (§38–39, §146).
DB data is canonical and takes precedence over web (§37, §40).
Graph provides relationship evidence.
Carries provenance for every merged candidate (§42).
"""

from typing import List, Dict, Tuple

from app.retrieval.models import (
    RetrievalResult,
    MergedCandidate,
    SourceRecord,
    SourceConflict,
    SourceType,
)
from app.retrieval.deduplicator import normalize_scheme_id
from app.retrieval.conflict_detector import detect_conflicts
from app.core.logging import get_logger
from app.core.config import settings

logger = get_logger(__name__)


def merge_results(
    db_results: List[RetrievalResult],
    graph_results: List[RetrievalResult],
    web_results: List[RetrievalResult],
) -> Tuple[List[MergedCandidate], List[SourceConflict]]:
    """
    Merge and deduplicate results from all sources (§38).

    Priority:
    1. DB canonical data (never overridden by web) (§40)
    2. Graph relationship evidence
    3. Web supplementary information

    Returns:
    - List of MergedCandidates (sorted deterministically §147)
    - List of SourceConflicts detected
    """
    # Index by normalized scheme_id
    candidates: Dict[str, MergedCandidate] = {}
    # Track raw results per scheme for conflict detection
    raw_by_scheme: Dict[str, Dict[str, RetrievalResult]] = {}
    all_conflicts: List[SourceConflict] = []

    # 1. Process DB results first (canonical) (§40)
    for r in db_results:
        sid = normalize_scheme_id(r.scheme_id or "")
        if not sid:
            continue

        candidates[sid] = MergedCandidate(
            candidate_id=f"candidate:{sid}",
            scheme_id=sid,
            name=r.title,
            description=r.description,
            benefit_summary=r.benefits,
            eligibility_summary=r.eligibility_summary,
            documents=r.documents,
            application_steps=r.application_steps,
            official_url=r.official_url,
            retrieval_sources=[SourceType.DATABASE],
            matched_fields=list((r.evidence or {}).get("targeting", [])),
            scheme_meta=(r.evidence or {}).get("scheme_meta"),
            source_records=[SourceRecord(
                source_name=r.source_name,
                source_url=r.source_url or r.official_url,
                source_type=SourceType.DATABASE,
                source_trust=r.source_trust,
            )],
        )
        raw_by_scheme.setdefault(sid, {})[SourceType.DATABASE.value] = r

    # 2. Process Graph results (relationship evidence)
    for r in graph_results:
        sid = normalize_scheme_id(r.scheme_id or "")
        if not sid:
            continue

        evidence = r.evidence or {}
        matched_relations = evidence.get("matched_relations", [])
        matched_nodes = evidence.get("matched_nodes", [])

        if sid in candidates:
            # Enhance existing DB candidate
            candidates[sid].retrieval_sources.append(SourceType.KNOWLEDGE_GRAPH)
            candidates[sid].graph_evidence = matched_nodes
            candidates[sid].matched_fields.extend(matched_relations)
            candidates[sid].source_records.append(SourceRecord(
                source_name=r.source_name,
                source_type=SourceType.KNOWLEDGE_GRAPH,
                source_trust=r.source_trust,
            ))
        else:
            # Graph-only candidate (no DB data)
            candidates[sid] = MergedCandidate(
                candidate_id=f"candidate:{sid}",
                scheme_id=sid,
                name=r.title or sid,
                retrieval_sources=[SourceType.KNOWLEDGE_GRAPH],
                matched_fields=matched_relations,
                graph_evidence=matched_nodes,
                source_records=[SourceRecord(
                    source_name=r.source_name,
                    source_type=SourceType.KNOWLEDGE_GRAPH,
                    source_trust=r.source_trust,
                )],
            )
        raw_by_scheme.setdefault(sid, {})[SourceType.KNOWLEDGE_GRAPH.value] = r

    # 3. Process Web results (supplementary)
    for r in web_results:
        sid = normalize_scheme_id(r.scheme_id or "")

        if sid and sid in candidates:
            # Web matches an existing candidate — add source, detect conflicts
            if SourceType.LIVE_WEB not in candidates[sid].retrieval_sources:
                candidates[sid].retrieval_sources.append(SourceType.LIVE_WEB)
            candidates[sid].source_records.append(SourceRecord(
                source_name=r.source_name,
                source_url=r.source_url,
                source_type=SourceType.LIVE_WEB,
                source_trust=r.source_trust,
            ))
            raw_by_scheme.setdefault(sid, {})[SourceType.LIVE_WEB.value] = r
        elif sid:
            # Web-only candidate (not in DB or Graph)
            candidates[sid] = MergedCandidate(
                candidate_id=f"candidate:{sid}",
                scheme_id=sid,
                name=r.title or "",
                description=r.description,
                benefit_summary=r.benefits,
                official_url=r.source_url,
                retrieval_sources=[SourceType.LIVE_WEB],
                source_records=[SourceRecord(
                    source_name=r.source_name,
                    source_url=r.source_url,
                    source_type=SourceType.LIVE_WEB,
                    source_trust=r.source_trust,
                )],
            )
            raw_by_scheme.setdefault(sid, {})[SourceType.LIVE_WEB.value] = r

    # 4. Detect source conflicts (§76)
    for sid, sources in raw_by_scheme.items():
        conflicts = detect_conflicts(sid, sources)
        if conflicts:
            all_conflicts.extend(conflicts)
            if sid in candidates:
                candidates[sid].source_conflicts = conflicts

    # 5. Validate: every candidate must have stable identity + at least one source (§194)
    valid_candidates = [
        c for c in candidates.values()
        if c.scheme_id and len(c.retrieval_sources) > 0
    ]

    # 6. Sort deterministically (§147, §108)
    sorted_candidates = _sort_candidates(valid_candidates)

    # 7. Apply candidate limit (§195)
    max_candidates = settings.MAX_CANDIDATES
    final = sorted_candidates[:max_candidates]

    logger.info(
        f"Merged {len(db_results)} DB + {len(graph_results)} Graph + "
        f"{len(web_results)} Web → {len(final)} candidates, "
        f"{len(all_conflicts)} conflicts"
    )

    return final, all_conflicts


def _sort_candidates(candidates: List[MergedCandidate]) -> List[MergedCandidate]:
    """
    Sort candidates deterministically (§108, §147).

    Priority:
    1. Targeted at the user's state/crop (most specific first — Phase 7 BUG-006)
    2. More retrieval sources (multi-source evidence)
    3. DB presence (canonical)
    4. Graph evidence count
    5. Scheme ID (stable tiebreaker)
    """
    def sort_key(c: MergedCandidate):
        targeted = sum(1 for f in c.matched_fields if f in ("state_targeted", "crop_targeted"))
        has_db = 1 if SourceType.DATABASE in c.retrieval_sources else 0
        has_graph = 1 if SourceType.KNOWLEDGE_GRAPH in c.retrieval_sources else 0
        evidence_count = len(c.graph_evidence or [])
        source_count = len(c.retrieval_sources)
        return (-targeted, -source_count, -has_db, -has_graph, -evidence_count, c.scheme_id)

    return sorted(candidates, key=sort_key)
