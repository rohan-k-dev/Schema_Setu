# Phase 3 — Knowledge Graph Architecture

## Overview
The Knowledge Graph is a **derived representation** of scheme data stored in PostgreSQL.
PostgreSQL remains the **system of record**.

## Architecture
```
PostgreSQL (System of Record)
        |
        v
  Graph Builder (builder.py)
        |
        v
  NetworkX MultiDiGraph
        |
        v
  Graph Snapshot (JSON)
        |
        v
  Graph Repository (repository.py)
        |
        v
  KnowledgeGraphService
        |
        v
  SchemeService (merged candidates)
        |
   +---------+----------+
   |                     |
PostgreSQL Search   Graph Search
   |                     |
   +----------+----------+
              |
         Candidates
              |
          LangGraph
```

## Key Design Principles
1. **PostgreSQL is authoritative** — graph is always derived
2. **LangGraph ≠ Knowledge Graph** — separate concerns
3. **Read-only runtime** — graph snapshot loaded once at startup
4. **Graceful degradation** — if graph unavailable, DB search continues
5. **No LLM dependency** — graph is deterministic, built from structured data
6. **No network dependency** — graph build works offline

## Data Flow
```
Corpus → PostgreSQL → Graph Builder → NetworkX → JSON Snapshot → Runtime
```

## Class Responsibilities
| Class | Responsibility |
|-------|---------------|
| `KnowledgeGraphBuilder` | Builds graph from corpus/DB data |
| `KnowledgeGraphRepository` | Read-only query interface over graph |
| `KnowledgeGraphService` | Runtime service with graceful degradation |
| `GraphValidator` | Validates graph structure and DB consistency |
| `GraphCandidate` | Typed result model for graph-based discovery |
