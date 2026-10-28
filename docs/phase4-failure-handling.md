# Phase 4 — Failure Handling

## Design Principle

SchemeSetu uses graceful degradation: if any retrieval source fails, the system continues with the remaining sources rather than returning an error.

## Failure Scenarios

### Single Source Failure

| Failed Source | Behavior |
|---------------|----------|
| PostgreSQL down | Graph + Web results still provided |
| Knowledge Graph unavailable | DB + Web results still provided |
| Tavily down | DB + Graph results still provided |

### Partial Failure Response

When some sources fail:
- `response_status = "partial_results"`
- `retrieval_metadata.retrieval_success` shows which sources succeeded
- No tracebacks or error details shown to user

### Total Failure

When ALL retrieval sources fail:
- Safe fallback message: "I could not find matching schemes in the available sources."
- No hallucinated schemes
- No fabricated data

### LLM Failure

| Component | Fallback |
|-----------|----------|
| Profile Extraction | Keep existing profile unchanged |
| Question Generation | Use deterministic template questions |
| Query Rewriting | Use original query + keyword intent detection |
| Response Formatting | Use deterministic structured response |

## Timeout Configuration

```
DB_SEARCH_TIMEOUT = 5 seconds
GRAPH_SEARCH_TIMEOUT = 3 seconds
TAVILY_SEARCH_TIMEOUT = 10 seconds
GROQ_TIMEOUT = 30 seconds
```

Each retrieval channel has its own timeout. A timeout is treated identically to a failure — the channel returns empty results.

## Error Tracking

Errors are tracked in `retrieval_errors` state field:
```json
{
  "database": null,
  "knowledge_graph": "TIMEOUT after 3.0s",
  "live_web": null
}
```

## Security Failures

| Threat | Protection |
|--------|-----------|
| SQL injection | Repository layer uses parameterized queries |
| Graph injection | KG service uses structured queries, not raw user input |
| Web prompt injection | Web content treated as data, never as instructions |
| API key exposure | Keys never included in responses or logs |

## Recovery

The system does not auto-retry failed sources within a single request (to stay within latency budget). Users can simply send another message to trigger fresh retrieval.
