# SchemeSetu AI 🌾

**AI-powered government scheme discovery for Indian farmers.**

SchemeSetu ("Bridge to Schemes") is a multilingual AI assistant that helps rural Indian farmers discover government schemes they're eligible for. It uses voice input in native languages, an intelligent conversational agent, and text-to-speech to make government benefits accessible to everyone.

## Current Implementation (Phase 0 → Phase 8 + farmer accounts, v1.0.0)

### Phase 0 — Core Platform
- ✅ Conversational scheme discovery via text and voice
- ✅ Profile extraction using Groq LLM structured output (originally LLaMA 3.3; now `GROQ_MODEL`)
- ✅ Deterministic multi-turn profile gathering
- ✅ Web scheme search via Tavily
- ✅ Voice input via Sarvam ASR (speech-to-text)
- ✅ Voice output via Sarvam TTS (text-to-speech)
- ✅ Clean component-based React frontend
- ✅ Centralized configuration & structured error handling

### Phase 1 — Corpus Engineering
- ✅ Validated canonical scheme corpus (40 schemes)
- ✅ Structured eligibility rules, benefits, documents
- ✅ Source provenance tracking
- ✅ Deduplication and review pipeline

### Phase 2 — PostgreSQL Persistence
- ✅ Normalized relational schema (15 tables)
- ✅ Alembic migration system
- ✅ Transactional, idempotent corpus importer
- ✅ Repository layer (SQL isolated from application)
- ✅ Structured scheme search (by state, crop, name, alias)
- ✅ Full scheme detail retrieval with all child records
- ✅ Database health checks and integrity verification

### Phase 3 — Knowledge Graph
- ✅ NetworkX MultiDiGraph with 179 nodes, 356 edges
- ✅ 15 node types (Scheme, State, District, Crop, Beneficiary, Category, etc.)
- ✅ 17 edge types (APPLIES_TO_STATE, TARGETS_CROP, REQUIRES_DOCUMENT, etc.)
- ✅ Deterministic, reproducible graph builds from corpus
- ✅ Graph validation and coverage metrics
- ✅ Profile-based candidate discovery with match evidence
- ✅ Graph snapshot persistence (JSON) with versioning
- ✅ Graceful degradation (DB search works if graph unavailable)

### Phase 4 — Agentic Orchestration & Hybrid Retrieval
- ✅ LangGraph multi-agent supervisor architecture
- ✅ Profile Agent (structured extraction, merge, conflict detection)
- ✅ Completeness Agent (deterministic, no LLM)
- ✅ Question Agent (priority-based, conflict confirmation, template fallback)
- ✅ Query Rewriter (contextual reference resolution, intent classification)
- ✅ Retrieval Agent (parallel DB + Graph + Web via asyncio.gather)
- ✅ Response Formatter (LLM with strict grounding, deterministic fallback)
- ✅ Candidate normalization, deduplication, and source conflict detection
- ✅ Per-channel retrieval timeouts
- ✅ Partial failure graceful degradation
- ✅ Typed retrieval models and response contracts
- ✅ Session isolation via unique thread IDs
- ✅ Voice + text use same LangGraph workflow
- ✅ Versioned prompt system

### Phase 5 — Deterministic Eligibility Engine
- ✅ Deterministic rule evaluation engine (11 operators)
- ✅ Three-valued logic (PASS/FAIL/UNKNOWN) with AND/OR groups
- ✅ 4 eligibility statuses: ELIGIBLE, NOT_ELIGIBLE, NEEDS_MORE_INFORMATION, UNVERIFIABLE
- ✅ Field normalization (state, crop, category, gender, numeric with lakh/crore)
- ✅ Conflict detection (contradictory rule bounds → UNVERIFIABLE)
- ✅ Evidence-based XAI explanations (deterministic templates)
- ✅ Explanation validation (no contradictions with engine status)
- ✅ Deterministic recommendation ranking (no ML, no probability)
- ✅ LangGraph integration (eligibility_agent + recommendation_agent nodes)
- ✅ Golden test dataset (30 cases, 100% accuracy)
- ✅ Eligibility status display on frontend scheme cards
- ✅ CLI evaluation script with quality reporting
- ✅ 342 tests passing (all phases)

