# SchemeSetu AI 🌾

**AI-powered government scheme discovery for Indian farmers.**

SchemeSetu ("Bridge to Schemes") is a multilingual AI assistant that helps rural Indian farmers discover government schemes they're eligible for. It uses voice input in native languages, an intelligent conversational agent, and text-to-speech to make government benefits accessible to everyone.

## Current Implementation (Phase 0 → Phase 7, release candidate v0.7.0-rc1)

### Phase 0 — Core Platform
- ✅ Conversational scheme discovery via text and voice
- ✅ Profile extraction using Groq LLaMA 3.3 structured output
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
- 484 backend tests pass (0 skipped); frontend build clean; offline smoke test 19/19.

### System Status
**Release candidate SchemeSetu RC-1 (v0.7.0-rc1)**, classified READY_FOR_FINAL_DOCUMENTATION for the
offline-measurable scope. Before final submission: run `--live` evaluation with API keys, run the user study
and expert review, and verify against a real PostgreSQL instance ([limitations](docs/phase7-limitations.md)).

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
| AI Agent  | LangGraph, Groq LLaMA 3.3, Tavily  |
| Voice     | Sarvam AI (ASR + TTS)               |
| Database  | Neon (Serverless PostgreSQL)         |
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

### 4. Docker (alternative for backend)

```bash
# With Neon (just backend)
docker compose up --build

# With local PostgreSQL
docker compose --profile local-db up --build
```

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
| `REVIEW_API_KEY` | No | Reviewer key (`X-Review-Key` header). Review API disabled when unset |
| `MAX_SESSIONS` | No | Conversations kept in memory (default 1000, oldest evicted) |
| `MAX_CANDIDATES` / `MAX_RESPONSE_SCHEMES` | No | Candidates evaluated / returned (default 25 / 25) |
| `MAX_MESSAGE_CHARS` | No | Chat message length limit (default 2000) |

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
| GET | `/review-cases` | Human-review queue (requires `X-Review-Key`) |
| GET | `/review-cases/{id}` | Case detail + audit log |
| POST | `/review-cases/{id}/resolve` | Reviewer action (APPROVE / REJECT / REQUEST_INFORMATION / MARK_UNVERIFIABLE) |
| POST | `/review-cases/{id}/dismiss` | Dismiss a case |

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

Tests run without any API keys or database connection. Current: **484 passed, 0 skipped**.

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

## Future Roadmap

- **Phase 8**: Final documentation, diagrams, deployment packaging, presentation and demo
- **Later**: persistent session/review store, more structured rules for the corpus, PSTN/IVR, mobile app

## License

MIT
