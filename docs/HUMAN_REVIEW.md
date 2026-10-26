# Human-in-the-Loop Review

When the automated system can't give a reliable answer, it opens a **review case** for a person.
Reviewers work the cases on the **reviewer dashboard** (`/review`). Farmers can see the status of cases their own searches raised.
A human decision is recorded **next to** the automated result. It never changes the automated result, and it never changes scheme rules.

## When a case is opened

The service is `services/review_workflow.py`, called from `agents/recommendation_agent.py` after every scheme search. Only deterministic triggers are used, checked in this order:
1. **RULE_CONFLICT**: a scheme's structured rules contradict each other.
2. **UNVERIFIABLE**: a candidate couldn't be evaluated (no structured rules, rule loading failed, or an evaluation error).
3. **SOURCE_CONFLICT**: database and web values differ for a structured field.
4. **SYSTEM_ERROR**: two or more retrieval channels failed.

**One open case per session and reason:** a partial unique index enforces this, also when several requests arrive at once, so repeated searches don't flood the queue. A new case can open after the previous one is closed.

`INSUFFICIENT_DATA`, `AMBIGUOUS_QUERY` and `OTHER` exist as reasons for cases created manually.

## Access policy

It is enforced on the server, in `services/review_workflow.py`, on every request; the `/review` page only reflects it.

**Who can work cases**
- **REVIEWER role + approval:** only REVIEWER accounts that an administrator has **approved** (on `/admin` → "Reviewer access", or with `scripts/set_role.py <email> REVIEWER --approve`).
  - The role alone grants only the account's own data.
  - Approval is re-read with the account on every request, so a revocation applies to the next request.
  - Revoking approval, or any role change, also **ends the reviewer's sessions and case grants**. A role change clears the approval.
- **Administrators** oversee: they see every case, assign or reassign cases to approved reviewers, and give read grants. They **never decide**.
- **Everyone else:** farmers get 403; anonymous and forged-cookie calls get 401, on every review endpoint.

**Which cases a reviewer can see**

| Case | What the reviewer gets |
|---|---|
| Assigned to them | The full case; they act on it |
| Explicitly **granted** to them by an administrator (expiring, 1–168 h, revocable) | The full case, read and comment only; never claim or decide |
| Unassigned and PENDING (the queue) | A **summary only** (scheme, reason, status, dates): no question, profile, evidence or history. Taking the case is what opens it. Set `REVIEW_SELF_ASSIGN=false` to allow only administrator assignment. |
| Anything else | Doesn't exist for them: **404, the same answer as a case that doesn't exist** (no existence oracle). The attempt is audited as `REVIEW_CASE_ACCESS_DENIED` (DENIED). |

- **Field-level minimisation:**
  - Case views never include the farmer's account, session or chat thread id.
  - The stored question is redacted (phone, e-mail and ID-like numbers are masked).
  - The profile snapshot holds only the fields the triggering rules use.
  - Reviewers have no route to farmer profiles, accounts, or the admin user list.
- **No exports or scraping:**
  - There is no export endpoint; the queue returns summaries, and pages are at most 50.
  - Full-case views are rate-limited per reviewer (`REVIEW_VIEWS_PER_10_MIN`, default 120); excess views get 429 and are audited.
  - Every review response is sent with `Cache-Control: no-store`.
- **Staff sessions** (REVIEWER / ADMIN):
  - **Shorter timeouts:** 30 minutes idle (`STAFF_SESSION_IDLE_MINUTES`) and 12 hours in total (`STAFF_SESSION_ABSOLUTE_HOURS`); farmers keep their longer sessions.
  - **Bound to the browser:** a stolen cookie used from another browser is revoked.
  - **Revoked by account changes:** sessions end on revocation, a role change or deactivation.
- **Reauthentication:** these actions need a sign-in or a password confirmation (`POST /auth/reauthenticate`) within `REAUTH_WINDOW_MINUTES` (default 10):
  - final decisions and dismissals;
  - assignments and grants;
  - reviewer approval.

  Otherwise the server answers **403 `REAUTH_REQUIRED`**, and the page asks for the password and retries. Five wrong passwords end the session. Both outcomes are audited (`REAUTHENTICATION`). Taking a case, commenting and requesting verification don't need it.