### Phase 6 — Multilingual Voice, Accessibility & Human Review
- ✅ Centralized language registry (11 Indian languages)
- ✅ Translation service (Sarvam Translate API integration)
- ✅ Language-aware ASR with typed ASRResult output
- ✅ Language-aware TTS with auto-resolution
- ✅ Language selector (mobile-friendly, native names, ARIA)
- ✅ Multilingual chat API (translate → LangGraph → translate back)
- ✅ Multilingual voice API (ASR → translate → LangGraph → translate → TTS)
- ✅ Text + Voice use SAME LangGraph pipeline (single intelligence)
- ✅ Human-in-the-loop review queue with deterministic escalation triggers
- ✅ Review case lifecycle (PENDING → IN_REVIEW → RESOLVED/DISMISSED)
- ✅ Reviewer API with typed actions, audit logging, status transitions
- ✅ Sensitive field stripping (no Aadhaar in review cases)
- ✅ Accessibility: 44px touch targets, ARIA labels, screen reader support
- ✅ Voice state machine (IDLE/RECORDING/UPLOADING/TRANSCRIBING/PROCESSING)
- ✅ Expandable scheme cards (documents, steps, source links)
- ✅ Responsive layout (mobile/tablet/desktop)
- ✅ Browser compatibility (WebM/OGG/WAV detection)
- ✅ Graceful degradation (mic denied → text, TTS fail → text, Tavily fail → DB+Graph)

### Phase 7 — Evaluation, Red-Team & Hardening
- Phase 6 gate audit found that the backend could not even import in the dev environment, and that
  human-review escalation was never wired in. Both were fixed first ([gate audit](docs/phase7-phase6-gate-audit.md)).
- Evaluation framework in `evaluation/`: 11 golden datasets (≈400 cases), offline fixtures for every external
  service, 15 runners, and `scripts/run_evaluation.py` (`--offline` / `--live`).
- MEASURE → FIX → RE-MEASURE: **35 bugs** found and fixed, each with a regression test
  ([bug register](docs/phase7-bug-register.md)). Baseline scorecard 19 PASS / 8 PARTIAL / 18 FAIL → after
  **47 PASS / 0 FAIL**, with 6 metrics honestly `NOT_MEASURED`: live LLM extraction, live latency, Sarvam
  quality, WER, user study, expert review ([final scorecard](docs/phase7-final-scorecard.md)).
- At the end of Phase 7: 484 backend tests passed; frontend build clean; offline smoke test 19/19.

### Phase 8 — Final Delivery
- ✅ Real PostgreSQL end to end (Docker Compose: database, migrations + corpus import, backend, frontend)
- ✅ Demo mode without API keys (`scripts/demo_server.py`), smoke test, real-DB benchmarks, screenshots
- ✅ Configurable Groq model (`GROQ_MODEL`), after the live run of 2026-10-18 with real keys

### Farmer Accounts, Profile & Dashboard (optional sign-in)
- ✅ Secure accounts: Argon2id passwords, HttpOnly cookie sessions, CSRF tokens,
  password reset, lockout and rate limits ([docs/AUTH.md](docs/AUTH.md))
- ✅ Saved farmer profile with land units, income ranges and conflict-safe edits; used by chat with consent
  ([docs/PROFILE.md](docs/PROFILE.md))
- ✅ Personal dashboard: eligibility for every scheme from the saved profile (deterministic engine only),
  missing/conflicting details, stale-result notice, saved schemes, search history
  ([docs/DASHBOARD.md](docs/DASHBOARD.md))
