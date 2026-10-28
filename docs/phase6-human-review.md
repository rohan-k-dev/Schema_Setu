# Phase 6 — Human Review (HITL)

## Architecture

```
Eligibility Engine → should_escalate() → Review Queue → Reviewer UI → Resolution
```

Human review is an exception-handling workflow, NOT a parallel intelligence system.

## Escalation Triggers (§57)

| Trigger | ReviewReason | Description |
|---------|-------------|-------------|
| No structured rules for scheme | UNVERIFIABLE | System cannot verify eligibility |
| Contradictory rules detected | RULE_CONFLICT | Rules within a scheme conflict |
| DB vs Web vs Graph disagreement | SOURCE_CONFLICT | Different sources report different data |
| Multiple retrieval channels fail | SYSTEM_ERROR | System reliability concern |
| User data insufficient for evaluation | INSUFFICIENT_DATA | Cannot evaluate with available info |

All triggers are **deterministic** — no vague LLM judgment.

## Review Case Lifecycle (§125)

```
PENDING → IN_REVIEW → RESOLVED
PENDING → DISMISSED
IN_REVIEW → DISMISSED
```

Invalid transitions are rejected. Terminal states: RESOLVED, DISMISSED.

## Reviewer Actions (§63)

| Action | Effect |
|--------|--------|
| APPROVE | Case resolved — eligibility confirmed |
| REJECT | Case resolved — eligibility denied |
| REQUEST_INFORMATION | Case stays IN_REVIEW — needs more data |
| MARK_UNVERIFIABLE | Case resolved — genuinely unverifiable |

## API Endpoints (§122)

| Method | Endpoint | Purpose |
|--------|----------|---------|
| GET | `/review-cases` | List cases (optional `?status=` filter) |
| GET | `/review-cases/{id}` | Get single case + audit log |
| POST | `/review-cases/{id}/resolve` | Reviewer action |
| POST | `/review-cases/{id}/dismiss` | Dismiss case |
| GET | `/review-cases/stats/summary` | Queue statistics |

Protected by `X-Review-Key` header (development auth).

## Audit Log (§70, §126)

Every action records: case_id, action, reviewer, timestamp, note.

## Privacy (§61)

Profile snapshots in review cases have sensitive fields stripped:
- aadhaar_number
- bank_account
- pan_number
- phone_number

Only `has_aadhaar: true/false` may be retained.

## Limitations

- In-memory storage (academic demonstration per §67)
- Single reviewer model (no concurrent reviewer conflict detection)
- No email/notification integration
- Review does NOT directly edit schemes or eligibility rules (§64)

## Files

| File | Purpose |
|------|---------|
| `backend/app/models/review.py` | ReviewCase, ReviewStatus, ReviewAction, transitions |
| `backend/app/services/review_service.py` | Escalation triggers, queue, resolution |
| `backend/app/api/review.py` | REST API endpoints |
