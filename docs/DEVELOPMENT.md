# Development Guide

All commands were executed during the Phase 8 release check, on Windows 11 / Python 3.11.4 / Node 24
and in a clean `python:3.11-slim` container.

## 1. Setup
```bash
git clone <repo-url> && cd Scheme_Setu

# Database (PostgreSQL 16 in Docker)
docker run -d --name schemesetu-pg -e POSTGRES_DB=schemesetu -e POSTGRES_USER=schemesetu \
  -e POSTGRES_PASSWORD=schemesetu -p 5432:5432 postgres:16

# Backend
cd backend
cp .env.example .env          # set DATABASE_URL=postgresql://schemesetu:schemesetu@localhost:5432/schemesetu
python -m venv .venv && source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements.txt
alembic upgrade head          # schema (15 tables)
cd ..
python scripts/import_corpus.py         # canonical corpus → PostgreSQL (idempotent)
python scripts/db_check.py              # counts + integrity checks
python scripts/verify_db_parity.py      # optional: PostgreSQL vs evaluation fixture (301 comparisons)
cd backend && python -m app --reload    # API on :8000  (Linux/macOS: uvicorn app.main:app --reload also works)

# Frontend (second terminal)
cd frontend && npm ci && npm run dev    # UI on :3000
```
Windows note: start the API with `python -m app`. It selects the selector event loop that async psycopg
needs; plain `uvicorn app.main:app` on Windows cannot connect to PostgreSQL.

Keyless demo (real DB/pipeline, simulated LLM/speech/translation for the scripted demo):
`python scripts/demo_server.py` (from `Scheme_Setu/`). See `docs/demo/DEMO_SCRIPT.md`.

## 2. Repository layout
```
backend/app/
  api/            FastAPI routes (chat, voice, schemes, review, health) — thin, no business logic
  agents/         LangGraph nodes (profile, completeness, question, query_rewriter, retrieval, eligibility,
                  recommendation, response_formatter) + prompts/
  graph/          LangGraph state + workflow (BoundedMemorySaver)
  retrieval/      db / graph / web retrievers, merger, deduplicator, conflict detector
  eligibility/    deterministic engine: operators, logical (Kleene), normalizer, evaluator, validators
  xai/            templates, explainer + validator, grounding, LLM-reply validator
  recommendation/ deterministic ranker
  knowledge_graph/ schema, builder, serializer, repository
  database/       connection pool + repositories (all SQL parameterised)
  services/       llm, search (Tavily), language & voice (Sarvam), review, corpus import, KG service
  models/         FarmerProfile (canonicalising validators), request/response, review, DB rows
  localization/   language registry (11 languages)
  tests/          pytest suite (unit, integration, golden journeys, security regressions)
backend/alembic/  migrations
data/             corpus pipeline outputs (validated/schemes.json is canonical), graph snapshots, evaluation data
evaluation/       Phase 7 framework: datasets/, fixtures/ (mocks + corpus DB), runners/, report.py, finalize.py
scripts/          corpus/graph/DB tooling, run_evaluation, smoke_test, demo_server, capture_screenshots, ...
frontend/src/     Next.js app (page.tsx) + components + lib/api.ts, lib/types.ts
docs/             architecture, operations, evaluation, capstone report, presentation
```

## 3. Workflow
- Branch, change, then run `cd backend && python -m pytest app/tests -q` (497 tests, about 10 s, no keys/DB needed).
- Changing eligibility, retrieval or XAI: also run `python scripts/run_evaluation.py --offline --skip-performance --label dev`
  and check `data/evaluation/reports/dev/summary.md` (no FAIL/PARTIAL expected).
- Frontend: `cd frontend && npm run build` (type-check + build).
- CI (`.github/workflows/ci.yml`) runs the same plus a real-PostgreSQL parity job and the Docker build.
- Golden labels are human-curated. Never edit expected values to match output. Use `label_history` +
  `evaluation/datasets/DATASET_VERSIONS.md`.

## 4. Database migrations
```bash
cd backend
alembic revision -m "describe change"   # edit backend/alembic/versions/<new>.py
alembic upgrade head
alembic downgrade -1                    # roll back one step
```
`alembic/env.py` reads `DATABASE_URL` and uses the psycopg 3 dialect automatically.

## 5. Corpus update
```bash
python scripts/build_corpus.py          # raw/extracted → normalized/validated (Phase 1 pipeline)
python scripts/validate_corpus.py
python scripts/import_corpus.py         # upsert into PostgreSQL, new corpus_versions row
python scripts/build_knowledge_graph.py # rebuild graph snapshot from the same validated corpus
python scripts/validate_knowledge_graph.py
```
Bump `corpus_version` in `data/metadata/corpus_manifest.json` when content changes. The graph metadata
records the corpus version it was built from; `/health` and the release manifest compare them.

## 6. Graph rebuild
`python scripts/build_knowledge_graph.py` writes `data/graph/snapshots/<date>/` and `data/graph/current/`
(loaded at API start-up). `python scripts/inspect_knowledge_graph.py` prints node/edge statistics.

## 7. Evaluation, smoke test, screenshots
```bash
python scripts/run_evaluation.py --offline --label <name> [--soak-seconds 600] [--skip-performance]
python scripts/run_evaluation.py --live          # needs GROQ/TAVILY/SARVAM keys
python scripts/run_evaluation.py --compare before after
python -m evaluation.finalize                    # docs/phase7-final-scorecard.md, acceptance matrix
python scripts/smoke_test.py --offline           # or --base-url http://localhost:8000 [--review-key K]
pip install playwright==1.47.0 && python scripts/capture_screenshots.py   # needs demo server + frontend
```
