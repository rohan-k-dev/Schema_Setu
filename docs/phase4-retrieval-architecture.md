# Phase 4 — Retrieval Architecture

## Overview

The retrieval subsystem performs parallel hybrid search across three sources:
PostgreSQL (canonical), Knowledge Graph (derived), and Tavily (live web).

## Retrieval Flow

```
RetrievalRequest (typed)
        │
        ├── DB Retriever (async, 5s timeout)
        │     └── SchemeRepository → List[RetrievalResult]
        │
        ├── Graph Retriever (async, 3s timeout)
        │     └── KnowledgeGraphService → List[RetrievalResult]
        │
        └── Web Retriever (async, 10s timeout)
              └── TavilySearchService → List[RetrievalResult]
        │
   asyncio.gather (parallel)
        │
        ▼
   Merger + Deduplicator
        │
        ▼
   Conflict Detector
        │
        ▼
   List[MergedCandidate]
```

## Parallel Execution

All three retrievers run simultaneously via `asyncio.gather`:

```python
db_result, graph_result, web_result = await asyncio.gather(
    _search_with_timeout(search_db(request), DB_TIMEOUT, "Database"),
    _search_with_timeout(search_graph(request), GRAPH_TIMEOUT, "Graph"),
    _search_with_timeout(search_web(request), WEB_TIMEOUT, "Web"),
)
```

## Source Trust Levels

| Source | Trust | Precedence |
|--------|-------|-----------|
| PostgreSQL | OFFICIAL | Canonical — never overridden |
| Knowledge Graph | OFFICIAL | Derived from canonical |
| Tavily (gov.in) | OFFICIAL/SECONDARY | Supplements DB |
| Tavily (other) | UNKNOWN | Lowest priority |

## Deduplication

Scheme IDs are normalized:
- `SCHEME:PM_KISAN` → `PM_KISAN`
- `pm_kisan` → `PM_KISAN`
- `pm-kisan` → `PM_KISAN`
- `WEB_CANDIDATE:abc123` → kept as-is

## Conflict Detection

When DB and Web disagree on a field (e.g., benefit amount):
1. Both values are recorded in `source_conflicts`
2. DB value takes precedence in the merged candidate
3. The conflict is available for audit/logging

## Timeouts

| Channel | Default Timeout |
|---------|----------------|
| PostgreSQL | 5 seconds |
| Knowledge Graph | 3 seconds |
| Tavily Web | 10 seconds |

## Candidate Limits

| Parameter | Default |
|-----------|---------|
| Max DB results | 10 |
| Max Graph results | 10 |
| Max Web results | 5 |
| Max merged candidates | 10 |
