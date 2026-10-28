# Phase 4 — Agentic Architecture

## Overview

Phase 4 transforms SchemeSetu from a linear pipeline into a multi-agent LangGraph architecture with parallel hybrid retrieval.

## Architecture Diagram

```
                     USER
                      │
                 text/voice
                      │
                      ▼
                FastAPI API
                      │
                      ▼
               ┌──────────────┐
               │  SUPERVISOR   │
               │  LANGGRAPH    │
               └──────┬───────┘
                      │
        ┌─────────────┼────────────────┐
        ▼                              ▼
  PROFILE AGENT                  CONTEXT HANDLER
        │
        ▼
  COMPLETENESS AGENT
       /          \
      /            \
 INCOMPLETE      COMPLETE
     │               │
     ▼               ▼
QUESTION AGENT   QUERY REWRITER
                      │
                      ▼
                RETRIEVAL AGENT
                      │
         ┌────────────┼────────────┐
         ▼            ▼            ▼
      PostgreSQL    Graph        Tavily
         │            │            │
         └────────────┼────────────┘
                      ▼
             NORMALIZE / MERGE
                      │
                      ▼
                DEDUPLICATE
                      │
                      ▼
                SOURCE CHECK
                      │
                      ▼
             RESPONSE FORMATTER
                      │
                      ▼
                Typed Response
                      │
                      ▼
                    USER
```

## LangGraph State

All data flows through `SchemeSetuState` (TypedDict):

| Field | Type | Owner |
|-------|------|-------|
| messages | List[BaseMessage] | append-only |
| profile | Dict | ProfileAgent |
| missing_fields | List[str] | CompletenessAgent |
| profile_complete | bool | CompletenessAgent |
| profile_conflicts | List[Dict] | ProfileAgent |
| contextual_query | str | QueryRewriter |
| query_intent | str | QueryRewriter |
| merged_candidates | List[Dict] | RetrievalAgent |
| response_text | str | ResponseFormatter |
| response_status | str | ResponseFormatter |

## Agent Responsibilities

### Profile Agent
- Extracts profile from conversation using structured LLM output
- Merges with existing profile (never erases known fields)
- Detects profile conflicts

### Completeness Agent
- Purely deterministic — no LLM
- Checks configurable priority fields
- Returns complete/incomplete status

### Question Agent
- Asks for ONE missing field at a time
- Handles conflict confirmations
- Handles clarification requests
- Falls back to template questions if LLM fails

### Query Rewriter
- Transforms follow-up messages into standalone queries
- Resolves contextual references ("the second one")
- Classifies query intent
- Detects ambiguous references

### Retrieval Agent
- Orchestrates parallel retrieval via asyncio.gather
- Per-channel timeouts
- Normalizes, merges, deduplicates results
- Detects source conflicts

### Response Formatter
- Generates user-facing text from structured candidates
- Strict grounding (never fabricates)
- Deterministic fallback if LLM fails

## Routing Logic

All routing is deterministic (no LLM):

1. After completeness check:
   - Profile conflicts → question_agent
   - Incomplete → question_agent
   - Complete → query_rewriter

2. After query rewrite:
   - Needs clarification → question_agent
   - Clear → retrieval_agent

## Files

| File | Purpose |
|------|---------|
| `backend/app/graph/state.py` | SchemeSetuState definition |
| `backend/app/graph/workflow.py` | LangGraph graph construction |
| `backend/app/graph/routing.py` | Deterministic routing functions |
| `backend/app/agents/profile_agent.py` | Profile extraction |
| `backend/app/agents/completeness_agent.py` | Completeness check |
| `backend/app/agents/question_agent.py` | Follow-up questions |
| `backend/app/agents/query_rewriter.py` | Query rewriting |
| `backend/app/agents/retrieval_agent.py` | Parallel retrieval |
| `backend/app/agents/response_formatter.py` | Response generation |
| `backend/app/retrieval/models.py` | Typed retrieval models |
| `backend/app/retrieval/db_retriever.py` | PostgreSQL retriever |
| `backend/app/retrieval/graph_retriever.py` | Knowledge Graph retriever |
| `backend/app/retrieval/web_retriever.py` | Tavily retriever |
| `backend/app/retrieval/merger.py` | Candidate merge/dedup |
| `backend/app/retrieval/deduplicator.py` | Identity normalization |
| `backend/app/retrieval/conflict_detector.py` | Source conflict detection |