- **Audit:** every queue view (`REVIEW_QUEUE_VIEWED`) and case view (`REVIEW_CASE_VIEWED`, with the access level) is audited, along with every denied attempt and every state change. With PostgreSQL, a view whose audit record can't be written is refused (fail closed).
- **The development-only review key** (`X-Review-Key`):
  - sees only cases **not linked to a farmer**;
  - can't assign or grant, and has no access to administrator routes;
  - is refused in production.

## What a reviewer sees

- **Scheme:** the scheme(s) with their official website links.
- **Why:** the escalation reason.
- **Automated result:** status and missing information, shown read-only.
- **Supporting evidence:** the official source text of each rule, with its source URL.
- **Conflicting values:**
  - contradicting rule bounds or values;
  - database-vs-web values per source;
  - the names of failed retrieval channels.
- **The farmer's question** (500 characters at most).
- **Minimal profile:** only the fields the triggering rules use, plus the state. Identity fields are never stored: name, phone, e-mail, Aadhaar, bank, PAN, address, account id. Other profile fields (age, gender, …) are dropped unless a triggering rule uses them.
- **Whether a signed-in farmer follows the case:** shown as yes/no only, never who the farmer is.
- **The case reference**, so a farmer's reference number can be matched without revealing who the farmer is.
- **Workflow details:** assignee, timestamps, comments, and the complete history.

## Workflow

```
                 take (claim) / admin assigns / request verification
     PENDING ───────────────────────────────────────────────▶ IN_REVIEW ──approve / reject /──▶ RESOLVED
        ▲                                                         │  │      mark unverifiable /
        └────────────────────────── release ──────────────────────┘  │      resolve
     PENDING / IN_REVIEW ──dismiss──▶ DISMISSED                      └─ request additional verification
                                                                         (stays IN_REVIEW, flagged
                                                                          "awaiting verification")
```

| Action | From → to | Who | Meaning |
|---|---|---|---|
| Take (`claim`) | PENDING → IN_REVIEW | approved reviewer (queue case) | The case is assigned to you; nobody else can see or act on it |
| Release | IN_REVIEW → PENDING | the assignee | Back to the queue, unassigned |
| Assign | PENDING / IN_REVIEW → IN_REVIEW | administrator (recent sign-in) | Assign or reassign to an active, approved reviewer |
| Request additional verification (`REQUEST_INFORMATION`) | PENDING / IN_REVIEW → IN_REVIEW | reviewer / assignee | Someone is checking with the official source; the case stays open |
| Approve | IN_REVIEW → RESOLVED | the assignee | The automated result is correct |
| Reject | IN_REVIEW → RESOLVED | the assignee | The automated result or the scheme data is wrong; can flag **data correction needed** |
| Mark unverifiable | IN_REVIEW → RESOLVED | the assignee | It can't be confirmed from official sources |
| Resolve | IN_REVIEW → RESOLVED | the assignee | Handled without a verdict on the result (e.g. a temporary outage) |
| Dismiss | PENDING / IN_REVIEW → DISMISSED | reviewer / assignee | No action needed (duplicate, false alarm) |
| Comment | any status | assignee or grantee | Notes for colleagues; doesn't change the case |
| Grant / revoke read access | — | administrator (recent sign-in) | Another approved reviewer may read and comment for 1–168 hours |

