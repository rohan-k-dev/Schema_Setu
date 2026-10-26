# Phase 6 — Performance

## Performance Breakdown Fields (§103)

The system tracks the following latency components:

| Field | Description |
|-------|-------------|
| profile_ms | Profile extraction time |
| query_ms | Query rewriting/context resolution |
| db_ms | PostgreSQL scheme search |
| graph_ms | Knowledge Graph traversal |
| tavily_ms | Tavily web search |
| eligibility_ms | Rule evaluation engine |
| xai_ms | Explanation generation |
| translation_ms | Sarvam translate (both directions) |
| tts_ms | Sarvam TTS generation |
| total_ms | End-to-end request time |

## Target (§166)

Review-II SRS target: **10–15 seconds** for results using parallel search.
Voice has separate end-to-end latency due to ASR + TTS overhead.

## Architecture Optimizations

1. **Parallel retrieval**: DB, Graph, Web search run concurrently
2. **Deterministic eligibility**: No LLM call needed — pure rule evaluation
3. **Template-based XAI**: No LLM call — template string generation
4. **Connection pooling**: PostgreSQL pool (1–5 connections)
5. **Configurable timeouts**: Each external service has independent timeout

## Configured Timeouts (§97)

| Service | Timeout | Config Key |
|---------|---------|------------|
| Groq LLM | 30s | GROQ_TIMEOUT |
| Tavily Web | 15s | TAVILY_TIMEOUT |
| Sarvam ASR/TTS/Translate | 30s | SARVAM_TIMEOUT |
| PostgreSQL | 10s | DB_TIMEOUT |
| DB Search | 5s | DB_SEARCH_TIMEOUT |
| Graph Search | 3s | GRAPH_SEARCH_TIMEOUT |
| Tavily Search | 10s | TAVILY_SEARCH_TIMEOUT |

## Known Bottlenecks

1. **LLM inference** (Groq): typically 2–5s per call
2. **Sarvam ASR**: typically 2–4s for short utterances
3. **Sarvam TTS**: typically 1–3s
4. **Translation**: typically 0.5–2s per direction

## Notes

- All performance numbers must come from actual tests (§104)
- Do not claim targets achieved without measurement (§104)
- Retry policy: at most one retry for transient failures (§98)
