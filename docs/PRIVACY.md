# Privacy, Data Flow, Retention and Deletion

Farmers see and manage all of this on **`/privacy`** ("Privacy and data settings"). The page is public; signed-in users also get their own data controls.
The page, the API (`GET /privacy/policy`) and this document draw on one source, **`backend/app/core/privacy.py`**. A test fails if a stored profile column isn't described there.

## Data flow

```
                  ┌─────────────────────── SchemeSetu server ───────────────────────┐
 browser ──HTTPS──▶ FastAPI ─▶ chat pipeline (in memory) ─▶ eligibility rules (local) │
   ▲  cookie        │    │            │  ▲                                           │
   │  (HttpOnly)    │    │            │  └── saved profile (only with consent)        │
   │                │    ▼            ▼                                              │
   │                │  PostgreSQL: account, profile, history, saved schemes,         │
   │                │  notifications, review cases, sessions, audit log              │
   │                └────┬──────────────┬───────────────┬──────────────┬────────────┘
   │                     ▼              ▼               ▼              ▼
   │               Groq (LLM)     Tavily (web)   Sarvam (translate,  E-mail / SMS
   │               chat text +    state + crop   speech)             provider
   │               safe profile   + fixed topic  message & reply     address/number
   │               summary                       text, voice audio   + message
```

- **Eligibility is decided on the server** by fixed rules. The LLM never decides it.
- **External processing is real.** When a provider key is configured, the data above leaves the server and is handled under that provider's own terms and retention. Nothing on the page or here claims otherwise.

| Provider | Receives | When |
|---|---|---|
| **Groq** (LLM) | The recent chat messages in full, so whatever the farmer types or says, including personal details. From the profile: only state, district, land size in acres, main crop and occupation (`app/utils/privacy.py`). Scheme cards with age, gender, category and income values masked; other criterion values (e.g. rural/urban) can appear. | Every chat / voice turn |
| **Tavily** (web search) | `"<topic words> <state> <crop> farmer government scheme eligibility benefits"` — topic words only from a fixed list (insurance, loan, irrigation…), never the question text, age, category or income (`app/live/discovery.py`). The official pages found are fetched by SchemeSetu's server (`SchemeSetuBot` user agent, robots.txt respected); those sites see the server, not the farmer | Scheme searches (query-time live check, [LIVE_VERIFICATION.md](LIVE_VERIFICATION.md)) |
| **Sarvam AI** | The full text of non-English messages and replies, voice recordings, and reply text for speech | Other languages / voice |
| **E-mail (SMTP)** | E-mail address + content | Verification, reset, opted-in notifications |
| **SMS provider** | Phone number + message | Only after phone verification + SMS consent |

## What is collected

Required for an account: **e-mail** and **password** (stored only as an Argon2id hash).

Optional:
- **Account details:** name, and a mobile number (for SMS only).
- **Profile details**, all optional: state, district, land size + unit, main crop, other crops, farming type, occupation, age, gender, social category, income range, rural/urban.
  - Saving any profile detail requires **consent** (`consent_given`, with the time it was given).
  - A missing detail makes a result "needs more information", never "not eligible".
  - What each detail is used for: see [PROFILE.md](PROFILE.md) and the `/privacy` field table.

Never collected:
- Aadhaar number, Aadhaar status, bank account, PAN;
- exact income (only a range);
- device location.

## Consent

- **Profile and history:** the first profile save needs `consent_given: true` (403 otherwise). Chat saves details only when the farmer ticks "keep my details" (`consent_to_save_profile`). Search history is recorded only while consent exists.
- **Withdrawing consent:** `DELETE /farmers/me/profile`, the "Delete profile" button on `/privacy`. It deletes the profile **and** the search history recorded under it; from then on the chat neither loads nor saves profile details and no searches are recorded. Saving details again needs fresh consent.
- **SMS:** a separate, versioned consent, recorded when given; turning SMS off is an opt-out ([SCHEME_UPDATES.md](SCHEME_UPDATES.md)).

## The farmer's controls

All of these act on the **signed-in account only**: no route accepts a farmer id. Writes need the CSRF header; responses are `no-store`.

| Action | Route | Notes |
|---|---|---|
| See what is stored | `GET /farmers/me/data` | Filled profile fields, counts per category, consent time |
| View / edit profile | `GET` / `PUT /farmers/me/profile` | [PROFILE.md](PROFILE.md) |
| Export everything (JSON) | `GET /farmers/me/data/export` | Recent sign-in required (password dialog); 5 per hour; audited (`DATA_EXPORTED`). Includes account, profile, searches, saved schemes + checklists, notification settings, followed schemes, messages, review cases (farmer view), sessions. Never includes password hashes or tokens. |
| Delete profile + history (withdraw consent) | `DELETE /farmers/me/profile` | Audited `PROFILE_DELETED` |
| Delete search history | `DELETE /farmers/me/search-history` | [DASHBOARD.md](DASHBOARD.md) |
| Delete saved schemes + checklists | `DELETE /farmers/me/saved-schemes` | Audited |
| Delete notification data | `DELETE /farmers/me/notification-data` | Preferences + SMS consent, followed schemes, messages (queued deliveries are cancelled), phone number, phone codes. Audited. |
| Delete the account | `POST /farmers/me/delete-account` `{password, confirm: "DELETE MY ACCOUNT"}` | See below |

## What account deletion does

One database transaction (`privacy_repository.delete_account`):

