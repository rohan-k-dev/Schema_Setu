# Administrator Operations

The operations dashboard is at **`/admin`** (the "🛠️ Operations" button on the dashboard). It is for
`ADMIN` accounts only. The server checks every request: a farmer or reviewer gets 403 from the API
and "Administrator access required" on the page, never any data. See [RBAC.md](RBAC.md) for roles and
how to create the first administrator (`scripts/set_role.py`).

## What the dashboard shows

| Section | Source | Notes |
|---|---|---|
| System health | the app, `alembic_version` | version, uptime, database, migration vs the code's head, graph loaded, which external services are **configured** (never their keys), warnings |
| Scheme corpus | `data/validated/schemes.json` + manifest; `schemes`, `eligibility_rules`, `corpus_versions` | file vs database version and counts; status counts; needs-review / possible-duplicate / no-rules counts |
| Ingestion jobs | `admin_jobs`, `ingestion_runs` | the running job, recent jobs, recent imports |
| Graph synchronisation | the loaded graph + database | in sync = same corpus version and the same scheme ids; lists missing / extra schemes |
| Pending reviews | review queue | open cases by reason, oldest open, cases with source conflicts |
| Recent errors | this server process | ERROR log records, **redacted**, with correlation ids |

Each section is loaded on its own. If one source is down, that card says **Unavailable**; the page never
shows "all clear" for something it could not check.

## Tools

| Tool | Changes data? | What it does |
|---|---|---|
| **Validate scheme data** | No | It runs these checks: <ul><li>the phase 1 validator on the corpus file;</li><li>contradictory eligibility rules;</li><li>database integrity (active schemes without sources, `UNKNOWN` operators);</li><li>curation flags;</li><li>file vs database drift;</li><li>graph validation and sync.</li></ul> Each check is PASS / WARN / FAIL / ERROR. The run is audited (`VALIDATION_RUN`). |
| **Inspect conflicts** | No | Shows three things: <ul><li>source conflicts that retrieval found between the database and the live web (kept on review cases);</li><li>contradictory rules;</li><li>schemes flagged needs-review / possible-duplicate.</li></ul> The database value is canonical: if the web is right, fix the corpus. |
| **Import corpus** (job) | Yes | Runs the existing importer: one transaction, idempotent, it never deletes schemes. |
| **Rebuild Knowledge Graph** (job) | Yes | Builds a graph from the validated corpus file, validates it, swaps it in, and reloads it. |

### Job safety rules (enforced on the server)

1. **Administrators only**, and every POST needs `X-CSRF-Token`.
2. **Dry run by default.** A dry run reports what would happen and changes nothing:
   - an import shows schemes to insert / update, schemes kept because they're not in the file, and
     admin curation that would be reset;
   - a rebuild shows node / edge counts and whether the graph changes.
3. **A real run needs confirmation**: `confirm` must equal the job kind (`IMPORT_CORPUS` / `REBUILD_GRAPH`)
   and a `reason` (5–300 characters) is required. The UI asks you to type the name.
4. **One job at a time.** A second request gets 409 `JOB_IN_PROGRESS` (a partial unique index on `admin_jobs`).
5. **Validation gates**:
   - an import stops before touching the database if the corpus file has validation errors;
   - a new graph that fails validation is never swapped in.
6. **Graph swap.** The swap works on Windows, Linux and Docker's overlay filesystem:
   1. the new graph is written to a staging folder and test-loaded;
   2. the current graph is copied to `data/graph/backups/<time>-<job>` (the last 5 are kept);
   3. each file is installed with an atomic rename;
   4. if the new graph doesn't load, the backup is put back and reloaded automatically.
7. **Strict input:** only `kind`, `dry_run`, `reason` and `confirm` are accepted. Paths, `force` and other
   options can't be sent (422).
8. **Restart:** a job that was queued or running when the server stopped is marked FAILED at the next
   start, and audited as `system`.

Jobs run in the backend process after the request returns (202). Follow them under Recent jobs, or with
`GET /admin/ops/jobs/{id}`.

## Audit trail

Sensitive actions are recorded in `audit_events`:
- role and status changes, scheme curation;
- review decisions;
- validation runs, job requests / results, audit verifications;
- refused attempts (`ACCESS_DENIED`).

Each event has:

| Field | |
|---|---|
| actor | `actor_label` (staff e-mail, `review-key`, `system`, `cli:set_role`), `actor_role`, `actor_account_id` |
| action | e.g. `ROLE_CHANGED`, `JOB_REQUESTED`, `JOB_FAILED` |
| affected record | `target_type` + `target_id` (account UUID, scheme id, job id, endpoint) |
| timestamp | `occurred_at` (UTC) |
| outcome | `SUCCESS`, `FAILURE` (refused or failed, e.g. `LAST_ADMIN`, wrong confirmation) or `DENIED` (no permission) |
| correlation id | the request's `X-Request-ID` (the caller's, if it is a safe token, else a new one; returned in the response header) |

**Integrity:**
- The table is append-only (a trigger rejects UPDATE / DELETE).
- Every event carries `prev_hash` and `entry_hash`, a SHA-256 chain (`app/core/audit_chain.py`).
- **Verify integrity** (`GET /admin/audit-events/verify`) recomputes the whole chain. It finds an edited,
  deleted, inserted or reordered event even if someone with database rights disabled the trigger, and it
  reports the first broken event. The check itself is audited.
- Writers take an advisory lock, so concurrent events keep a single chain.

