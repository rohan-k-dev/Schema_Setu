# Roles and Permissions

SchemeSetu has three roles. Every account is a **FARMER** when it is created.

| Role | Who | Purpose |
|---|---|---|
| `FARMER` | every registered user | Use the assistant and keep their own profile, saved schemes and history |
| `REVIEWER` | human-review staff | Work the review queue on `/review`: cases the eligibility engine can't decide reliably ([HUMAN_REVIEW.md](HUMAN_REVIEW.md)) |
| `ADMIN` | operators | Manage accounts, curate scheme status, verify and publish scheme updates, and read the audit log |

All checks run on the **server**: in each route's FastAPI dependency (`require` / `require_own` in
`app/api/deps.py`) and again inside the service functions for staff actions (`admin_service`, and the
`*_for` / `*_as` functions in `review_service`). The frontend only *shows* links (`GET /auth/permissions`);
hiding a button is never the protection.

## Permission matrix

The source of truth is `ROLE_PERMISSIONS` in `app/core/permissions.py`. Access is **deny by default**:
a role may do only what is listed, and an unknown role can do nothing.

| Area | Permission | FARMER | REVIEWER | ADMIN | Scope |
|---|---|:-:|:-:|:-:|---|
| Profile | `profile:own:read` / `write` | ✓ | ✓ | ✓ | own account only |
| Saved schemes & checklists | `saved_schemes:own:read` / `write` | ✓ | ✓ | ✓ | own account only |
| Search history | `search_history:own:read` / `delete` | ✓ | ✓ | ✓ | own account only |
| Eligibility dashboard | `eligibility:own:read` | ✓ | ✓ | ✓ | own account only |
| Review cases: read | `review_cases:read` | — | ✓* | ✓ | *approved reviewers: full case only when assigned or granted; the queue as summaries ([HUMAN_REVIEW.md](HUMAN_REVIEW.md#access-policy)) |
| Review cases: take, comment, request verification, decide, dismiss | `review_cases:decide` | — | ✓* | — | *approved reviewers; only the assignee acts; grantees comment only |
| Review cases: assign / reassign, read grants | `review_cases:assign` | — | — | ✓ | to active, approved reviewers only; recent sign-in |
| Approve / revoke reviewer accounts | `users:reviewer:approve` | — | — | ✓ | REVIEWER accounts only; not yourself; recent sign-in; revoking ends sessions and grants |
| Own review cases (status in plain language) | `review_cases:own:read` | ✓ | ✓ | ✓ | own account only |
| Own data: summary, export, delete account | `account:own:data` | ✓ | ✓ | ✓ | own account only; export needs a recent sign-in, deletion the password ([PRIVACY.md](PRIVACY.md)) |
| Scheme data: curation flags | `schemes:curate` | — | — | ✓ | status / needs-review / notes only |
| Accounts: read | `users:read` | — | — | ✓ | account metadata only |
| Accounts: change role | `users:role:assign` | — | — | ✓ | other accounts only |
| Accounts: deactivate / reactivate | `users:status:manage` | — | — | ✓ | other accounts only |
| Audit log | `audit:read` | — | — | ✓ | the whole log, read-only; integrity check |
| Operations dashboard, errors, conflicts, jobs list | `ops:read` | — | — | ✓ | system / corpus status ([ADMIN_OPERATIONS.md](ADMIN_OPERATIONS.md)) |
| Validate scheme data | `ops:validate` | — | — | ✓ | read-only checks |
| Start ingestion / graph-rebuild jobs | `ops:jobs:run` | — | — | ✓ | dry run by default; real run needs confirmation |
| Own notifications, preferences, followed schemes, phone | `notifications:own` | ✓ | ✓ | ✓ | own account only ([SCHEME_UPDATES.md](SCHEME_UPDATES.md)) |
| Detect / approve / reject / discard scheme changes | `scheme_changes:review` | — | — | ✓ | change batches; consequential approvals need confirmation + note |
| Publish approved changes (job `PUBLISH_CHANGES`) | `ops:jobs:run` + `scheme_changes:review` | — | — | ✓ | only fully reviewed batches |
| Notification delivery status, dispatch retries | `notifications:admin` | — | — | ✓ | delivery metadata only (account id, no e-mail or phone) |

Notes on the matrix:
- **Own data** is always the signed-in account's. No `/farmers/me/*` route takes an account id, and every
  query is filtered by the session's account. Staff accounts get the same self-service, but only over
  their own data.
- **Separation of duties:** administrators can see the review queue but can't decide cases; a decision
  needs a reviewer. Reviewers can't touch accounts, scheme data or the audit log.
- **Least privilege for administrators:** they see account metadata only (e-mail, name, role, status,
  verified, locked, created, last sign-in). They never see profiles, saved schemes, search history or
  phone numbers, because no permission grants that.
- **Scheme data:** phase 6 §64 says corrections belong to the corpus curation process, and nobody can
  edit rules, documents or other scheme content through the API. Administrators can only suspend or
  reactivate a scheme and flag it for curation (`PATCH /admin/schemes/{id}`). A corpus re-import restores
  the corpus values, and the response says so.
- **Audit log:** reviewers see the review history of a case they open; only administrators can read the full log.
- **Public (no account):** chat, voice, TTS, the scheme catalogue, languages, health, and the sign-in /
  registration endpoints.

## Rules that cannot be bypassed

- **The REVIEWER role alone gives no review access:** an administrator must approve the account. `Principal.for_account` removes `review_cases:read` and `review_cases:decide` from unapproved reviewers. A role change clears the approval.
- **Recent sign-in for sensitive actions:** `ensure_recent_auth` in `app/api/deps.py` returns 403 `REAUTH_REQUIRED` unless the session signed in or re-entered the password within `REAUTH_WINDOW_MINUTES`.
- **The role comes from the account row**, which is loaded with the session on every request. It is never
  taken from a request, a cookie or the frontend. A role change or deactivation applies to the very next
  request, and it also ends the account's sessions.
- **Nobody chooses their own role:**
  - registration and profile updates reject a `role` field (422);
  - every account starts as `FARMER`;
  - no route changes your own role or status (403 `SELF_CHANGE`);
  - the **last active administrator** can't be demoted or deactivated (409 `LAST_ADMIN`). Role and status
    changes lock the rows involved, so two administrators demoting each other at the same moment still
    leave one (tested on PostgreSQL).
- **The first administrator** can only be created on the server, by someone with database access:
  `python scripts/set_role.py you@example.com ADMIN` (in Docker: `docker compose exec backend python ../scripts/set_role.py …`).
  This change is audited as `cli:set_role`.
- **Every state change** with the session cookie needs `X-CSRF-Token` (403 `CSRF_FAILED`).
- **The reviewer recorded on a review decision** is the signed-in account. A `reviewer_id` sent in the
  request body is rejected (422).
- **IDOR:** another account's resources answer 404 (saved schemes, checklist items, search entries), the
  same as missing ones. Admin routes address accounts by their public UUID and are admin-only.
- **Deny-by-default test:** `test_rbac.py` fails if a non-public route has no permission dependency, or
  is missing from the tested matrix.

| Response | When |
|---|---|
| 401 `NOT_AUTHENTICATED` | not signed in, the session expired or was revoked, or the account was deactivated |
| 403 `FORBIDDEN` | the role lacks the permission (also refused inside the service functions) |
| 403 `CSRF_FAILED` | a state change without a valid `X-CSRF-Token` |
| 403 `SELF_CHANGE` | changing your own role or status |
| 409 `LAST_ADMIN` / `CONFLICT` | the last active administrator; or the role changed since you looked (`expected_role`) |

## Development-only reviewer key

The original phase 6 shared key (`X-Review-Key: $REVIEW_API_KEY`) still works, for the demo server, the smoke
test and the evaluation. Its limits:
- it acts for **no account**: review read / decide only, never own-data or admin permissions;
- it sees **only review cases not linked to a farmer**, and can't assign or grant;
- it is **refused when `ENVIRONMENT=production`** or when `REVIEW_API_KEY` is unset;
- decisions made with it are recorded under `review-key`.

In production, use reviewer accounts.

## Audit log (`audit_events`, migration 0006)

It records:
- `ROLE_CHANGED`, `ACCOUNT_DEACTIVATED`, `ACCOUNT_REACTIVATED`, `SCHEME_CURATED` (with before / after);
- review decisions (`REVIEW_<ACTION>`, `REVIEW_DISMISSED`);
- `ACCESS_DENIED`: a signed-in account refused a permission, with the endpoint and the permission;
- scheme updates: `CHANGES_DETECTED`, `CHANGE_REVIEWED` (also refused approvals), `CHANGE_BATCH_DISCARDED`, `CHANGES_PUBLISHED`;
- reviewer access: `REVIEWER_APPROVED`, `REVIEWER_APPROVAL_REVOKED`, `REVIEW_ACCESS_GRANTED` / `_REVOKED`, `REVIEW_QUEUE_VIEWED`, `REVIEW_CASE_VIEWED`, `REVIEW_CASE_ACCESS_DENIED` (DENIED), `REAUTHENTICATION` (SUCCESS / FAILURE);
- review workflow: `REVIEW_CASE_CREATED`, `REVIEW_ASSIGNED`, `REVIEW_UNASSIGNED`, `REVIEW_COMMENTED`, `REVIEW_<ACTION>`, `REVIEW_DISMISSED` (same transaction as the case change);
- notification consent: `NOTIFICATION_CONSENT` (e-mail / SMS on or off, consent-text version), `PHONE_VERIFIED`, `NOTIFICATION_UNSUBSCRIBED`.

How it is stored:
- Administrative changes and their audit row are written in **one transaction**.
- Review decisions also go to the in-memory review log (phase 6 §70). Their database copy is best effort,
  so a demo without PostgreSQL still works.
- The table is **append-only**: a database trigger rejects UPDATE and DELETE, and no API route writes or deletes events.
- Actors are stored by value (account id + e-mail + role), so deleting an account doesn't rewrite history.
- No secrets are logged (no passwords, tokens or keys).

## API

| Method | Path | Permission |
|---|---|---|
| GET | `/auth/permissions` | signed in (your own role and permissions) |
| GET | `/admin/users?role=&q=&limit=&offset=` | `users:read` |
| GET | `/admin/users/{farmer_id}` | `users:read` |
| PATCH | `/admin/users/{farmer_id}/role` `{role, expected_role?}` | `users:role:assign` |
| PATCH | `/admin/users/{farmer_id}/status` `{is_active}` | `users:status:manage` |
| PATCH | `/admin/users/{farmer_id}/reviewer-approval` `{approved}` | `users:reviewer:approve` (+ recent sign-in) |
| PATCH | `/admin/schemes/{scheme_id}` `{status?, needs_review?, review_notes?}` | `schemes:curate` |
| GET | `/admin/audit-events?action=&target_type=&target_id=&actor=&limit=&offset=` | `audit:read` |
| GET / POST | `/review-cases…` (list, case, claim, release, comments, resolve, dismiss) | `review_cases:read` / `review_cases:decide` |
| POST | `/review-cases/{id}/assign`, `/grants`, `/grants/revoke` | `review_cases:assign` (+ recent sign-in to assign / grant) |
| GET | `/farmers/me/review-cases` | `review_cases:own:read` |
| GET / POST | `/admin/scheme-changes…` | `scheme_changes:review` ([SCHEME_UPDATES.md](SCHEME_UPDATES.md)) |
| GET / POST | `/admin/notifications/deliveries`, `/admin/notifications/dispatch` | `notifications:admin` |
| … | `/farmers/me/notifications…`, `/notification-preferences`, `/subscriptions…`, `/phone…` | `notifications:own` |
| POST | `/notifications/unsubscribe`, `/notifications/sms-status` | public: signed token / HMAC signature |
| … | `/farmers/me/…` | the matching `*:own:*` permission |

The operations dashboard is at `/admin` ([ADMIN_OPERATIONS.md](ADMIN_OPERATIONS.md)). There is no review or
account-management screen yet; use the API (`/docs`) for those.

## Tests

- `backend/app/tests/test_rbac.py` (301 tests, including the scheme-update, notification and reviewer-dashboard routes) runs through the HTTP API with real cookie sessions. It covers:
  - every protected endpoint × every role, plus anonymous callers and missing CSRF;
  - deny-by-default route coverage, and an unknown role;
  - privilege escalation: role in registration or profile, self change, last admin, stale role;
  - sessions ended on a role change or deactivation;
  - IDOR and scope: admin sees no profile data; reviewers stay in the review queue;
  - the reviewer name cannot be spoofed; admin can't decide cases; dev-key limits and its production cut-off;
  - service-level denials, and the audit trail.
- `backend/app/tests/test_rbac_pg.py` (8 tests, opt-in `TEST_DATABASE_URL`) runs on PostgreSQL. It covers:
  - the migration and the role constraint; the append-only trigger;
  - role change + audit + session revocation together; the self and last-admin rules (also two concurrent demotions);
  - curation audit; listing filters; the `set_role.py` bootstrap.