| Store | Effect |
|---|---|
| `farmers` row | Deleted. Every per-farmer table cascades: `farmer_profiles`, `search_history`, `saved_schemes`, `saved_scheme_checklist_items`, `scheme_subscriptions`, `notification_preferences`, `notifications`, `notification_deliveries` (not-yet-sent e-mails and SMS are cancelled), `auth_sessions` (signed out everywhere), `auth_tokens`, `refresh_tokens`, `review_case_grants` |
| `review_cases` raised by the farmer | Unlinked (`farmer_id` NULL) and anonymised: the question and the profile snapshot are cleared. The scheme, reason, public rule evidence and the decision are kept as an anonymous quality record. |
| Open cases assigned to them (reviewer accounts) | Returned to the queue, with a history entry |
| `audit_events` | One `ACCOUNT_DELETED` event naming **the account id only** (actor `account:<uuid>`, no e-mail) |
| Chat conversations in server memory | Conversations linked to the farmer's review cases are dropped, plus any thread ids the client sends |
| In-memory rate-limit counters | Counters for the e-mail are dropped |
| Session cookie | Cleared in the response |

**Rules:**
- The password must be re-entered, and the confirmation typed. A wrong password gives 400, a missing or wrong confirmation 422.
- The **last active administrator** can't delete their account (409 `LAST_ADMIN`).
- Afterwards the e-mail can't sign in, and the address can register again as a new, empty account.

## Retention

The rules run at startup and then every `RETENTION_PURGE_INTERVAL_HOURS` (default 24), in `privacy_service.purge`. The defaults are configurable:

| Data | Kept |
|---|---|
| Search history | Newest 50, at most **90 days** (also pruned on every read and write) |
| Ended sessions (revoked / expired) | Deleted **30 days** after they ended (`RETENTION_SESSION_DAYS`) |
| One-time tokens (verify, reset, phone), legacy refresh tokens | Deleted **7 days** after use / expiry (`RETENTION_TOKEN_DAYS`) |
| In-app notifications (and their deliveries) | **365 days** (`RETENTION_NOTIFICATION_DAYS`) |
| Closed review cases | Anonymised **365 days** after closing (`RETENTION_REVIEW_CASE_DAYS`): question and profile snapshot cleared, unlinked |
| Profile, saved schemes, notification settings, account | Until the farmer deletes them |
| Chat conversations | Server memory only: at most `MAX_SESSIONS` (1000) conversations, lost on restart |
| Voice recordings | Not stored (sent to Sarvam for transcription) |

## Exceptions: when deletion is delayed or limited

These are also listed on `/privacy`, and in the delete-account response (`still_kept`).

| What | Why | How long |
|---|---|---|
| **Audit log** (`audit_events`) | Append-only and hash-chained so tampering is detectable. Removing rows would break the chain. Earlier events the farmer caused keep their account id; staff actions keep the staff e-mail. | Today kept without a limit. Pseudonymising old entries would need a re-chaining migration. |
| Review history written by staff | Reviewer accountability (`review_case_events.actor`, `scheme_changes.reviewed_by`, `admin_jobs.requested_by`) | With the record |
| Review cases | Kept anonymised as a quality record (see above) | Indefinitely, anonymised |
| Data already sent to Groq / Tavily / Sarvam / e-mail / SMS providers | Their own terms; SchemeSetu can't delete it there | Their retention |
| Server logs | Operational logs. In development without SMTP, e-mails (with the address and links) are printed to the backend log. | Until log rotation (Docker logging settings) |
| Database backups | SchemeSetu makes none for personal data (`data/backups/` holds the public corpus only). Operator backups keep deleted data. | Until the operator's backups expire; document their rotation |
| Last administrator | The system must keep one | Until another admin exists |

**Operators:**
- Set the Docker log rotation (e.g. `max-size`, `max-file`).
- Don't enable SMTP logging in production.
- Keep database backups encrypted, with a documented rotation shorter than your deletion promise.

## Tests

- `backend/app/tests/test_privacy.py` (22 tests, HTTP API with real sessions) covers:
  - **inventory:** every stored profile column is documented; required vs optional; the disclosures match what the code actually sends (the LLM-safe fields, the web-search query); no "local" claims about external processing; the public policy has no personal data;
  - **consent:** nothing is saved without it; withdrawal deletes the profile and history and stops chat sync and recording;
  - **export:** contains everything of mine and nothing of others, no secrets, audited; needs a recent sign-in; rate-limited;
  - **deletion:** each category; CSRF and session required; the account and everything with it; password and typed confirmation; last admin; a deleted reviewer's cases are released;
  - **isolation:** no route takes another account; staff see only their own data; the retention rules are passed to the purge.
- `backend/app/tests/test_privacy_pg.py` (4 tests, opt-in `TEST_DATABASE_URL`) runs on PostgreSQL:
  - two farmers have rows in **every** per-farmer table; deleting one removes all of theirs, anonymises their review case and leaves the other untouched;
  - the audit event names only the account id, and the chain stays valid;
  - category deletes; the last-admin rule; release of a deleted reviewer's cases;
  - the retention purge (old rows removed or anonymised, fresh rows kept, profile kept).
- `scripts/ui_privacy_test.py` (12 checks, real browser):
  - signed out: the field table (required / optional, purpose, sharing), the processors, the exceptions;
  - signed in: export (own data only), deleting saved schemes, withdrawing consent, deleting the account (password + confirmation);
  - afterwards: the session is ended, sign-in is refused, and the other farmer's data is intact.
