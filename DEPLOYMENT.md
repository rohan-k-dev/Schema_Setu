# Deployment Guide — SchemeSetu v1.0.0

**Status:** local deployment (bare metal and Docker Compose) has been **performed and verified**.
Staging and production deployments have **not** been performed. Those sections are a guide based on the
current architecture.

## Architecture constraints that drive deployment
- Two stateless-ish services: the **frontend** (Next.js) and the **backend** (FastAPI). Plus **PostgreSQL**
  (canonical data) and three external APIs (Groq required; Tavily and Sarvam optional).
- Conversation state and the review queue live **in the backend process memory**. Run **one backend
  process** (`uvicorn` without `--workers`, one replica). For more replicas you need sticky sessions by
  `thread_id`, and the review queue would still be per-replica. A persistent checkpointer is future work.
- The Knowledge Graph snapshot (`data/graph/current/`) and corpus (`data/validated/`) ship inside the backend
  image and are loaded at start-up.
- `NEXT_PUBLIC_API_BASE_URL` is compiled into the frontend at build time.

---
## LOCAL

### Option A — Docker Compose (verified 2026-10-14)
```bash
cp backend/.env.example backend/.env    # add GROQ_API_KEY etc. (optional: compose overrides DATABASE_URL)
docker compose up --build               # postgres → init (migrate, import, check) → backend → frontend
```
Open http://localhost:3000 · API http://localhost:8000/docs · health `curl localhost:8000/health`.
Observed on the reference machine: image build 93 s, stack up in 25 s. `init` logged
"Running upgrade -> 0001", "[OK] Import completed successfully!", "Schemes: 40", "Rules: 25", and all integrity
checks OK. `/health` returned `{"status":"healthy","db_connected":true,"graph_available":true}`.
Reset data: `docker compose down -v`.

### Option B — without Docker for the app
See `docs/DEVELOPMENT.md` §1 (Postgres in Docker, backend `python -m app`, frontend `npm run dev`).

### Option C — keyless demo
`python scripts/demo_server.py` + `cd frontend && npm run build && npm start`. See `docs/demo/DEMO_SCRIPT.md`.

---
## STAGING (recommended, not performed)
Same images as production, separate database and keys:
- `ENVIRONMENT=staging`, a staging Postgres, staging Groq/Tavily/Sarvam keys with low quotas.
- Run `python scripts/smoke_test.py --base-url https://<staging-api> --review-key <key>` after every deploy,
  and `python scripts/run_evaluation.py --live --label staging-<date>` to measure live latency and extraction
  accuracy (the outstanding Review-II measurement).

---
## PRODUCTION (guide, not performed)

| Component | Recommended | Build | Start | Health |
|---|---|---|---|---|
| Database | Managed PostgreSQL 16 (TLS, automated backups) | — | — | provider |
| Backend | Container service or VM running `backend/Dockerfile` (context = repo root) | `docker build -f backend/Dockerfile -t schemesetu-api .` | image CMD `uvicorn app.main:app --host 0.0.0.0 --port 8000` (one process) | liveness `/health/live`; readiness `/health/ready` |
| Frontend | Container from `frontend/Dockerfile`, or any Next.js host (e.g. Vercel) | `docker build --build-arg NEXT_PUBLIC_API_BASE_URL=https://api.<domain> -t schemesetu-web frontend` | `node server.js` (port 3000) | `GET /` |
| TLS / domain | Reverse proxy or platform TLS: `https://<domain>` → frontend, `https://api.<domain>` → backend | | | |

### Steps
1. Create the database; set `DATABASE_URL=postgresql://user:pass@host:5432/schemesetu?sslmode=require`.
2. **Release job (once per release)**, using the backend image:
   `alembic upgrade head && python ../scripts/import_corpus.py && python ../scripts/db_check.py`.
   The import is an idempotent upsert of the canonical corpus. It never imports web content.
3. Deploy the backend with secrets from the platform's secret store: `GROQ_API_KEY`, `TAVILY_API_KEY`,
   `SARVAM_API_KEY`, `REVIEW_API_KEY` (optional), `CORS_ORIGINS=["https://<domain>"]`,
   `ENVIRONMENT=production`, `LOG_LEVEL=INFO`, `MAX_SESSIONS` sized to memory (about 300 KB each).
4. Build the frontend with the **public** API URL and deploy.
5. Verify: `curl https://api.<domain>/health/ready` (expect `ready`), then
   `python scripts/smoke_test.py --base-url https://api.<domain>`.

### Must not be exposed
API keys, `DATABASE_URL` and `REVIEW_API_KEY` stay server-side (never `NEXT_PUBLIC_*`). Do not publish the
database port. `/docs` and `/redoc` are public by default; restrict them at the proxy if undesired. Error
responses contain no stack traces or configuration names.

### Logs, restarts, updates
- Logs go to stdout in `time | level | module | message` format, without personal data. Collect them with the platform.
- Restart policy `unless-stopped` / platform auto-restart. Conversations and review cases are lost on
  restart (documented limitation).
- Corpus update: rebuild the image with the new `data/validated` and graph snapshot, then run the release job.
- Rollback: redeploy the previous image tag. Schema rollback with `alembic downgrade -1` if a migration was added.

### Operations — diagnosing failures
| `/health` / `/health/ready` | Meaning | Action |
|---|---|---|
| `healthy`, `ready` | DB + graph up, Groq configured | — |
| `degraded`, `db_connected:false` | Database unreachable | Check `DATABASE_URL`, network, DB status |
| `degraded`, `graph_available:false` | Graph snapshot missing | Rebuild the image with `data/graph/current` |
| `not_ready`, `groq_configured:false` | Conversations cannot be understood | Set `GROQ_API_KEY` |
| `tavily_configured:false` / `sarvam_configured:false` | Web search / voice and translation off | Optional keys |
Detailed matrix: `docs/FAILURE_HANDLING.md`; fixes: `docs/TROUBLESHOOTING.md`.
