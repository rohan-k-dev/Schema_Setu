# Security Policy — SchemeSetu

SchemeSetu is a student capstone release (v1.0.0). This document describes the threat model, the controls that
are actually implemented and tested, and the known risks. Evidence: `docs/evaluation/red-team-report.md`
(36 red-team probes, all passing after fixes) and `backend/app/tests/test_phase7_regressions.py`.

## Threat model
**Assets:** users' profile answers (state, district, land, crop, income, social category, gender, Aadhaar
*status* — never an Aadhaar number), the canonical scheme database, API keys (Groq, Tavily, Sarvam), the reviewer
key, and the integrity of eligibility decisions.

**Actors:** anonymous end users (no login), reviewers (shared key), malicious users, malicious web content
returned by search, and a misbehaving or manipulated LLM.

| Threat | Control | Tested by |
|---|---|---|
| LLM or prompt injection makes a scheme "eligible" | Eligibility is decided only by the deterministic engine over DB rules. LLM replies pass a grounding validator; the deterministic reply is used on violation. Retrieved text is labelled untrusted in the prompt | A11–A16, E2E21/22 |
| Indirect prompt injection from web results | Web results never alter rules or canonical data; unmapped results are dropped; prompt rule 17 | A11, E2E21 |
| SQL injection | All SQL parameterised (`%s`); identifiers composed with `psycopg.sql.Identifier`; static scan in CI | A06, A18, A19, test_bug026 |
| Graph / code injection | Graph queried with structured profile values only; no `eval`/`exec` (static scan) | A20, A21 |
| XSS | React escapes all text; no `dangerouslySetInnerHTML`/`innerHTML`; bold rendering without HTML parsing | A22, A23 |
| Malicious upload | ≤10 MB, MIME allow-list, magic-byte check, server-generated filename, audio never stored | A24–A26, VF05–VF09 |
| Oversized / blank input | 2000-character message limit, blank rejected (HTTP 422) | A32, A33 |
| Session leakage | Per-tab random `thread_id`; per-thread checkpoints; isolation tests | A27, PL22 |
| Unauthorised review actions | Role-based access control: REVIEWER accounts decide, ADMIN reads only, others 403 ([docs/RBAC.md](docs/RBAC.md)); dev-only `X-Review-Key` compared in constant time, refused in production | A28–A30, test_bug020, test_rbac.py |
| Unsafe admin operations / tampered audit trail | Admin-only ops API; dry run by default, typed confirmation, one job at a time, validation gates, graph staging + backup + auto-restore; hash-chained append-only audit log with outcome + correlation id; redaction of secrets / personal data ([docs/ADMIN_OPERATIONS.md](docs/ADMIN_OPERATIONS.md)) | test_admin_ops.py, test_admin_ops_pg.py, ui_admin_test.py |
| Privilege escalation | Role only from the account row; no self role/status change; last admin protected; first admin only via `scripts/set_role.py`; append-only audit log | test_rbac.py, test_rbac_pg.py |
| Secret exposure | Secrets only in server env (`backend/.env`, git-ignored); no secret in code (static scan); `/health` returns booleans only; configuration errors shown to clients without names | A31, test_phase8_configuration_errors_hidden |
| Personal data in logs | Logs record field names, lengths and IDs only; no profile values or transcripts | A34, test_bug021 |
| Unnecessary data to third parties | Groq gets a minimal profile summary; sensitive values in scheme cards are redacted; Tavily gets state + crop only | A35, test_bug022 |
| Identity data in review cases | Aadhaar/bank/PAN/phone/name/email/address fields stripped | review runner PRIVACY |

## Secrets management
- Put keys in `backend/.env` (local) or the hosting platform's secret store (production). Never commit them.
  `.gitignore` excludes `.env` and `.env.*` (except `.env.example`).
- The only browser-exposed variable is `NEXT_PUBLIC_API_BASE_URL`. Never put a secret in a `NEXT_PUBLIC_*` variable.
- Generate the reviewer key: `python -c "import secrets; print(secrets.token_urlsafe(24))"`. The demo server
  generates a random key on every run.
- Rotate any key that was ever pasted into chat, logs or a commit.

## Safe deployment practices
HTTPS only. Set `CORS_ORIGINS` to the exact frontend origin. Use a managed PostgreSQL with TLS and a
non-default password (the Docker Compose credentials are for local use only). Use `LOG_LEVEL=INFO` or
`WARNING`. Put a rate-limiting reverse proxy in front (SchemeSetu has none). Leave `REVIEW_API_KEY` unset unless
reviewers need access. Containers run as non-root users. See `DEPLOYMENT.md`.

## Known limitations and risks
- **No end-user authentication.** Anyone holding a `thread_id` can continue that conversation (IDs are
  random UUIDs and never listed).
- **No rate limiting.** Abuse can drain the Groq/Tavily/Sarvam quota.
- **Reviewer accounts** (role `REVIEWER`) are used for review; the audit log records the signed-in account. The shared
  reviewer key remains for development only (refused when `ENVIRONMENT=production`).
- The LLM-reply validator is pattern-based. A paraphrased false claim could evade it, but the structured
  per-scheme status shown in the UI always comes from the engine.
- Conversation text is sent to Groq and Sarvam (third-party processors) under their terms.
- The review queue and conversations are in memory; they are lost on restart and not encrypted at rest.
- Dependencies are pinned for reproducibility (e.g. `langgraph==0.0.31`, `fastapi==0.110.1`). They are older
  versions and should be upgraded and re-tested before any production use.

## Reporting a vulnerability
Please do not open a public issue. E-mail the project maintainers (see the README "Team" section) with a
description, reproduction steps and impact. We aim to acknowledge reports within 7 days. As a student
project there is no bug bounty.
