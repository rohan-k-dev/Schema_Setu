# Human-in-the-Loop Review

Implemented as a controlled exception path: an **in-memory** queue plus a key-protected REST API. There is
**no reviewer web UI**. Reviewers use the API (for example Swagger UI at `/docs`).

## When escalation occurs (`services/review_service.py`, called from `agents/recommendation_agent.py`)
Deterministic triggers only, checked in this order after every scheme search:
1. **RULE_CONFLICT**: a scheme's structured rules contradict each other.
2. **UNVERIFIABLE**: at least one candidate could not be evaluated (no structured rules, rule loading
   failed, or an evaluation error).
3. **SOURCE_CONFLICT**: DB and web values differ for a structured field.
4. **SYSTEM_ERROR**: two or more retrieval channels failed.

At most **one open case per session and reason** is created, so repeated searches do not flood the queue.
`INSUFFICIENT_DATA`, `AMBIGUOUS_QUERY` and `OTHER` exist as reasons, but cases with them are created only manually.

## What is sent for review
`session_id`, the query (≤500 chars), the reason, the triggering scheme IDs and their statuses / missing
fields, source conflicts, and a profile snapshot **with identity fields removed** (`aadhaar_number`,
`bank_account`, `pan_number`, `phone_number`, `farmer_id`, `name`, `email`, `address`).

## What the user sees
The reply ends with: "Some results could not be verified automatically and have been flagged for review by
a person. Please treat them as unconfirmed." The API response carries
`review: {needs_review, reason, case_id}`. Eligibility results are **not** changed by escalation.

## Reviewer API (header `X-Review-Key: $REVIEW_API_KEY`; unset key → API disabled)
| Endpoint | Purpose |
|---|---|
| `GET /review-cases?status=PENDING` | List cases + queue stats |
| `GET /review-cases/{id}` | Case + audit log |
| `POST /review-cases/{id}/resolve` `{"action", "reviewer_id", "note"}` | `REQUEST_INFORMATION` (PENDING→IN_REVIEW), then `APPROVE` / `REJECT` / `MARK_UNVERIFIABLE` (IN_REVIEW→RESOLVED) |
| `POST /review-cases/{id}/dismiss` | PENDING or IN_REVIEW → DISMISSED |
| `GET /review-cases/stats/summary` | Counts per status |

Invalid transitions return HTTP 400. Every action is written to the audit log (case, action, reviewer,
timestamp, note).

## How decisions are represented and what they change
A decision is stored on the case (`reviewer_action`, `reviewer_note`, `reviewed_at`) and in the audit log. It
does **not** modify canonical scheme data or rules (§64). Corrections to the corpus go through the data
update path in `docs/DATA_FLOW.md`. The user is not notified of the decision; that is a known limitation.

## Unresolved cases
They remain PENDING/IN_REVIEW until actioned. The queue is lost on server restart (academic simulation;
see `docs/phase7-limitations.md`).

## Evidence
Review runner: 22/22 checks (escalation from real engine results, lifecycle, invalid transitions, all four
actions, audit, privacy, authorization). E2E20 confirms escalation inside the live pipeline. Demo: smoke test
"review case resolved".