- ✅ Saved schemes with an application checklist (documents, preparation, official steps, submission,
  acknowledgement, own milestones). Progress is user-reported, tied to the scheme version and kept when the
  scheme data changes ([docs/SAVED_SCHEMES.md](docs/SAVED_SCHEMES.md))
- ✅ Role-based access control (FARMER / REVIEWER / ADMIN), deny by default, enforced in routes and services;
  admin account management, scheme curation flags and an append-only audit log ([docs/RBAC.md](docs/RBAC.md))
- ✅ Administrator operations dashboard (`/admin`): health, corpus, ingestion jobs, graph sync, reviews, recent
  errors; validation, conflict inspection, safe import / graph-rebuild jobs; hash-chained audit trail with
  correlation ids ([docs/ADMIN_OPERATIONS.md](docs/ADMIN_OPERATIONS.md))
- ✅ Privacy and data settings (`/privacy`): every profile field with required / optional, purpose, storage and
  external sharing; external processors (Groq, Tavily, Sarvam, e-mail, SMS) disclosed without claiming local
  processing; view, export (JSON), delete by category, withdraw consent, delete the account; retention purge and
  documented exceptions ([docs/PRIVACY.md](docs/PRIVACY.md))
- ✅ Reviewer dashboard (`/review`) for cases raised by unverifiable results, rule / source conflicts or failed
  retrieval: evidence, source URLs, conflicting values and a minimal profile; status / reason / assignment
  filters; take, comment, request verification, approve / reject / mark unverifiable / resolve, dismiss;
  versioned (no double decisions) and audited. Only admin-approved reviewers, only their assigned or explicitly
  granted cases (others: 404), summaries for the queue, audited views, shorter staff sessions and password
  re-entry for decisions. Decisions never change automated results or rules; farmers see
  open checks as unconfirmed and the outcome on their dashboard ([docs/HUMAN_REVIEW.md](docs/HUMAN_REVIEW.md))
- ✅ Scheme-update notifications: a newly scraped corpus is compared with the verified one (cosmetic
  differences ignored); every change waits for an administrator's approval, consequential ones need explicit
  confirmation; only published changes notify farmers who saved or follow the scheme — in-app, e-mail (SMTP)
  and SMS (configured provider, verified phone, consent, opt-out), once each, with retries and delivery
  status ([docs/SCHEME_UPDATES.md](docs/SCHEME_UPDATES.md))