**Viewing:** pages of up to 200 (the UI uses 25), newest first. You can filter by action, outcome, record,
actor, correlation id and time window. All filters are validated, and a bad value gives 422.

### What is never stored or shown

Passwords, API keys, session cookies or tokens, CSRF tokens, reset links, full profiles,
Aadhaar, phone or bank numbers, and e-mail addresses inside free text. They are removed in three places:
1. **When an event is written:** detail keys like `password`, `token`, `session`, `phone`, `profile` are
   replaced with `[redacted]`.
2. **In free text:** key-like strings, bearer tokens, `user:pass@` in URLs, long opaque tokens, e-mails,
   Aadhaar-like and phone numbers are masked (`app/core/redaction.py`).
3. **In captured errors** (same rules), and in job errors and results.

Configuration is shown only as configured: yes / no.

What is kept on purpose:
- the acting staff member's e-mail, so you can see who did it;
- the client IP of the request (security);
- account **UUIDs** as targets, never profile contents.

The audit log has no retention limit. Set one if your data-protection policy needs it; deleting rows will
show up as a chain break, so archive and then start a new chain deliberately.

## Recovery runbook

| Situation | What to do |
|---|---|
| Dashboard card says **Unavailable** | Check that card's source: the database (`docker compose ps`, `/health`) or the corpus file. The other cards are still correct. |
| **Migration** differs from the expected one | `docker compose run --rm init` or `cd backend && alembic upgrade head`. Then refresh. |
| A job **FAILED** | Read its error and correlation id, find that id under Recent errors and in the server log (`docker compose logs backend`), fix the cause, and re-run (dry run first). Nothing is committed when an import fails: it is one transaction. |
| A job was **interrupted by a restart** | It is already marked FAILED. Run a dry run to see the current state, then run it again. |
| **Graph not in sync** after an import | Run the *Rebuild Knowledge Graph* job (dry run, then real). |
| **Graph broken or missing** | <ol><li>Copy the newest folder from `data/graph/backups/` over `data/graph/current/`.</li><li>Restart the backend, or rebuild: `python scripts/build_knowledge_graph.py`.</li><li>Without a graph, retrieval still works from the database (graceful degradation).</li></ol> |
| **Import reset an administrator's scheme suspension** | Expected: the corpus is canonical. Make lasting status changes in the corpus, or curate again after the import. The dry run lists these schemes as `curation_reset`. |
| **Verify integrity** reports a break | Treat it as a security incident:<ol><li>Keep a copy of the database.</li><li>Check who had database access around the broken event's time.</li><li>Don't "repair" the chain.</li><li>Record the finding and start investigating from the reported event id.</li></ol> |
| **Docker:** a rebuilt graph disappears after `docker compose up --build` | `data/` is part of the image. A rebuild in the container lasts until the container is recreated. To keep it, rebuild locally (`python scripts/build_knowledge_graph.py`) and rebuild the image. |

## Limits

- **One backend process:** jobs, the graph reload and the error buffer are per process. With more than
  one instance, the other instances still use their old graph until they restart, and the error list
  shows one instance only.
- **The error list is not the system of record:** it is in memory (newest 500) and empty after a restart.
  Use the server log for history.
- **Audit-chain verification reads the whole log:** fine at this size; very large logs would need
  checkpoints.

## API

| Method | Path | Permission |
|---|---|---|
| GET | `/admin/ops/overview` | `ops:read` |
| GET | `/admin/ops/errors?limit=&offset=` | `ops:read` |
| GET | `/admin/ops/conflicts` | `ops:read` |
| POST | `/admin/ops/validate` | `ops:validate` |
| GET | `/admin/ops/jobs?limit=&offset=`, `/admin/ops/jobs/{id}` | `ops:read` |
| POST | `/admin/ops/jobs` `{kind, dry_run=true, reason, confirm?}` | `ops:jobs:run` |
| GET | `/admin/audit-events?action=&outcome=&target_type=&target_id=&actor=&correlation_id=&since=&until=&limit=&offset=` | `audit:read` |
| GET | `/admin/audit-events/verify` | `audit:read` |

## Tests

- `backend/app/tests/test_admin_ops.py` (53 tests) uses the HTTP API with real sessions. It covers:
  - the dashboard, failure isolation, no secrets in the overview, migration drift;
  - reviews and conflicts;
  - redaction of errors and their correlation ids, request-id handling;
  - validation, including an outage;
  - jobs: dry run, confirmation, one at a time, invalid input, the validation gate, a crash with no leak,
    restart recovery;
  - a real graph rebuild: backup, reload, restore on failure, invalid graph, the Docker/EXDEV case;
  - the audit fields, outcomes, the hash chain (tampering, a removed event), query validation, pagination;
  - redaction rules, and the manifest-version regression.
- `backend/app/tests/test_rbac.py` has every role × every operations endpoint.
- `backend/app/tests/test_admin_ops_pg.py` (6 tests, opt-in `TEST_DATABASE_URL`) runs on PostgreSQL:
  - the migration backfill of existing events;
  - concurrent writers;
  - tampering that bypasses the trigger (edit and delete);
  - outcome constraint and sanitising;
  - the one-active-job index and restart recovery;
  - a real import job → validation → graph sync.
- `scripts/ui_admin_test.py` (15 checks) runs in a real browser against `docker compose up`. It covers:
  - a farmer refused (page and API);
  - all sections; validation; conflicts; a dry-run job;
  - the confirmation guard; the audit row with a correlation id; integrity verified.