**Rules:**
- **RESOLVED and DISMISSED are final.** Any further action gets 409.
- **Notes:** decisions and dismissals need a note (at least 3 characters; up to 2000). Contact data and secrets in notes are redacted.
- **Assignee only:** only the assignee acts on an IN_REVIEW case. A grantee gets 409 `ASSIGNED_TO_OTHER`; any other reviewer gets 404 (the case isn't theirs); an administrator can reassign.
- **Dismissing from the queue:** a queue case that is dismissed becomes the dismisser's case, so it stays visible to them.
- **Recent sign-in:** final decisions and dismissals need one (see Access policy).
- **Concurrency:** every change carries the version the reviewer saw (`expected_version`); the server also re-checks it atomically. A stale view gets 409 `VERSION_CONFLICT` and the page reloads the case. So two reviewers can never both take or decide the same case. The tests cover this with simultaneous requests, including on separate PostgreSQL connections.
- **Audit:** each step is written to the case history (`review_case_events`, append-only, enforced by a database trigger) and to the hash-chained `audit_events`, **in the same transaction**. Recorded actions:
  - `REVIEW_CASE_CREATED`, `REVIEW_ASSIGNED`, `REVIEW_UNASSIGNED`, `REVIEW_COMMENTED`;
  - `REVIEW_REQUEST_INFORMATION`;
  - `REVIEW_APPROVE` / `_REJECT` / `_MARK_UNVERIFIABLE` / `_RESOLVE`, `REVIEW_DISMISSED`.

## Human decisions vs. automated results vs. scheme rules

- **The automated eligibility result is never changed.** The case keeps the engine's original output, and the dashboard and chat keep computing eligibility deterministically.
- **The review code can't change scheme data:** it has no route or code path that writes schemes or eligibility rules, and a test checks this. Requests can't carry rules or statuses (unknown fields give 422).
- **A wrong rule** is fixed only through the separate, verified and versioned scheme-update process ([SCHEME_UPDATES.md](SCHEME_UPDATES.md)): an administrator detects the correction, approves it, and publishes a new corpus version. "Data correction needed" on a Reject marks the case for that follow-up.

## What farmers see (unresolved cases are clearly communicated)

- **Chat:** the reply ends with "Some results could not be verified automatically and have been flagged for review by a person. Please treat them as unconfirmed." Signed-in farmers also get a line pointing to their dashboard. The API response carries `review: {needs_review, reason, case_id}`.
- **Dashboard → "Checks by our team"** (signed-in farmers whose search raised a case):
  - shows the scheme, a plain-language reason, and whether the case is open;
  - open cases are highlighted and labelled **unconfirmed**, with advice to check the official website before applying;
  - closed cases show the outcome: confirmed, problem found and being corrected, couldn't verify, resolved, or no action needed;
  - reviewer names, notes and evidence are never shown.
- **Eligibility list:** a scheme with an open case shows "Being checked by our team — treat this result as unconfirmed".
- **Anonymous searches** aren't linked to anyone; they get the chat notice only.

## API

Permissions (see [RBAC.md](RBAC.md)):
- **REVIEWER:** `review_cases:read`, `review_cases:decide`, **only once approved**; the case scope above applies on top.
- **ADMIN:** `review_cases:read`, `review_cases:assign`, `users:reviewer:approve`; administrators don't decide (separation of duties).
- **Farmers:** `review_cases:own:read`.
- **The reviewer recorded** is always the signed-in account; a `reviewer_id` in the body gets 422.
- **Development-only key:** `X-Review-Key: $REVIEW_API_KEY` can read and decide, acting as "review-key". It is refused in production and when the key is unset.

| Method | Path | Notes |
|---|---|---|
| GET | `/review-cases?status=&reason=&assigned=me\|unassigned&limit=&offset=` | `{cases, total, stats}`: **summaries** of the cases in your scope (each with `access`); counts cover your scope only. Open statuses oldest first (a queue); resolved / dismissed / all newest first. `limit` ≤ 50. |
| GET | `/review-cases/stats/summary` | Counts per status, plus awaiting verification |
| GET | `/review-cases/{id}` | `{case, access, history, audit_log}`; administrators also get `grants`. Assigned / granted / admin only, otherwise 404. Audited and rate-limited. (`audit_log` is the earlier phase 6 shape.) |
| POST | `/review-cases/{id}/claim` `{expected_version?}` | Take the case |
| POST | `/review-cases/{id}/release` `{expected_version?}` | Give it back |
| POST | `/review-cases/{id}/assign` `{reviewer_email, expected_version?}` | Administrators; recent sign-in |
| POST | `/review-cases/{id}/grants` `{reviewer_email, hours}` · `/grants/revoke` `{reviewer_email}` | Administrators; granting needs a recent sign-in |
| PATCH | `/admin/users/{farmer_id}/reviewer-approval` `{approved}` | Administrators; recent sign-in; revoking signs the reviewer out |
| POST | `/auth/reauthenticate` `{password}` | Signed in; confirms the password for sensitive actions |
| POST | `/review-cases/{id}/comments` `{text}` | 201 |
| POST | `/review-cases/{id}/resolve` `{action, note, expected_version?, data_correction_needed?}` | `REQUEST_INFORMATION`, `APPROVE`, `REJECT`, `MARK_UNVERIFIABLE`, `RESOLVE` (the last four need a recent sign-in) |
| POST | `/review-cases/{id}/dismiss` `{note, expected_version?}` | Recent sign-in |
| GET | `/farmers/me/review-cases` | The farmer's own cases, in plain language |

Errors (`detail.code`):
- 400 `BAD_FILTER` / `BAD_ACTION`;
- 403 `FORBIDDEN` / `REAUTH_REQUIRED`;
- 404 `NOT_FOUND` (also: not in your scope) / `NO_GRANT`;
- 409 `INVALID_TRANSITION` / `ASSIGNED_TO_OTHER` / `VERSION_CONFLICT` / `ALREADY_ASSIGNED`;
- 422 `NOTE_REQUIRED` / `NOT_A_REVIEWER` / `BAD_DURATION`;
- 429 `RATE_LIMITED`.

## Storage (migrations `0009`, `0010`)

- **`review_cases`:** check constraints ensure RESOLVED has a decision and IN_REVIEW has an assignee. `farmer_id` is set to NULL if the account is deleted; the case itself stays for the record.
- **`review_case_events`:** the append-only history.
- **Migration `0010` adds:**
  - `farmers.reviewer_approved_at` / `_by`, with a check that only REVIEWER accounts can be approved;
  - `auth_sessions.reauthenticated_at`;
  - `review_case_grants`: expiring and revocable, with at most one active grant per case and reviewer.

  Existing REVIEWER accounts are **not** approved by the migration.
- **Without a database** (keyless demo, offline evaluation runners), the same workflow runs on the in-memory queue in `review_service.py`. Its original synchronous functions still work.

**Demo case from real data:** `python scripts/raise_review_case.py [--email farmer@example.com]`. It evaluates an active scheme without structured rules (so the result is UNVERIFIABLE) and escalates it as the pipeline would.

## Tests

- `backend/app/tests/test_review_workflow.py` (30 tests, HTTP API, real sessions, real engine results) covers:
  - **queue:** filters, counts, order and paging;
  - **case content:** evidence, URLs, conflicting values, failed channels, minimal profile, no identity data;
  - **transitions:** every transition, final states, notes, unknown actions;
  - **assignment:** admin assigns but can't decide; farmer 403 and anonymous 401; reviewer identity and rules can't be sent;
  - **concurrency:** stale versions, 5 simultaneous claims, double-submitted decisions, simultaneous escalations;
  - **audit:** history and audit trail; comments; no edit or delete route;
  - **separation:** the automated result is unchanged; no scheme writes;
  - **farmers:** dedupe; the pipeline node; a chat case linked to the farmer with the outcome, without reviewer details; dashboard flags.
- `backend/app/tests/test_review_pg.py` (7 tests, opt-in `TEST_DATABASE_URL`) covers:
  - the migration is reversible, and the constraints hold;
  - the full workflow writes the history and a valid audit chain;
  - simultaneous claims and escalations on separate connections;
  - the history is append-only;
  - the farmer link, and account deletion;
  - SQL filters.
- `backend/app/tests/test_review_access_policy.py` (28 security tests) covers:
  - **approval:** an unapproved reviewer is refused everywhere; approval and revocation (sessions ended); approval rules; the principal is rebuilt on every request;
  - **cross-case access:** every endpoint on another reviewer's case gives 404 with the same body as a missing case, is audited, and changes nothing; listings and counts cover only your scope; queue summaries have no farmer or evidence fields; the question is redacted; closed cases stay with their reviewer; self-assignment can be switched off;
  - **grants:** a grantee reads and comments but can't act; expiry and revocation; grant rules;
  - **reviewer → admin escalation:** 13 administrator operations refused and audited; the review key sees no farmer-linked cases; no farmer-profile browsing;
  - **direct API calls:** no or forged cookie gives 401 everywhere; CSRF; a stolen cookie from another browser; no-store headers; view rate limit; no bulk page size;
  - **sessions:** staff idle and absolute expiry; reauthentication for decisions, dismissals and admin actions; reauthentication expiry; 5 wrong passwords end the session;
  - **audit:** views and state changes are recorded.
- `backend/app/tests/test_review_access_pg.py` (5 tests, opt-in) runs on PostgreSQL: the migration and the approval constraint; revocation ends sessions and grants in one transaction (valid audit chain); a role change clears approval; scoped listing, grant expiry, re-grant and revoke in SQL; the reauthentication timestamp.
- `scripts/ui_review_test.py` (14 checks, real browser):
  - the farmer sees the open check as unconfirmed, and neither a farmer nor an **unapproved reviewer** can open `/review`;
  - an administrator approves the reviewer on `/admin`;
  - the queue shows a **summary only**; after taking the case, the reviewer sees the evidence, comments, requests verification and approves;
  - a second reviewer acting on a stale view is refused, and a direct API call for that case gives 404;
  - the farmer sees the outcome.
- The phase 6 review runner and the smoke test still use the original API shape.
