# Environment & Configuration Reference

Single authoritative source for SchemeSetu configuration. Values are read by
`backend/app/core/config.py` (pydantic-settings) from the process environment and `backend/.env`.
Template: `backend/.env.example`. The frontend has exactly one variable.

**Secrets:** every backend variable is server-only. The backend never returns API keys, the database URL
or the reviewer key in any response. `/health` reports only booleans (`groq_configured`, …). Configuration
errors are reported to clients as "This service is not configured on the server." Details go to server logs
only.

## Backend

| Variable | Required | Default | Where it comes from | If missing / effect |
|---|---|---|---|---|
| `DATABASE_URL` | **Yes** (for real use) | — | Your PostgreSQL (local Docker or managed) | App starts; DB retrieval fails and is reported as a failed channel; rules cannot load, so no scheme can be ELIGIBLE (all UNVERIFIABLE); `/health` → `degraded` |
| `NEON_DATABASE_URL` | No | — | Legacy alias | Used only when `DATABASE_URL` is empty |
| `DB_MIN_SIZE` / `DB_MAX_SIZE` | No | 1 / 5 | — | Connection pool size |
| `GROQ_API_KEY` | **Yes** for conversations | — | console.groq.com | Assistant cannot understand free text: replies `LANGUAGE_SERVICE_UNAVAILABLE`. Replies fall back to deterministic text. Keyless demo: `scripts/demo_server.py` |
| `TAVILY_API_KEY` | No | — | tavily.com | Live web search reported as failed; DB + graph still answer (`partial_results`) |
| `SARVAM_API_KEY` | No | — | sarvam.ai | `/voice`, `/tts` return `CONFIGURATION_ERROR`; non-English text is passed untranslated |
| `ENVIRONMENT` | No | development | — | Shown in `/health`. `demo` is set only by the demo server |
| `LOG_LEVEL` | No | INFO | — | Logs never contain profile values or transcripts |
| `BACKEND_HOST` / `BACKEND_PORT` | No | 0.0.0.0 / 8000 | — | Used by `python -m app` |
| `GROQ_TIMEOUT` | No | 30 | — | Per-request LLM timeout (1 retry) |
| `SARVAM_TIMEOUT` | No | 30 | — | ASR/TTS/translation timeout |
| `DB_TIMEOUT` | No | 10 | — | Pool connection timeout |
| `DB_SEARCH_TIMEOUT` / `GRAPH_SEARCH_TIMEOUT` / `TAVILY_SEARCH_TIMEOUT` | No | 5 / 3 / 10 | — | Per-channel retrieval timeouts; a timed-out channel is reported and skipped |
| `MAX_DB_RESULTS` / `MAX_GRAPH_RESULTS` / `MAX_WEB_RESULTS` | No | 25 / 25 / 5 | — | Per-channel candidate caps |
| `MAX_CANDIDATES` | No | 25 | — | Candidates evaluated by the eligibility engine |
| `MAX_RESPONSE_SCHEMES` | No | 25 | — | Ranked schemes returned (the LLM rephrases only the top 10) |
| `RECENT_MESSAGES_WINDOW` | No | 10 | — | Conversation turns given to the LLM |
| `PROFILE_PRIORITY` | No | `["state","land_size_acres","primary_crop"]` | — | Fields asked before searching |
| `MAX_MESSAGE_CHARS` | No | 2000 | — | Longer messages → HTTP 422 |
| `MAX_AUDIO_SIZE_MB` | No | 10 | — | Larger uploads → `VALIDATION_ERROR` |
| `MAX_SESSIONS` | No | 1000 | — | In-memory conversations kept (about 300 KB each); oldest evicted |
| `REVIEW_API_KEY` | No | — | Generate: `python -c "import secrets; print(secrets.token_urlsafe(24))"` | Review API returns 403 (disabled) |
| `CORS_ORIGINS` | No | `["http://localhost:3000"]` | — | JSON list of allowed browser origins. Production: exact frontend origin, never `*` |

## Frontend

| Variable | Required | Default | Notes |
|---|---|---|---|
| `NEXT_PUBLIC_API_BASE_URL` | No | `http://localhost:8000` | **Public**: compiled into the browser bundle. It must be the backend URL as seen by the user's browser. Never put secrets in `NEXT_PUBLIC_*` variables |
| `NEXT_OUTPUT` | No | — | `standalone` only for the Docker image build |

## Development vs production

| Setting | Development | Production |
|---|---|---|
| `ENVIRONMENT` | development | production |
| `LOG_LEVEL` | INFO / DEBUG | INFO or WARNING |
| `DATABASE_URL` | local Docker Postgres | managed Postgres with TLS (`sslmode=require`) |
| `CORS_ORIGINS` | `["http://localhost:3000"]` | `["https://<your-frontend-domain>"]` |
| `REVIEW_API_KEY` | optional | set a long random value, or leave unset to disable the review API |
| `MAX_SESSIONS` | 1000 | size to available memory (about 300 KB per session) |
| Server | `python -m app --reload` | `uvicorn app.main:app --host 0.0.0.0 --port 8000` behind HTTPS |

## Audit performed (Phase 8)
- Every `Settings` field was checked for use. Three unused settings were removed (`FRONTEND_URL`,
  `API_TIMEOUT`, `TAVILY_TIMEOUT`). `GROQ_TIMEOUT` existed but was never applied, and is now passed to the
  Groq client.
- The frontend reads only `NEXT_PUBLIC_API_BASE_URL` (`frontend/src/lib/api.ts`). No secret reaches the browser.
- `.env`, `.env.*` and `backend/.env` are git-ignored. `.env.example` contains placeholders only. The red-team
  secret scan (A31) passes.