### Real-Time Scheme Verification
- Every scheme question also searches official government websites (national portals, ministries, the farmer's state; Tavily) and re-reads the official pages of the top stored schemes, within a time budget
- robots.txt, rate limits and access controls respected (CAPTCHA, login, 403 and TLS failures are reported, never bypassed); HTML and PDF
- Each scheme is labelled **Verified live**, **checked earlier**, or **stored** (with the reason and date), with source links and retrieval times; conflicts with stored records go to human review; eligibility stays on stored rules
- Provenance snapshots keep the last known-good extraction and classify changes (new, updated, incomplete, unparseable, missing) — see [docs/LIVE_VERIFICATION.md](docs/LIVE_VERIFICATION.md)

### Eligible Schemes & Relevant Alternatives
- Answers keep **Eligible Schemes** (exactly the deterministic engine's ELIGIBLE results) and add **More Relevant Schemes & Alternatives**: related schemes ranked by the farmer's stated need, similar purpose, state/crop targeting and criteria already met — each with the reason, what still needs checking (missing information vs a known mismatch vs incomplete scheme data), the official link and the last verification date; "Show more" paging
- Every scheme applicable to the state is now evaluated (previously cut at 25 alphabetically); duplicates are shown once — see [docs/RECOMMENDATIONS.md](docs/RECOMMENDATIONS.md)

### Chat History
- Every signed-in account keeps its conversations (question, reply in the reply language, schemes shown); **Chat history** (`/history`) lists them, opens one, continues it in the chat or deletes one / all; saving can be turned off
- Scoped to the session; another account's conversation can't be read, deleted or continued (not even by sending its thread id); in the data export, deleted with the account, purged after 365 days — see [docs/CHAT_HISTORY.md](docs/CHAT_HISTORY.md)

### System Status
**SchemeSetu v1.0.0**, running locally (no cloud deployment). The evaluation scorecard (47 PASS / 0 FAIL /
6 NOT_MEASURED) is from 2026-10-17 and has not been re-run since the account features were added.
Still not measured: live evaluation with API keys, user study and expert review
([limitations](docs/phase7-limitations.md)). Current status and next steps: [progress.md](progress.md).

## Architecture

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
        ▼             │                ▼
  PROFILE AGENT       │          CONTEXT HANDLER
        │             │
        ▼             │
  COMPLETENESS        │
     AGENT            │
       /      \       │
      /        \      │
 INCOMPLETE   COMPLETE│
     │           │    │
     ▼           ▼    │
QUESTION      QUERY   │
  AGENT      REWRITER │
                 │    │
                 ▼    │
           RETRIEVAL  │
             AGENT    │
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
        ELIGIBILITY ENGINE
          (deterministic)
                 │
                 ▼
       RECOMMENDATION RANKER
                 │
                 ▼
           XAI EVIDENCE
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

## Tech Stack

| Layer     | Technology                          |
|-----------|-------------------------------------|
| Frontend  | Next.js 15, TypeScript, Tailwind 4  |
| Backend   | FastAPI, Python 3.11+               |
| AI Agent  | LangGraph, Groq (`GROQ_MODEL`, default `openai/gpt-oss-20b`), Tavily |
| Voice     | Sarvam AI (ASR + TTS + translation) |
| Database  | PostgreSQL 16 (Docker locally; any PostgreSQL such as Neon via `DATABASE_URL`) |
| Accounts  | Argon2id, server-side cookie sessions, CSRF |
| KG        | NetworkX (MultiDiGraph)             |
| Deploy    | Docker Compose                      |

## Getting Started

### Prerequisites

- Python 3.11+
- Node.js 18+
- Docker & Docker Compose (optional)

### 1. Clone the repo

```bash
git clone https://github.com/YOUR_USERNAME/Scheme_Setu.git
cd Scheme_Setu
```

### 2. Backend Setup

```bash
cd backend
cp .env.example .env
# Fill in your API keys in .env

# Create virtual environment (recommended)
python -m venv .venv
# Windows:
.venv\Scripts\activate
# macOS/Linux:
source .venv/bin/activate

pip install -r requirements.txt

# Run database migrations
alembic upgrade head

# Import validated corpus into PostgreSQL
cd ..
python scripts/import_corpus.py

# Verify database
python scripts/db_check.py

# Build Knowledge Graph
python scripts/build_knowledge_graph.py

# Start the backend
cd backend
uvicorn app.main:app --reload --port 8000
```

### 3. Frontend Setup

```bash
cd frontend
npm install

# Optional: Create .env.local for custom API URL
# echo "NEXT_PUBLIC_API_BASE_URL=http://localhost:8000" > .env.local

npm run dev
```

### 4. Docker (full stack)

```bash
docker compose up --build -d   # PostgreSQL 16, migrations + corpus import, backend (:8000), frontend (:3000)
docker compose logs backend    # without SMTP, reset e-mail links are printed here
docker compose down            # stop
```

To use an external database (e.g. Neon) instead, set `DATABASE_URL` in the root `.env` and run
`alembic upgrade head` against it first. Migration `0004` clears stored exact incomes and Aadhaar statuses
(see [docs/PROFILE.md](docs/PROFILE.md)).

## Environment Variables

### Backend (`backend/.env`)

| Variable | Required | Description |
|---|---|---|
| `DATABASE_URL` | Yes* | Primary PostgreSQL connection string |
| `NEON_DATABASE_URL` | Yes* | Fallback PostgreSQL URL (if DATABASE_URL unset) |
| `GROQ_API_KEY` | Yes | Groq API key for LLM |
| `TAVILY_API_KEY` | Yes | Tavily API key for web search |
| `SARVAM_API_KEY` | Yes* | Sarvam API key for voice (ASR/TTS) |
| `DB_MIN_SIZE` | No | Connection pool min size (default: 1) |
| `DB_MAX_SIZE` | No | Connection pool max size (default: 5) |
| `FRONTEND_URL` | No | Frontend origin for CORS (default: `http://localhost:3000`) |
| `ENVIRONMENT` | No | `development`, `staging`, `production` |
| `LOG_LEVEL` | No | `DEBUG`, `INFO`, `WARNING`, `ERROR` |
| `REVIEW_API_KEY` | No | Development-only shared reviewer key (`X-Review-Key`); refused in production. Use REVIEWER accounts ([docs/RBAC.md](docs/RBAC.md)) |
| `MAX_SESSIONS` | No | Conversations kept in memory (default 1000, oldest evicted) |
| `MAX_CANDIDATES` / `MAX_RESPONSE_SCHEMES` | No | Candidates evaluated / returned (default 25 / 25) |
| `MAX_MESSAGE_CHARS` | No | Chat message length limit (default 2000) |
| `GROQ_MODEL` | No | Groq model id (default `openai/gpt-oss-20b`) |
| `SMTP_HOST` … `SMTP_FROM` | No | E-mail for password reset and account notices. Unset locally: links are printed in the backend log |
| `SESSION_*`, `COOKIE_SECURE`, `LOGIN_*` | No | Account security settings — see [docs/AUTH.md](docs/AUTH.md). Set `SESSION_SECRET`: unsubscribe links depend on it |
| `RETENTION_*` | No | Data retention (sessions 30 d, tokens 7 d, notifications 365 d, closed review cases anonymised after 365 d; daily purge) — see [docs/PRIVACY.md](docs/PRIVACY.md) |
| `STAFF_SESSION_*`, `REAUTH_WINDOW_MINUTES`, `REVIEW_SELF_ASSIGN`, `REVIEW_GRANT_MAX_HOURS`, `REVIEW_VIEWS_PER_10_MIN` | No | Reviewer access policy: shorter staff sessions, password re-entry for sensitive actions, case scope — see [docs/HUMAN_REVIEW.md](docs/HUMAN_REVIEW.md#access-policy) |
| `LIVE_*` | No | Query-time check of official websites: on/off, time budget, pages per question, per-request limits — see [docs/LIVE_VERIFICATION.md](docs/LIVE_VERIFICATION.md) |
| `NOTIFY_*`, `SMS_*`, `API_BASE_URL` | No | Scheme-update notifications: retries, SMS provider (off unless configured) — see [docs/SCHEME_UPDATES.md](docs/SCHEME_UPDATES.md) |

*The app starts without these but specific features will return configuration errors.

### Frontend

| Variable | Description |
|---|---|
| `NEXT_PUBLIC_API_BASE_URL` | Backend URL (default: `http://localhost:8000`) |

## API Endpoints

| Method | Endpoint | Description |
|--------|-----------|--------------------------------------|
| GET | `/` | API status |
| GET | `/health` | Health check with DB connectivity |
| GET | `/health/live` | Liveness probe |
| GET | `/health/ready` | Readiness probe with dependency status |
| POST | `/chat` | Text-based conversation with agent |
| POST | `/voice` | Voice input → ASR → agent response |
| POST | `/tts` | Text-to-speech conversion |
| GET | `/schemes` | List/search schemes (query, state, crop) |
| GET | `/schemes/{id}` | Full scheme detail with all child records |
| GET | `/languages` | Supported languages for the selector |
| GET | `/review-cases?status=&reason=&assigned=` | Human-review queue (REVIEWER / ADMIN account; dev-only `X-Review-Key`) — [docs/HUMAN_REVIEW.md](docs/HUMAN_REVIEW.md) |
| GET/PATCH | `/admin/users`, `/admin/users/{id}/role`, `/admin/users/{id}/status`, `/admin/schemes/{id}`, `/admin/audit-events` | Administrator only: accounts, scheme curation flags, audit log ([docs/RBAC.md](docs/RBAC.md)) |
| GET | `/auth/permissions` | Your role and permissions |
| GET/POST | `/admin/ops/overview`, `/errors`, `/conflicts`, `/validate`, `/jobs`, `/admin/audit-events/verify` | Administrator operations ([docs/ADMIN_OPERATIONS.md](docs/ADMIN_OPERATIONS.md)) |
| GET/POST | `/admin/scheme-changes…`, `/admin/notifications/deliveries`, `/admin/notifications/dispatch` | Administrator: detect, verify and publish scheme changes; delivery status ([docs/SCHEME_UPDATES.md](docs/SCHEME_UPDATES.md)) |
| GET/PUT/POST/DELETE | `/farmers/me/notifications…`, `/notification-preferences`, `/subscriptions…`, `/phone…` | Your notifications, channels, followed schemes, phone verification (signed in) |
| GET | `/review-cases/{id}` | Case detail + history |
| POST | `/review-cases/{id}/claim`, `/release`, `/comments`, `/assign` (admin) | Assignment and comments |
| POST | `/review-cases/{id}/resolve` | APPROVE / REJECT / MARK_UNVERIFIABLE / RESOLVE, or REQUEST_INFORMATION (request verification) |
| POST | `/review-cases/{id}/dismiss` | Dismiss a case |
| GET | `/farmers/me/review-cases` | Your own cases, in plain language |
| POST | `/auth/register`, `/auth/login`, `/auth/logout`, … | Accounts: cookie sessions and password reset — see [docs/AUTH.md](docs/AUTH.md) |
| GET/PUT/POST/DELETE | `/farmers/me/*` | Saved profile ([docs/PROFILE.md](docs/PROFILE.md)), eligibility from the saved profile, search history, dashboard ([docs/DASHBOARD.md](docs/DASHBOARD.md)) (signed in) |
| GET/POST/PATCH/DELETE | `/farmers/me/saved-schemes[/{id}[/checklist[/{item}]]]` | Save / unsave schemes, user-reported application checklist, optional application reference ([docs/SAVED_SCHEMES.md](docs/SAVED_SCHEMES.md)) |

## LangGraph Workflow

```
profile_agent → completeness_agent
    → [incomplete/conflict] → question_agent → END
    → [complete] → query_rewriter
        → [ambiguous] → question_agent → END
        → [clear] → retrieval_agent → eligibility_agent → recommendation_agent (+ review escalation)
                  → response_formatter (grounding validator) → END
```

1. **profile_agent**: Structured LLM extraction with merge and conflict detection
2. **completeness_agent**: Deterministic check for critical fields (state, land, crop)
3. **question_agent**: Priority-based follow-up questions, conflict confirmation
4. **query_rewriter**: Contextual reference resolution, intent classification
5. **retrieval_agent**: Parallel DB + Graph + Web search with timeouts
6. **response_formatter**: LLM-grounded response from structured candidates

## Testing

```bash
cd backend
pytest app/tests/ -v
```

Tests run without any API keys or database connection. Current (2026-10-26): **1219 passed, 67 skipped**.
The 67 skipped tests are opt-in PostgreSQL integration tests; they run (67 passed) when `TEST_DATABASE_URL` is set:

```bash
TEST_DATABASE_URL=postgresql://schemesetu:schemesetu@localhost:5432/schemesetu_auth_test \
  pytest app/tests/test_auth_repository_pg.py app/tests/test_profile_repository_pg.py \
         app/tests/test_search_history_pg.py app/tests/test_saved_schemes_pg.py app/tests/test_rbac_pg.py \
         app/tests/test_admin_ops_pg.py app/tests/test_scheme_updates_pg.py app/tests/test_review_pg.py \
         app/tests/test_review_access_pg.py app/tests/test_privacy_pg.py
```

Admin dashboard in a real browser (stack running): `python scripts/ui_admin_test.py` (15 checks).

Privacy page, export and account deletion in a real browser (stack running): `python scripts/ui_privacy_test.py`
(12 checks; 2 sign-ups).

Reviewer dashboard and access policy in a real browser (stack running): `python scripts/ui_review_test.py` (14 checks; 4 sign-ups).
A reviewer works cases only once approved: on `/admin` → "Reviewer access", or `set_role.py <email> REVIEWER --approve`.
A demo case from real data: `docker compose exec backend python ../scripts/raise_review_case.py --email you@example.com`.

Scheme-update pipeline in a real browser (stack running): `python scripts/ui_updates_test.py` (12 checks). It
really publishes a test change; afterwards run `docker compose up -d --force-recreate backend` and
`docker compose run --rm init` to restore the original corpus.

Browser test of sign-in, profile, dashboard and saved schemes (stack running): `python scripts/ui_auth_test.py`
(30 checks; it registers a new account per run, and registration allows 5 per IP per hour).

### Evaluation (Phase 7)

```bash
# from Scheme_Setu/
python scripts/run_evaluation.py --offline --label mylabel   # deterministic, no keys needed (~1 min + perf)
python scripts/run_evaluation.py --live                      # adds live Groq/Tavily/Sarvam measurements
python scripts/run_evaluation.py --compare before after      # before/after table
python -m evaluation.finalize                                # final scorecard + acceptance matrix docs
python scripts/smoke_test.py --offline                       # or --base-url http://localhost:8000
```

## Documentation

- [Progress & handoff](progress.md) · [Accounts](docs/AUTH.md) · [Profile](docs/PROFILE.md) · [Dashboard](docs/DASHBOARD.md) ·
  [Saved schemes](docs/SAVED_SCHEMES.md) · [Roles & permissions](docs/RBAC.md) ·
  [Admin operations & recovery](docs/ADMIN_OPERATIONS.md) · [Scheme updates & notifications](docs/SCHEME_UPDATES.md) · [Human review](docs/HUMAN_REVIEW.md) · [Privacy, retention & deletion](docs/PRIVACY.md) ·
  [Real-time scheme verification](docs/LIVE_VERIFICATION.md) · [Chat history](docs/CHAT_HISTORY.md) · [Eligible schemes & alternatives](docs/RECOMMENDATIONS.md)
- [Phase 4 — Agentic Architecture](docs/phase4-agentic-architecture.md)
- [Phase 4 — Retrieval Architecture](docs/phase4-retrieval-architecture.md)
- [Phase 4 — Conversation Context](docs/phase4-conversation-context.md)
- [Phase 4 — Failure Handling](docs/phase4-failure-handling.md)
- [Phase 4 — Performance Baseline](docs/phase4-performance-baseline.md)
- [Phase 7 — Final evaluation](docs/phase7-final-evaluation.md) · [Scorecard](docs/phase7-final-scorecard.md) ·
  [Bug register](docs/phase7-bug-register.md) · [Limitations](docs/phase7-limitations.md) ·
  [Review-II traceability](docs/phase7-review2-traceability.md) · [Metrics](docs/phase7-metrics.md)

## Known Limitations

See [docs/phase7-limitations.md](docs/phase7-limitations.md). Most important: offline evaluation mocks
Groq/Tavily/Sarvam (live accuracy and latency not yet measured); 22/40 corpus schemes have no structured rules
(always UNVERIFIABLE); in-memory session store and review queue; no user study or expert review yet.
Accounts: rate limits are in memory (one backend instance only); no two-factor authentication; no account
deletion from the UI yet; no SMTP configured by default.

## Future Roadmap

- Persistent conversation store, more structured rules for the corpus, PSTN/IVR, mobile app
- Account and profile deletion from the UI, two-factor authentication, shared rate-limit store

## License

MIT
