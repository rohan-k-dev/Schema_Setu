# SchemeSetu AI — Progress & Implementation Handoff

_Last updated: 2026-10-26. Read this first in a new session._

Git: `main` at `1ffcd34` (Tanmay's merge "farmer auth profile dashboard").
**Everything below dated 2026-10-25/26 by Rohan/Claude is uncommitted:** 41 modified and 113 new files, 154 paths in total (`git status --short -uall`).
Nothing has been committed or tagged; commit only when the team asks.

---

## 1. Architecture (short)

```
Next.js 15 frontend (localhost:3000)
   │  fetch with credentials: "include"  (HttpOnly session cookie + X-CSRF-Token header)
FastAPI backend (localhost:8000)
   ├─ /chat, /voice, /tts ── LangGraph workflow (8 nodes): profile → completeness → question
   │                         | query_rewriter → retrieval (DB + knowledge graph + Tavily web,
   │                         parallel) → eligibility (deterministic rules) → recommendation → formatter
   ├─ /auth/*   accounts: cookie sessions, CSRF, e-mail verification, reset (docs/AUTH.md)
   ├─ /farmers/me/*  saved profile, saved schemes, eligibility, search history, dashboard (docs/PROFILE.md, docs/DASHBOARD.md)
   ├─ /farmers/me/notifications…, /subscriptions…, /phone…  inbox, channels, followed schemes (docs/SCHEME_UPDATES.md)
   ├─ /admin/*  accounts, audit, operations, scheme-change review (docs/RBAC.md, ADMIN_OPERATIONS.md, SCHEME_UPDATES.md)
   └─ /review-cases  human review: reviewer dashboard /review (REVIEWER account; dev-only X-Review-Key; docs/HUMAN_REVIEW.md)
PostgreSQL 16 (Docker) ── schemes corpus + accounts + profiles + audit + notifications + review cases (Alembic migrations 0001–0009)
External: Groq (LLM, model from GROQ_MODEL, default openai/gpt-oss-20b), Tavily (web), Sarvam (ASR/TTS/translate)
```

Key decisions (keep):
- **The LLM never decides eligibility.** It only extracts the profile, rewrites queries and words replies. The deterministic rule engine decides; replies are checked by a grounding validator.
- **Unknown stays UNKNOWN** (`null`), giving "needs more information", never "not eligible".
- **Accounts use server-side sessions**: an HttpOnly cookie `ss_session`, with only its SHA-256 hash stored. There is no JWT and no token in localStorage.
- **The saved profile collects only fields the rules use.** Aadhaar status and exact income are not stored, and the Aadhaar number is never collected.
- Every `/farmers/me/*` operation uses the account from the session; no farmer id is accepted from the client.

---

## 2. Feature status

### Done (and verified)
- **Core assistant** (Phases 0–8): multilingual text + voice chat, 40-scheme corpus, knowledge graph, eligibility engine, explanations, human review, evaluation framework. Version **1.0.0**.
- **Live-service fixes (2026-10-18):**
  - The Groq model was made configurable, because llama-3.3-70b was retired.
  - Profile extraction no longer crashes on dict output.
  - Prompts were shrunk for Groq's free-tier tokens-per-minute limit.
  - Sarvam translate (1000-char limit) and TTS (500-char limit) are chunked.
  - The browser's `audio/webm;codecs=opus` MIME type is fixed for ASR.
  - Answers to documents / how-to-apply questions work without the LLM.
- **Farmer accounts** (Tanmay, 2026-10-25): register, login, dashboard, saved schemes, search history, saved profile in chat.
- **Secure authentication** (2026-10-25, on top of Tanmay's work), see `docs/AUTH.md`:
  - Argon2id passwords; legacy bcrypt hashes upgraded at the next login.
  - Cookie sessions: 12 h idle and 7 day absolute limits, bound to the User-Agent, revoked on logout / password reset / password change.
  - CSRF tokens (HMAC of the session) plus an Origin check.
  - E-mail verification required before login.
  - Forgot / reset password with single-use links valid 30 min.
  - Change password and "sign out of all devices".
  - Lock for 15 min after 5 failed logins; per-IP / per-e-mail rate limits (429).
  - Generic answers, so accounts can't be enumerated.
  - **Fixed security hole:** `/auth/forgot-password` used to return the reset token in its response.
- **Farmer profile module** (2026-10-25), see `docs/PROFILE.md`:
  - Fields: state, district, land size + unit (acre/hectare/guntha/cent, converted to acres), crop, occupation, age, gender, category, income range, residence.
  - Partial updates: a field left out is unchanged; `null` = unknown.
  - Strict validation (422, unknown fields rejected); 409 for stale edits via the version number.
  - Chat saves only the fields changed in that turn; the saved profile wins when the farmer has consented.
- **Personalized dashboard** (2026-10-25), see `docs/DASHBOARD.md`:
  - Eligibility for every active scheme from the saved profile (deterministic engine only), with status tabs and pages.
  - Missing and conflicting details, fixable in place, then recalculated.
  - A stale notice when the profile, scheme data or rules change (basis fingerprint).
  - Saved schemes flagged when their status changes.
  - Search history is now actually recorded (it never was before): consent only, 50 entries / 90 days, delete one or clear all.
- **Saved schemes + application checklists** (2026-10-25), see `docs/SAVED_SCHEMES.md`:
  - Before, the API could save, but **no UI ever called it**; a re-save wiped notes; errors looked like "not found"; any scheme id/name from the client was accepted.
  - Now: Save buttons on dashboard eligibility rows and chat scheme cards; only schemes in the database (name from the DB).
  - Checklist per saved scheme: documents, preparation, official steps, submission, acknowledgement, own milestones (≤ 20).
  - Tick / untick, notes per item and per scheme, optional application reference.
  - **Progress is labelled user-reported** everywhere (`progress_source: USER_REPORTED`, `official_tracking: false`); no government tracking exists.
  - Scheme version = content hash (stable across corpus re-imports). On a change, progress is kept, new items are added, removed items are kept but not counted, and a notice is shown until acknowledged.
  - Duplicate saves change nothing (200, `created: false`); ownership is enforced by queries and by a composite FK.
- **Role-based access control** (2026-10-25), see `docs/RBAC.md`:
  - Before: no roles. Review used a shared key, with a client-chosen `reviewer_id` (default "admin"); there was no admin function and no persistent audit log.
  - Now: roles `FARMER` (default) / `REVIEWER` / `ADMIN` in `farmers.role`, read from the DB on every request. Deny-by-default permission matrix in `app/core/permissions.py`, enforced in route dependencies (`require` / `require_own`) and again in the admin / review service functions.
  - Reviewers decide cases; admins read the queue but don't decide.
  - Admins manage account role and status (metadata only), set scheme curation flags (status / needs-review, not rules) and read the audit log.
  - No self role/status change; the last active admin is protected (row locks); a role change or deactivation ends the target's sessions; `role` is rejected in registration / profile bodies.
  - The first admin is made only on the server: `scripts/set_role.py`.
  - Append-only `audit_events` (DB trigger) records role/status changes, curation, review decisions and denied attempts.
  - The shared `X-Review-Key` is kept for dev/demo/evaluation: review-only, no account, refused in production. The reviewer recorded is the authenticated principal.
- **Administrator operations dashboard** (2026-10-26), see `docs/ADMIN_OPERATIONS.md`:
  - Page `/admin`; API `/admin/ops/*`; permissions `ops:read`, `ops:validate`, `ops:jobs:run` (ADMIN only).
  - Shows: system health, corpus status, ingestion jobs, graph sync, pending reviews, recent errors. Each section loads on its own (UNAVAILABLE, not a false all-clear).
  - Tools: read-only validation (corpus file, rule conflicts, DB integrity, file↔DB drift, graph); conflict inspection (DB-vs-web source conflicts from review cases, rule conflicts, flagged schemes).
  - Jobs (`admin_jobs`): IMPORT_CORPUS / REBUILD_GRAPH. Dry run by default; a real run needs `confirm` = kind and a reason; one at a time (partial unique index).
    - Import: gated on corpus validation; uses the existing transactional importer.
    - Graph: built in staging, backed up, installed file-by-file (works on Docker overlayfs), restored automatically if the reload fails.
    - Interrupted jobs are marked FAILED at startup.
  - Audit (migration 0007): every event has an outcome (SUCCESS/FAILURE/DENIED) and a correlation id (`X-Request-ID` middleware). A SHA-256 hash chain makes edits, deletions and reordering detectable, even past the trigger (`GET /admin/audit-events/verify`). More filters; paginated. Refused admin actions are audited as FAILURE.
  - Redaction (`app/core/redaction.py`) of audit details, captured errors and job output: no passwords, keys, tokens, cookies, contact data or profiles.
  - Found and fixed on the way:
    - the importer and `build_knowledge_graph.py` read `manifest["version"]`, but the key is `corpus_version`, so the version always defaulted to 1.0.0;
    - the first graph-swap design (directory renames) failed in Docker with EXDEV.
- **Reviewer dashboard** (2026-10-26), see `docs/HUMAN_REVIEW.md`:
  - Before: review cases lived only in memory (lost on restart), there was no reviewer screen, no assignment, comments or protection against two reviewers acting at once; case snapshots kept the whole profile; farmers never saw the outcome.
  - Now: cases in PostgreSQL (migration 0009) with an append-only history; page `/review` with status / reason / assignment filters, counts and paging.
  - Each case shows the scheme(s) + official links, the reason, the read-only automated result, source text + URLs, conflicting rule / source values, failed channels, the farmer's question and a **minimal profile** (only fields the triggering rules use, never identity data).
  - Workflow: take / release / admin assign; comment; request additional verification (stays open); approve / reject (optional "data correction needed") / mark unverifiable / resolve; dismiss. Notes required; final states; only the assignee acts; version-checked (409 on a stale view); history + hash-chained audit in one transaction.
  - Decisions never change automated results or rules: wrong rules go through the scheme-update process.
  - Farmers: a chat case is linked to the signed-in farmer; dashboard "Checks by our team" shows open checks as unconfirmed and the outcome in plain language (no reviewer names / notes); eligibility rows under review are badged.
  - Found and fixed on the way: the recommendation node's no-results path called the now-async escalation without `await` (chat answered "error" when every retrieval channel failed) — caught by the adversarial runner (A17), regression test added.
- **Privacy and data settings** (2026-10-26), see `docs/PRIVACY.md`:
  - Before: no account or profile deletion, no export, no way to withdraw consent, no privacy page or processor disclosure; ended sessions, used tokens and notifications were kept forever.
  - Page `/privacy` (public + "Your data" when signed in), driven by `app/core/privacy.py` (`GET /privacy/policy`): every profile and account field with required / optional, purpose, storage and which external service receives it; other records and retention; Groq / Tavily / Sarvam / e-mail / SMS processing stated accurately (chat text goes to the LLM; translation and voice to Sarvam; web search gets state + crop only); deletion exceptions.
  - Controls (own account only): data summary; JSON export (recent sign-in, 5/h, audited); delete profile = withdraw consent (also deletes the search history; chat stops syncing, searches stop being recorded); delete saved schemes; delete notification data (incl. phone); delete account (password + "DELETE MY ACCOUNT").
  - Account deletion in one transaction: cascade over every per-farmer table, review cases anonymised and unlinked, a deleted reviewer's open cases released, `ACCOUNT_DELETED` audited with the account id only; in-memory chat threads and rate-limit counters cleared; the last admin can't delete.
  - Retention purge (daily; `RETENTION_*`): ended sessions 30 d, used tokens 7 d, notifications 365 d, search history 90 d, closed review cases anonymised after 365 d.
  - Found and fixed on the way: `LastAdmin` raised inside `get_db_connection` would have been re-wrapped as a database error (503 instead of 409) — caught by the PostgreSQL test; the privacy routes returned 500 without a database (now 503); the disclosure first omitted that rural / urban can reach the LLM inside scheme criteria.
- **Reviewer authorization policy** (2026-10-26), see `docs/HUMAN_REVIEW.md` → Access policy:
  - Before: any REVIEWER account could read every case in full; review reads weren't audited; staff sessions lasted like farmers' (12 h idle / 7 days); nothing asked for the password again.
  - Approval: REVIEWER role + administrator approval (`/admin` → Reviewer access, or `set_role.py … REVIEWER --approve`; migration 0010). Unapproved reviewers have own data only. Revoking, or any role change, ends sessions and grants.
  - Scope: full case only when assigned or explicitly granted (expiring, revocable, read + comment only); the queue as summaries; everything else 404 (same as missing) and audited DENIED. Self-assignment can be switched off (`REVIEW_SELF_ASSIGN`).
  - Minimisation: no farmer account / session / thread ids; question text redacted; no route to farmer profiles. No exports: summaries only, page ≤ 50, per-reviewer view rate limit, `Cache-Control: no-store`.
  - Audit: queue and case views, denials, grants, approvals, reauthentication — fail closed with PostgreSQL.
  - Sessions: staff 30 min idle / 12 h absolute; recent sign-in (10 min) or `POST /auth/reauthenticate` for final decisions, dismissals, assignment, grants and approvals (403 `REAUTH_REQUIRED` → password dialog); 5 wrong passwords end the session. The dev review key sees only cases not linked to a farmer.
  - Found and fixed on the way: in `admin_repository.set_role` the grant cleanup ran between `UPDATE … RETURNING` and its `fetchone()` (caught by the PostgreSQL tests).
- **Scheme-update notifications** (2026-10-26), see `docs/SCHEME_UPDATES.md`:
  - Detect: a normalised candidate file in `data/incoming/` is compared with the verified corpus for eligibility, benefits, states, documents, steps, URLs, status, new / missing schemes. Cosmetic and provenance-only differences are ignored; invalid records are refused; suspicious scrapes (>20 % missing, >50 % changed) are flagged; change fingerprints stop duplicates. Provenance: source file + SHA-256, before / after, detector, time.
  - Verify: every change is PENDING until an admin approves or rejects it; consequential changes need "I checked the official source" + a note. Audited.
  - Publish (admin job `PUBLISH_CHANGES`): only fully reviewed batches; only approved categories merged; validated; new corpus version + backup + snapshot; DB import in one transaction; files restored and nobody notified if the import fails; stale candidate / base version refused.
  - Notify: savers and followers of an affected scheme, once per account per scheme per batch. In-app (default on), e-mail (SMTP + verified e-mail, one-click unsubscribe), SMS (configured provider + code-verified phone + recorded consent, opt-out). "Consequential only" option.
  - Delivery: one row per (notification, channel); `SKIP LOCKED` claims; retries 1/5/30/120/360 min up to `NOTIFY_MAX_ATTEMPTS`, then GAVE_UP; SENT is final; permanent failures SKIPPED; opt-out re-checked at send; interrupted sends are not retried (no duplicates); signed SMS delivery reports (DELIVERED / UNDELIVERED).
  - Found and fixed on the way: a punctuation-only benefit difference was reported as a change; the admin panel overwrote the detection summary with a generic message; the first inbox query used f-string SQL (caught by `test_bug026`).

- **Real-time scheme discovery and verification** (2026-10-26, docs/LIVE_VERIFICATION.md): every scheme question searches official sites (Tavily, per domain group: national / ministry / the farmer's state / open; privacy-safe query) and re-reads the official pages of the top stored schemes within a 9 s budget. Polite fetcher (robots.txt, crawl-delay, per-host rate limit, official hosts only, TLS verified, CAPTCHA / login / 403 / JS-only reported, never bypassed; HTML + PDF; cache with ETag revalidation). Deterministic field extraction with evidence; field-level verification vs stored records (conflicts → human review); per-scheme freshness labels (LIVE_VERIFIED / CACHED / SOURCE_REACHABLE / NOT_VERIFIED / STORED) with source links and timestamps; `live_check` report in the chat response and UI; provenance snapshots with last known-good and change classification (migration 0011). Eligibility still uses stored rules only.
  - Found and fixed by the tests: "Office hours 10 to 5" read as Rs. 10 ("rs" inside "hours"); "0.5 hectare" cut to "5 hectare" and "hectares" not matched; repeated dates.
  - Real network (2026-10-26): agriinfra.dac.gov.in read live (5 fields); nsmny.mahait.org / raitamitra reached but no scheme details; pmkisan.gov.in TLS failure; agmarknet JS-only; agricoop.nic.in unreachable. **Tavily discovery not run live (placeholder key).**

- **Eligible schemes + relevant alternatives** (2026-10-26, docs/RECOMMENDATIONS.md): Section A = the engine's ELIGIBLE results only (decisions identical to a pre-feature baseline of 8 profiles); Section B = other evaluated schemes ranked by stated need / similar purpose / targeting / criteria met, with reasons, honest statuses (more information needed / criteria not checkable / scheme info incomplete / known mismatch), links and dates; collapsed not-matching group; "Show more". All state-applicable schemes evaluated (caps 25 → 60; before, 6–13 per profile were cut alphabetically). Planted duplicate `PMKISAN_MAN_DHAN` hidden from farmers (kept in corpus for GQ_011). Corpus expansion: `scripts/discover_missing_schemes.py` checked 18 official pages (real network) — **0 schemes added** (403 / JS-only / unreachable / no details; PDMC = component of PMKSY).

- **Chat history per account** (2026-10-27, docs/CHAT_HISTORY.md, new repo `Schema_Setu-utkarsh`): migration 0012 reuses the unused `sessions` / `messages` tables (+ farmer_id, title, counts, language, input mode, status, schemes shown; `farmers.chat_history_enabled`). Every signed-in chat / voice turn saved; `/history` page (list, open, continue, delete one / all, turn off); chat page resumes `/?thread=`; context restored after a restart; another account's thread id never continued; privacy export / deletion / 365-day purge. Tests: 13 API + 4 PostgreSQL + RBAC + browser 12/12 with the real assistant.
- **Reply language** (2026-10-27): replies and spoken answers follow the language the farmer types (script) or speaks (Sarvam detection), and the picker switches to it.
- **Sarvam out of credits** is reported as such (`SERVICE_QUOTA_EXHAUSTED`) instead of a generic voice error.

### Partially done / limitations
- **Real-service features are untested after the `.env` change**: `backend/.env` has placeholder keys (see §6.1).
- **E-mail**: no SMTP configured, so verification and reset e-mails are printed in the backend log (development only).
- **Rate limits** are in-memory per process; that's fine for one backend instance only.
- **Session binding** checks the User-Agent; an attacker who copies the exact UA string is not stopped.
- **Income range** is stored, but no eligibility rule uses income; if a future rule does, the engine needs range-aware evaluation.
- **RBAC**:
  - The operations dashboard is at `/admin` and the review queue at `/review`; there is no account-management screen yet (use `/docs`).
  - Ops limits:
    - jobs, the graph reload and the error list are per backend process (one instance);
    - a graph rebuilt inside Docker lasts until the container is recreated (`data/` is in the image);
    - the audit log has no retention limit.
  - A corpus re-import restores scheme status / needs-review (curation is temporary until the corpus is corrected).
  - The Docker DB has test accounts from the live check, including one ADMIN (`admin-…@example.com`).
- **Scheme updates**:
  - No scraper is included: something must write normalised files to `data/incoming/` (format of `data/validated/schemes.json`). Detection is started by an admin or `scripts/detect_scheme_changes.py`.
  - E-mail and SMS are not configured locally, so only in-app notifications are delivered; SMS was tested only with fakes and the `log` provider (no real provider account).
  - The dispatcher runs in the backend process (one instance); `SESSION_SECRET` must be set or unsubscribe links break after a restart.
  - Publishing changes the container's `data/` (it is in the image, not mounted): recreating the backend container returns it to the image's corpus while the database keeps the published version. Re-run `docker compose run --rm init` after recreating, or mount `data/` if published updates must persist.
- **Privacy**:
  - The audit log keeps e-mails of earlier events (append-only hash chain); pseudonymising them would need a re-chaining migration.
  - Data already sent to Groq / Tavily / Sarvam / e-mail / SMS providers is outside SchemeSetu's control.
  - Chat threads in server memory aren't linked to accounts; only those linked to review cases (or sent by the client) are cleared on deletion.
  - Operator database backups and Docker log rotation must be configured to honour deletion.
- **Reviewer access**:
  - Existing REVIEWER accounts must be approved after migration 0010 (the migration approves nobody).
  - The view rate limit and reauthentication failure counters are in-memory per backend process.
  - Admin assignment is by e-mail; there is no reviewer picker yet.
- **Application progress is user-reported only**: no government tracking API is integrated.
  - 22 of 40 schemes have no documents/steps in the corpus, so they get general checklist items.
  - The global handler for `DatabaseError` (main.py, pre-existing) still returns 500 with the internal error text. Saved-scheme routes return 503 instead, but the other routes are unchanged.
- **Evaluation scorecard** (47 PASS / 0 FAIL / 6 NOT_MEASURED) is from 2026-10-17. Not re-run after the auth and profile changes (the backend unit tests were).
- **Not measured** (need live keys / people): live extraction accuracy, live latency, translation quality, speech WER, user study, expert review.

### Not implemented
- Two-factor authentication; breached-password check.
- Multi-instance deployment (shared rate-limit store), and production SMTP / HTTPS setup.
- `HOW_TO_RUN.md` (the simple local guide written 2026-10-17) is **not in the repo**: it sits one folder up, in `capstone_project_final/HOW_TO_RUN.md`, and was never committed. It predates accounts (no sign-in, e-mail-log or migration steps). README "Getting Started" exists.

---

## 3. Files changed on 2026-10-25 (uncommitted)

### Secure authentication
| File | Purpose |
|---|---|
| `backend/app/core/security.py` | Argon2id hashing (+ bcrypt verify), opaque tokens, CSRF HMAC; JWT code removed |
| `backend/app/core/config.py` | Session, token, lockout, SMTP, `GROQ_MODEL` settings (replaced the JWT settings) |
| `backend/app/core/rate_limit.py` (new) | In-memory sliding-window rate limiter |
| `backend/app/services/email_service.py` (new) | SMTP sender; logs e-mails when SMTP is unset (not in production) |
| `backend/app/database/repositories/auth_repository.py` (new) | Sessions, single-use tokens, lockout (raises on DB errors) |
| `backend/app/services/auth_service.py` | Rewritten: register / verify / login / session / logout / reset / change password |
| `backend/app/api/auth.py` | Rewritten endpoints, cookies, Origin check, rate limits (`/auth/refresh` removed) |
| `backend/app/api/deps.py` | Session-cookie auth + CSRF check (chat/voice: anonymous if CSRF is missing) |
| `backend/app/models/auth_schemas.py` | Auth request/response schemas (+ profile schemas, below) |
| `backend/app/models/db/farmer_auth.py` | New row models (`AuthSessionRow`, `AuthTokenRow`, new columns) |
| `backend/requirements.txt` | + `argon2-cffi==23.1.0`, `bcrypt==5.0.0`; removed `python-jose`, `passlib` |
| `backend/.env.example` | Documented account and SMTP settings, `GROQ_MODEL` |
| `frontend/src/lib/api.ts`, `AuthContext.tsx`, `types.ts` | Cookie sessions, CSRF in memory, `ApiError`; no localStorage tokens |
| `frontend/src/app/auth/page.tsx`, `auth/AuthLayout.tsx`, `auth/authStyles.ts` | Register → "check e-mail", resend link, shared styles |
| `frontend/src/app/verify-email/`, `reset-password/`, `account/security/` (new) | New pages |
| `frontend/src/app/dashboard/page.tsx`, `profile/page.tsx`, `page.tsx` | Use the session instead of an access token; Security link |

### Profile module
| File | Purpose |
|---|---|
| `backend/app/database/repositories/profile_repository.py` (new) | Profile load/save with optimistic locking (`psycopg.sql`, raises on errors) |
| `backend/app/services/profile_service.py` | New save/load logic, land→acres, income ranges; schemes/search/dashboard unchanged |
| `backend/app/services/chat_profile_service.py` | Merge policy (saved wins when consented), save only changed fields, never Aadhaar |
| `backend/app/api/farmers.py`, `api/chat.py`, `api/voice.py` | 409 on conflict; pass the previous profile to chat saves |
| `backend/app/models/profile.py`, `agents/prompts/profile_prompt.py` | `residence` field (rural/urban) for MGNREGA |
| `backend/app/database/repositories/farmer_repository.py` | Removed the unused `upsert_farmer_profile` |
| `frontend/src/app/profile/page.tsx` | Land unit, income range, residence, "prefer not to say", 409 → "Reload latest" |

### Personalized dashboard
| File | Purpose |
|---|---|
| `backend/app/services/dashboard_service.py` (new) | Eligibility for all active schemes from the saved profile, missing/conflicting details, basis fingerprint, saved-scheme status changes |
| `backend/app/models/dashboard_schemas.py` (new) | Dashboard / eligibility / basis / search-history response schemas |
| `backend/app/database/repositories/search_history_repository.py` (new) | Record (consent only), list, delete one, clear; 50 entries / 90 days retention |
| `backend/app/api/farmers.py`, `api/chat.py`, `api/voice.py` | `/farmers/me/eligibility`, `/eligibility/basis`, `/search-history` routes; chat/voice record searches |
| `backend/app/main.py` | CORS exposes `X-Total-Count` (search-history paging) |
| `frontend/src/components/dashboard/` (new) | `EligibilityPanel.tsx`, `ProfileFixesPanel.tsx`, `SearchHistoryPanel.tsx` |
| `frontend/src/lib/profileOptions.ts` (new) | Shared option lists (states, units, ranges, …) for the profile page and dashboard fixes |
| `frontend/src/app/dashboard/page.tsx` | Uses the panels; stale check every minute and on tab focus |

### Saved schemes + checklists
| File | Purpose |
|---|---|
| `backend/alembic/versions/2026_10_25_0005_saved_scheme_checklists.py` (new) | Version / reference columns on `saved_schemes`; `saved_scheme_checklist_items` with composite owner FK |
| `backend/app/database/repositories/saved_scheme_repository.py` (new) | Raising SQL: load scheme content, save (ON CONFLICT DO NOTHING), sync to a new version, items, milestones |
| `backend/app/services/saved_scheme_service.py` (new) | Version hash, checklist builder, sync on read, all operations |
| `backend/app/models/saved_scheme_schemas.py` (new) | Requests (strict, extra=forbid) and responses with the user-reported label |
| `backend/app/models/auth_schemas.py`, `models/db/farmer_auth.py` | `SaveSchemeRequest` validated (`scheme_name` no longer trusted); new row fields / `ChecklistItemRow` |
| `backend/app/api/farmers.py` | Saved-scheme routes + checklist routes; 503 without internal details when the DB is down |
| `backend/app/services/profile_service.py`, `database/repositories/farmer_repository.py` | Removed the old unused-by-UI save/remove functions (replaced) |
| `frontend/src/components/dashboard/SavedSchemesPanel.tsx` (new) | Saved schemes, progress, checklist, reference, notes, milestones, update notice |
| `frontend/src/components/dashboard/EligibilityPanel.tsx`, `components/SchemeList.tsx`, `app/page.tsx`, `app/dashboard/page.tsx` | Save buttons (dashboard + chat); panel replaces the old saved-schemes card |
| `frontend/src/lib/api.ts`, `types.ts` | Saved-scheme / checklist API calls and types |

### Role-based access control
| File | Purpose |
|---|---|
| `backend/alembic/versions/2026_10_25_0006_roles_and_audit.py` (new) | `farmers.role` + check; `audit_events` with append-only trigger |
| `backend/app/core/permissions.py` (new) | Roles, permissions, matrix, `Principal`, `authorize` (deny by default) |
| `backend/app/api/deps.py` | `get_current_principal`, `require(permission)`, `require_own(permission)`, dev review key, denial audit |
| `backend/app/api/admin.py`, `services/admin_service.py`, `database/repositories/admin_repository.py` (new) | Accounts (role/status), scheme curation, audit log; transactional with audit |
| `backend/app/database/repositories/audit_repository.py`, `models/rbac_schemas.py` (new) | Audit log SQL; admin request/response models |
| `backend/app/api/review.py`, `services/review_service.py` | Role-based; `*_for` / `*_as` service functions authorize; reviewer = principal; `reviewer_id` body field removed |
| `backend/app/api/farmers.py`, `api/auth.py`, `main.py` | Own-data permissions per route; `/auth/permissions`; role in session; 403 handler for service denials |
| `backend/app/models/auth_schemas.py`, `models/db/farmer_auth.py` | `RegisterRequest` extra=forbid; `role` on account and session user; `AuditEventRow` |
| `backend/app/tests/test_farmer_features.py` (Tanmay's) | Fixture now overrides `get_current_principal` (a FARMER) instead of `get_current_farmer_id` |
| `scripts/set_role.py` (new); `scripts/smoke_test.py`, `evaluation/runners/review_runner.py`, `adversarial_runner.py` | Bootstrap admin; "no credentials" now accepts 401 (was 403) |
| `frontend/src/lib/types.ts` | `role` on the session user (display only) |

### Administrator operations
| File | Purpose |
|---|---|
| `backend/alembic/versions/2026_10_25_0007_admin_operations.py` (new) | Audit outcome / correlation id / hash chain (backfilled); `admin_jobs` + one-active index |
| `backend/app/core/audit_chain.py`, `request_context.py`, `redaction.py`, `error_buffer.py` (new) | Hash chain + verify; X-Request-ID middleware; redaction; recent-errors buffer |
| `backend/app/database/repositories/audit_repository.py` | Chain + advisory lock, outcome, correlation id, sanitised details, filters, `verify_chain` |
| `backend/app/database/repositories/ops_repository.py`, `services/ops_service.py`, `services/admin_jobs.py`, `api/ops.py` (new) | Dashboard sections, validation, conflicts, jobs |
| `backend/app/api/admin.py`, `services/admin_service.py`, `models/rbac_schemas.py`, `core/permissions.py`, `api/deps.py`, `main.py` | Audit filters + `/verify`; FAILURE / DENIED outcomes; ops permissions; middleware, error buffer, startup recovery |
| `backend/app/services/corpus_import_service.py`, `scripts/build_knowledge_graph.py` | `manifest_version`: read `corpus_version` (bug fix) |
| `frontend/src/app/admin/page.tsx`, `components/admin/*` (new); `lib/api.ts`, `types.ts`, `app/dashboard/page.tsx` | Dashboard UI; Operations button for ADMIN (display only) |
| `backend/app/tests/test_admin_ops.py`, `test_admin_ops_pg.py`, `fake_ops.py` (new); `test_rbac.py` | Tests; the RBAC matrix now covers the ops routes |
| `scripts/ui_admin_test.py` (new) | Playwright admin dashboard test (15 checks) |

### Privacy and data settings
| File | Purpose |
|---|---|
| `backend/app/core/privacy.py` (new) | The inventory: fields (required / why / stored / shared), records, processors, retention, exceptions |
| `backend/app/services/privacy_service.py`, `database/repositories/privacy_repository.py`, `api/privacy.py` (new) | Summary, export, category deletes, account deletion (one transaction), retention purge |
| `backend/app/core/permissions.py`, `core/config.py`, `core/rate_limit.py`, `main.py` | `account:own:data`; `RETENTION_*`; `limiter.forget`; daily purge task; router |
| `frontend/src/app/privacy/page.tsx` (new); `app/dashboard/page.tsx`, `app/profile/page.tsx`, `app/auth/page.tsx`, `app/auth/authStyles.ts`, `lib/api.ts`, `types.ts` | Privacy page; links from the dashboard, the consent checkbox and sign-up |
| `backend/app/tests/test_privacy.py`, `test_privacy_pg.py` (new); `test_rbac.py` | 22 + 4 tests; RBAC matrix covers the new routes |
| `scripts/ui_privacy_test.py` (new) | Playwright: 12 checks |

### Reviewer authorization policy
| File | Purpose |
|---|---|
| `backend/alembic/versions/2026_10_26_0010_reviewer_access_policy.py` (new) | `farmers.reviewer_approved_at/_by` (+ check), `auth_sessions.reauthenticated_at`, `review_case_grants` |
| `backend/app/core/permissions.py`, `core/config.py` | Unapproved reviewers lose review permissions; `users:reviewer:approve`; staff session / reauth / scope settings |
| `backend/app/services/auth_service.py`, `api/auth.py`, `api/deps.py`, `database/repositories/auth_repository.py`, `models/db/farmer_auth.py`, `models/auth_schemas.py` | Staff session limits; `POST /auth/reauthenticate`; `ensure_recent_auth` |
| `backend/app/services/review_workflow.py`, `services/review_store.py`, `database/repositories/review_repository.py`, `services/review_service.py`, `api/review.py` | Case scope (assigned / granted / queue / 404), summaries, grants, view audit + rate limit, no-store, reauth on sensitive actions |
| `backend/app/api/admin.py`, `services/admin_service.py`, `database/repositories/admin_repository.py`, `models/rbac_schemas.py`, `scripts/set_role.py` | Approve / revoke reviewers (ends sessions + grants); role change clears approval; `--approve` |
| `frontend/src/components/ReauthDialog.tsx`, `components/admin/ReviewersPanel.tsx` (new); `components/review/CaseDetail.tsx`, `app/review/page.tsx`, `app/admin/page.tsx`, `lib/api.ts`, `types.ts` | Password dialog, reviewer approvals, queue summary card + take, grants UI |
| `backend/app/tests/test_review_access_policy.py`, `test_review_access_pg.py` (new); `test_review_workflow.py`, `test_review_pg.py`, `test_rbac.py`, `fake_auth_repo.py` | 28 + 5 security tests; earlier tests updated to the policy (approval, 404 outside scope, view audit) |
| `scripts/ui_review_test.py` | 14 checks: unapproved reviewer refused, admin approval in the UI, summary-only queue, direct-API 404 |

### Reviewer dashboard
| File | Purpose |
|---|---|
| `backend/alembic/versions/2026_10_26_0009_review_cases.py` (new) | `review_cases` (constraints, one open case per session + reason, version), append-only `review_case_events` |
| `backend/app/services/review_workflow.py`, `services/review_store.py`, `database/repositories/review_repository.py` (new) | Workflow / state machine, minimal profile, farmer view; PostgreSQL or in-memory store; CAS updates with history + audit in one transaction |
| `backend/app/services/review_service.py`, `models/review.py` | In-memory queue kept for no-DB use (legacy functions unchanged in behaviour); `*_as` delegate to the workflow; `RESOLVE` action, new case fields |
| `backend/app/api/review.py` | Filters, claim / release / assign / comments, versioned resolve / dismiss; old response keys kept |
| `backend/app/agents/recommendation_agent.py`, `api/chat.py`, `api/voice.py` | Async escalation with scheme URLs; link a case to the signed-in farmer |
| `backend/app/api/farmers.py`, `services/dashboard_service.py`, `models/dashboard_schemas.py`, `core/permissions.py` | `/farmers/me/review-cases`; `under_review` on eligibility rows; `review_cases:assign`, `review_cases:own:read` |
| `frontend/src/app/review/page.tsx`, `components/review/CaseDetail.tsx`, `components/dashboard/ReviewStatusPanel.tsx` (new) | Reviewer dashboard; farmer "Checks by our team" |
| `frontend/src/app/dashboard/page.tsx`, `app/page.tsx`, `components/dashboard/EligibilityPanel.tsx`, `lib/api.ts`, `types.ts` | Review queue link (REVIEWER / ADMIN), chat pointer, "being checked" badge, API calls and types |
| `backend/app/tests/test_review_workflow.py`, `test_review_pg.py` (new); `test_rbac.py` | 31 + 7 tests; RBAC matrix covers the new routes |
| `scripts/raise_review_case.py`, `scripts/ui_review_test.py` (new) | Demo case from a real UNVERIFIABLE result; Playwright test (11 checks) |

### Scheme-update notifications
| File | Purpose |
|---|---|
| `backend/alembic/versions/2026_10_26_0008_scheme_updates_notifications.py` (new) | Change batches / changes (fingerprint dedupe), subscriptions, preferences, notifications, deliveries, phone verification |
| `backend/app/services/change_detection.py` (new) | Pure normalise-and-diff per category, suspicious-scrape warnings, merge of approved changes |
| `backend/app/services/scheme_update_service.py` (new) | Detect → verify → publish (atomic files + transactional import + rollback) → notify |
| `backend/app/services/notification_service.py`, `notification_channels.py` (new) | Preferences / consent, phone codes, unsubscribe tokens, dispatcher with retries; SMTP and SMS-provider channels |
| `backend/app/database/repositories/change_repository.py`, `notification_repository.py` (new) | SQL (raises on errors, `SKIP LOCKED` claims) |
| `backend/app/api/scheme_updates.py`, `api/notifications.py` (new) | Admin review / delivery routes; farmer inbox, preferences, subscriptions, phone; public unsubscribe + signed SMS status |
| `backend/app/services/admin_jobs.py`, `api/ops.py`, `core/permissions.py`, `core/config.py`, `main.py`, `models/db/farmer_auth.py` | Job `PUBLISH_CHANGES`; permissions `notifications:own`, `scheme_changes:review`, `notifications:admin`; `NOTIFY_*` / `SMS_*` settings; background dispatcher |
| `frontend/src/components/dashboard/NotificationsPanel.tsx`, `NotificationSettingsPanel.tsx`, `components/admin/SchemeChangesPanel.tsx`, `app/unsubscribe/` (new) | Inbox, channel settings + phone verification, admin review / publish, unsubscribe page |
| `frontend/src/app/dashboard/page.tsx`, `app/admin/page.tsx`, `components/admin/JobsPanel.tsx`, `lib/api.ts`, `types.ts` | Wiring |
| `backend/app/tests/test_scheme_updates.py`, `test_scheme_updates_pg.py`, `fake_notifications.py` (new); `test_rbac.py` | 46 + 8 tests; RBAC matrix covers the new routes |
| `scripts/detect_scheme_changes.py`, `scripts/ui_updates_test.py` (new) | CLI detection for a scraper / scheduled task; Playwright pipeline test (12 checks) |

### Real-time scheme verification
| File | Purpose |
|---|---|
| `backend/app/live/` (new: `sources.py`, `discovery.py`, `fetcher.py`, `extractor.py`, `verifier.py`, `service.py`) | Registry, discovery, polite fetcher + cache, extraction, verification, orchestration |
| `backend/alembic/versions/2026_10_26_0011_live_source_snapshots.py`, `database/repositories/live_snapshot_repository.py` (new) | Provenance snapshots + change detection |
| `backend/app/agents/retrieval_agent.py`, `agents/response_formatter.py`, `graph/state.py`, `models/responses.py`, `utils/serialization.py`, `api/chat.py`, `api/voice.py`, `api/ops.py`, `core/config.py`, `core/privacy.py`, `requirements.txt` (lxml, pypdf) | Pipeline wiring, `live_check` + `freshness` in responses, deterministic note, `GET /admin/ops/live-sources`, `LIVE_*`, disclosure |
| `frontend/src/components/LiveCheck.tsx` (new), `SchemeList.tsx`, `app/page.tsx`, `lib/types.ts` | Freshness badge, sources and times, conflicts, live-check summary |
| `backend/app/tests/test_live_verification.py`, `test_live_snapshot_pg.py`, `fixtures/live/*` (new); `conftest.py`, `test_rbac.py`, `evaluation/fixtures/mock_services.py` | 32 + 3 tests; live check off in offline tests |
| `scripts/live_check.py`, `scripts/ui_live_check_test.py` (new); `docs/LIVE_VERIFICATION.md` (new), `PRIVACY.md`, README, `.env.example` | Real-network run; browser test on a real run; docs |

### Eligible schemes + alternatives
| File | Purpose |
|---|---|
| `backend/app/recommendation/alternatives.py` (new); `agents/recommendation_agent.py`, `agents/response_formatter.py`, `retrieval/db_retriever.py`, `retrieval/merger.py`, `retrieval/models.py`, `graph/state.py`, `models/responses.py`, `utils/serialization.py`, `core/config.py`, `.env.example`, `.env` (caps only) | Sections, relevance, stored metadata, response fields, caps 60 |
| `frontend/src/components/AlternativesSection.tsx` (new), `SchemeList.tsx`, `lib/types.ts` | Eligible + alternatives UI, Show more, empty state |
| `backend/app/tests/test_recommendation_sections.py`, `test_corpus_discovery.py`, `recommendation_harness.py`, `fixtures/recommendations/baseline_statuses.json` (new); `evaluation/fixtures/corpus_db.py` (loads possible_duplicate / needs_review / scheme_type) | 19 + 8 tests, pre-feature baseline |
| `scripts/discover_missing_schemes.py`, `scripts/ui_alternatives_test.py` (new); `data/evaluation/reports/corpus_expansion_2026-10-26.json`; `docs/RECOMMENDATIONS.md` (new), README | Corpus expansion (real run), browser test, report |

### Tests, scripts, docs
- New tests:
  - `test_auth_security.py`, `test_profile_module.py`, `test_dashboard.py`, `test_saved_schemes.py`, `test_rbac.py`, and the in-memory fake `fake_auth_repo.py`.
  - Opt-in PostgreSQL: `test_auth_repository_pg.py`, `test_profile_repository_pg.py`, `test_search_history_pg.py`, `test_saved_schemes_pg.py`, `test_rbac_pg.py`.
- Updated tests: `test_farmer_features.py`, `test_chat_profile_service.py`.
- `scripts/ui_auth_test.py` (new): Playwright UI test, 30 checks (6 for saved schemes; the status-filter check now waits for the list to finish loading).
- Docs: `docs/AUTH.md`, `docs/PROFILE.md`, `docs/DASHBOARD.md`, `docs/SAVED_SCHEMES.md`, `docs/RBAC.md`, `docs/ADMIN_OPERATIONS.md`, `docs/SCHEME_UPDATES.md` (new); `docs/HUMAN_REVIEW.md` (rewritten); `README.md` (status, env, API, tests); `SECURITY.md`, `docs/API.md`, `docs/HUMAN_REVIEW.md` (roles).

---

## 4. Database migrations (applied to the Docker DB, current head = `0011`)

| Rev | What | Data changes / risks |
|---|---|---|
| 0001 | Scheme corpus schema | — |
| 0002 | `farmers`, `farmer_profiles`, `saved_schemes`, `search_history`, `refresh_tokens` (Tanmay) | — |
| 0003 | `auth_sessions`, `auth_tokens`; `farmers.failed_login_count / locked_until / password_changed_at` | Clears old `password_reset_token`s and revokes all `refresh_tokens` (both unused now). **Existing users must verify their e-mail** before login (use "Send me a new verification link"). |
| 0004 | `farmer_profiles.land_size_value / land_unit / income_range / residence / version` + check constraints | Converts `annual_income` to `income_range`, then **clears `annual_income` and `has_aadhaar`**. Irreversible: downgrade can't restore them. |
| 0005 | `saved_schemes` version / reference columns + `UNIQUE (id, farmer_id)`; new `saved_scheme_checklist_items` | Additive and reversible. Notes longer than 1000 characters are cut to 1000. Existing saved schemes get a checklist on first read. |
| 0006 | `farmers.role` (default FARMER, check); `audit_events` + append-only trigger | Every existing account becomes FARMER; nobody is admin until `scripts/set_role.py` is run. Reversible (the downgrade drops the audit log). |
| 0007 | `audit_events.outcome / correlation_id / prev_hash / entry_hash`; `admin_jobs` | Existing events are hash-chained in id order (the trigger is suspended only inside the migration); ACCESS_DENIED → DENIED. Reversible (the downgrade drops the chain and the jobs). |
| 0008 | `scheme_change_batches`, `scheme_changes`, `scheme_subscriptions`, `notification_preferences`, `notifications`, `notification_deliveries`; `farmers.phone_verified_at`; `auth_tokens` purpose `verify_phone` + `attempts` / `target`; `admin_jobs` kind `PUBLISH_CHANGES` + `params` | Additive. Nobody gets e-mail or SMS until they turn it on (in-app is on by default). |
| 0009 | `review_cases` (+ checks, partial unique index on open (session, reason), version), `review_case_events` + append-only trigger | Additive and reversible. Cases raised before it (in-memory) are not migrated: they were lost at every restart anyway. |
| 0010 | `farmers.reviewer_approved_at/_by` (+ check: REVIEWER only), `auth_sessions.reauthenticated_at`, `review_case_grants` | Additive and reversible. **Existing REVIEWER accounts lose case access until an administrator approves them.** |
| 0011 | `live_source_snapshots` (provenance of live official sources: last attempt, last known-good, previous good, change status) | Additive and reversible. |

Any other database (for example a teammate's Neon DB) still needs `alembic upgrade head`.
Test DB `schemesetu_auth_test` exists in the Docker Postgres for the opt-in integration tests.

---

## 5. Tests — last actual results (2026-10-26)

**Full run with the real API keys (Groq, Tavily, Sarvam) on 2026-10-26:**

| Suite | Result |
|---|---|
| Backend | **1288 passed**, 70 skipped (opt-in PostgreSQL) |
| PostgreSQL integration | **70 passed** |
| Live smoke test (`scripts/smoke_test.py`) | **18/18** (1 skipped: no review key) |
| Real-services end to end (`scripts/e2e_real_services.py`, nothing mocked) | **17/17** — English 12.7 s, follow-up 1.5 s, Hindi 12.6 s, Kannada voice round trip 18.4 s |
| Live LLM profile extraction (30 cases) | F1 **0.885** (precision 0.90, recall 0.87), 23/30 exact; one case hit the Groq free-tier rate limit; P29 read "10 crore" as 10 |
| Live latency, 20 back-to-back requests | mean 16.8 s, p95 23.9 s (Groq free tier: 8,000 tokens/min); single requests 4.3–9.2 s |
| Browser (Playwright) | auth 30/30, privacy 12/12, reviewer 14/14, admin 15/15, scheme updates 12/12 (corpus restored), live check 23/23, alternatives 22/22 |
| Evaluation runners (offline) | eligibility 104/104 (0 FP / 0 FN), recommendation 7/7, e2e 24/24, human review 23/23, adversarial 35/36 (A31) |
| Real app in the browser | question → crop asked → 10 eligible + 21 alternatives + live check |

Fixed during this run (each with a regression test): live check took 72 s (regex on 500k+ character search texts; now linear, capped, off the event loop: 7.9 s within the 9 s budget); a page with an XML declaration aborted the whole live check; a ministry name alone was labelled "verified live"; discovered reports / portal listings used every page slot so the farmer's schemes weren't checked; direct checks went to alphabetically first schemes instead of the stated need; pages over the cap were counted as failures; flaky unsubscribe test; live profile runner broke on dict output; reviewer UI test didn't page through a long queue.

Grounding validator (2026-10-26): bold headings such as "Scheme Search – Dairy cattle farmers in Telangana" were read as unknown scheme names and the LLM reply was discarded. Bold phrases are now checked part by part (split at – — : |); generic heading parts are skipped, scheme-name parts are still checked, and "…Yojana and other schemes" no longer hides a name (`app/tests/test_grounding_headings.py`, 19 cases). Real run: 4/5 LLM replies accepted; the 5th was correctly rejected for claiming eligibility for an UNVERIFIABLE scheme. Backend **1307 passed**.


| Suite | Command | Result |
|---|---|---|
| Backend unit/API | `cd backend && py -m pytest app/tests -q` | **1282 passed, 70 skipped** (the 70 skips are the opt-in PostgreSQL tests) — after eligible schemes + alternatives |
| PostgreSQL integration | `TEST_DATABASE_URL=postgresql://schemesetu:schemesetu@localhost:5432/schemesetu_auth_test py -m pytest app/tests/test_auth_repository_pg.py app/tests/test_profile_repository_pg.py app/tests/test_search_history_pg.py app/tests/test_saved_schemes_pg.py app/tests/test_rbac_pg.py app/tests/test_admin_ops_pg.py app/tests/test_scheme_updates_pg.py app/tests/test_review_pg.py app/tests/test_review_access_pg.py app/tests/test_privacy_pg.py app/tests/test_live_snapshot_pg.py -q` | **70 passed** |
| Admin dashboard (Playwright) | `py scripts/ui_admin_test.py` (stack running) | **15/15** |
| Privacy page (Playwright) | `py scripts/ui_privacy_test.py` (stack rebuilt) | **12/12** (2026-10-26): field table, processors, exceptions; export of own data only; delete saved schemes; withdraw consent; delete account → signed out, sign-in refused, other farmer intact |
| Reviewer dashboard + access policy (Playwright) | `py scripts/ui_review_test.py` (stack rebuilt) | **14/14** (2026-10-26): farmer and unapproved reviewer refused; admin approves in the UI; queue summary only; after taking: evidence, comment, verification, approve; stale second reviewer refused and gets 404 by direct API; farmer sees the outcome |
| Live verification — real network | `py scripts/live_check.py "…" --state S` in the backend container; real `retrieval_agent_node` | Runs completed (2026-10-26): AGRI_INFRA_FUND **LIVE_VERIFIED** from agriinfra.dac.gov.in; other sources labelled with real reasons (TLS / JS-only / unreachable / no details). Discovery NOT_CONFIGURED (placeholder Tavily key) |
| Eligible + alternatives (Playwright) | `py scripts/ui_alternatives_test.py` (stack rebuilt) | **22/22** on the real pipeline + real PostgreSQL corpus (only the LLM wording bypassed) |
| Live-check display (Playwright) | `py scripts/ui_live_check_test.py` (stack rebuilt) | **22/22** on a real retrieval run (only the LLM reply step bypassed) |
| Evaluation runners (offline, direct) | human_review / e2e / adversarial | **23/23**, **24/24**, **35/36** (re-run after real-time verification): A31 (static secret scan) flags the fake secrets in `test_admin_ops.py` (from the admin-operations work, not this feature) |
| Scheme-update pipeline (Playwright) | `py scripts/ui_updates_test.py` (stack rebuilt) | **12/12** (2026-10-26): detect → confirmation gate → approve → publish → exactly one "Important" notification. Corpus restored afterwards (`--force-recreate backend` + `run --rm init`). |
| Live real jobs against Docker | scratch script: real REBUILD_GRAPH + IMPORT_CORPUS, correlation ids, audit verify, log scan for secrets | **8/8** |
| Offline smoke test / review + adversarial evaluation runners | `py scripts/smoke_test.py --offline`; runners called directly | **20/20**; human review **22/22**, adversarial **36/36** |
| Live RBAC check against Docker | scratch script (register → `set_role.py` → admin / reviewer / farmer calls) | **16/16** |
| Browser UI (Playwright) | `py scripts/ui_auth_test.py` (stack running, rebuilt) | **30/30 passed, 3 runs in a row**. Max 5 runs per hour: registration is rate-limited per IP (restart the backend to reset). |
| Frontend | `cd frontend && npx tsc --noEmit` / `npm run build` | both clean |
| Live smoke test | `py scripts/smoke_test.py --base-url http://localhost:8000` | Last run **10/18**: chat, profile, TTS and voice fail **only because `.env` keys are placeholders**. 18/18 on 2026-10-18 with real keys. |

No known failing tests in the code itself.
The UI test falls back to Microsoft Edge because Windows blocks Playwright's own Chromium.

---

## 6. Known issues → exact next steps

1. **API keys:** restored on 2026-10-26 (Groq, Tavily, Sarvam, `GROQ_MODEL`). Remaining service limits: Groq free tier 8,000 tokens/min (burst latency), voice round trip 18 s. *(Old note:)* In `backend/.env`, `GROQ_API_KEY`, `TAVILY_API_KEY` and `SARVAM_API_KEY` are set to `API_KEY_HERE`, and so is **`GROQ_MODEL`** (it must be `openai/gpt-oss-20b`).
   Then run `docker compose up -d --force-recreate backend` and the smoke test (expect 18/18).
2. **Review and commit** the 154 uncommitted paths (auth, profile, dashboard, saved-scheme, RBAC, admin-operations, scheme-update, reviewer-dashboard, reviewer-access and privacy work) on a branch, then open a PR to `main` and tell Tanmay: the API contract changed (no JWT; cookies + CSRF).
3. **Run `alembic upgrade head`** on every other database (Neon; now up to `0010`; approve existing reviewers afterwards) and warn about the 0004 data clearing. Then create an administrator there with `scripts/set_role.py`.
4. **Re-run the evaluation** (`py scripts/run_evaluation.py --offline --label final --soak-seconds 600`) and regenerate `release_manifest.json`.
5. **Optional:** configure SMTP; add account/profile deletion; move `../HOW_TO_RUN.md` into the repo and add the account steps, if the team wants the simple guide.
6. Before any deployment: `ENVIRONMENT=production` (Secure cookies), a set `SESSION_SECRET`, SMTP, HTTPS, and a shared rate-limit store if more than one backend instance runs. For SMS: a provider account (`SMS_PROVIDER=http`, `SMS_HTTP_URL`, `SMS_HTTP_TOKEN`, `SMS_STATUS_SECRET`) and a public `API_BASE_URL` for delivery reports.
7. **Adversarial A31:** exclude test fixtures from the static secret scan (or mark the fake values in `test_admin_ops.py`), then re-run the evaluation.
8. **Live verification:** with a real `TAVILY_API_KEY`, run `scripts/live_check.py` for a few questions and record discovery results in docs/LIVE_VERIFICATION.md; fix the dead stored URL `agricoop.nic.in` through the scheme-update pipeline; consider myScheme's official API (needs their key) for JS-only portals.
9. **Scheme updates:** connect a scraper that writes normalised files to `data/incoming/`; mount `data/` in Docker if published corpus versions must survive container recreation.

---

## 7. Commands (run from `Scheme_Setu/`; Windows: `py` = python)

```bash
docker compose up --build -d          # full stack: db, migrations + corpus import, backend, frontend
docker compose down                   # stop
docker compose logs backend           # backend log (dev e-mails with verify/reset links appear here)
curl localhost:8000/health/ready      # shows which API keys are configured

cd backend && py -m pytest app/tests -q                   # backend tests
py scripts/smoke_test.py --base-url http://localhost:8000 # live smoke test
py scripts/ui_auth_test.py                                 # browser UI test (stack running)
py scripts/ui_review_test.py                               # reviewer dashboard (3 sign-ups)
py scripts/raise_review_case.py --email you@example.com    # demo review case from real data (run in the backend container)
py scripts/ui_updates_test.py                              # scheme-update pipeline (then: docker compose up -d --force-recreate backend && docker compose run --rm init)
py scripts/detect_scheme_changes.py <file>.json            # detect changes in data/incoming/<file>.json
py scripts/demo_server.py                                  # keyless demo backend (scripted LLM)
py scripts/run_evaluation.py --offline --label NAME        # evaluation

cd backend && py -m alembic upgrade head                   # migrate a database (DATABASE_URL)
```

Docs: `docs/AUTH.md`, `docs/PROFILE.md`, `docs/DASHBOARD.md`, `docs/SAVED_SCHEMES.md`, `docs/RBAC.md`, `docs/ADMIN_OPERATIONS.md`, `docs/SCHEME_UPDATES.md`, `docs/HUMAN_REVIEW.md`, `docs/PRIVACY.md`, `README.md`, `SECURITY.md`. Project history: `../instructions/PROJECT_STATE.md`.
