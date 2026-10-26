# Scheme Updates and Notifications

When official scheme information changes, SchemeSetu finds the change, a person checks it, and only then
are the farmers who care about that scheme told. **Nothing scraped is trusted automatically.**

```
scraper → data/incoming/<name>.json → 1 DETECT → 2 VERIFY (admin) → 3 PUBLISH (admin job) → 4 NOTIFY
                                         PENDING      APPROVED/REJECTED    new corpus version     in-app / e-mail / SMS
```

## 1. Detect

A scraper writes its **normalised** output (the same format as `data/validated/schemes.json`) to
`data/incoming/`. An administrator then runs detection, either:
- on `/admin` → **Scheme updates** → pick the file → **Detect changes**, or
- with `python scripts/detect_scheme_changes.py <file>.json` (for a scheduled task).

Detection compares the file with the **last verified corpus** (`app/services/change_detection.py`):

| Category | What is compared | Consequential |
|---|---|:-:|
| `ELIGIBILITY` | eligibility rules | ✓ |
| `BENEFITS` | benefits (amounts normalised: "Rs. 6,000" = "₹6000") | ✓ |
| `STATES` | applicable states (empty list = all states) | ✓ |
| `STATUS` | active / inactive | ✓ |
| `NEW_SCHEME` / `MISSING_FROM_SOURCE` | scheme added to / gone from the source | ✓ |
| `DOCUMENTS` | required documents | — |
| `STEPS` | application steps | — |
| `URLS` | official and application links | — |

**False positives are filtered out.** Both sides are normalised first, so these are *not* changes:
- whitespace, case, quotes, dashes and punctuation-only edits;
- list order and duplicate entries;
- `2` vs `"2"` vs `2.0`;
- URL trailing slashes, fragments, tracking parameters, and http vs https;
- provenance-only differences (retrieval dates, content hashes, source text).

**Safety checks:**
- **Invalid records** are refused and listed. A broken record is never reported as "scheme missing".
- **A suspicious scrape is flagged:** more than 20 % of schemes missing, or more than 50 % changed at once, usually means the page layout changed rather than the schemes.
- **Only files inside `data/incoming/`** can be used (name pattern, 20 MB limit).

**Provenance:** each change stores:
- the source file name and its SHA-256;
- before and after values;
- the scheme's source records;
- who ran detection, and when.

**Duplicates:** each change has a fingerprint. A partial unique index stops the same change being stored twice while it is pending or approved, so re-running detection reports it as "already known".

## 2. Verify

Every change starts **PENDING**. An administrator (`scheme_changes:review`) approves or rejects each one.
- **Consequential changes need a deliberate approval:** the reviewer must tick "I checked this against the official source" and write a note of at least 10 characters. Otherwise the API returns `CONFIRMATION_REQUIRED`.
- **Audit:** every decision, including a refused one, is written to the audit log.
- **Discarding:** a whole open batch can be discarded.

## 3. Publish

The admin job `PUBLISH_CHANGES` (dry run available) runs only when **every** change in the batch is decided and at least one is approved. It:
1. **Refuses stale input:** the job stops if the candidate file changed after detection (SHA-256 mismatch), or if another batch was published meanwhile (base version mismatch).
2. **Merges only what was approved:** only the approved categories are taken from the candidate. An approved `MISSING_FROM_SOURCE` marks the scheme inactive; it is never deleted.
3. **Validates** the merged corpus. Any error stops the job.
4. **Writes** a new corpus version (atomic files, a backup in `data/backups/`, a dated snapshot) and imports it into PostgreSQL in one transaction.
5. **Rolls back on failure:** if the import fails, the files are restored from the backup and **nobody is notified**.

Afterwards, rebuild the Knowledge Graph (admin job `REBUILD_GRAPH`) so retrieval uses the new data.

## 4. Notify

Only after a successful publish, farmers are notified about each affected scheme they **saved** or **follow** (`PUT /farmers/me/subscriptions/{scheme_id}`). Rules:
- **One notification per account per scheme per batch** (`UNIQUE (account, dedupe_key)`). Publishing or notifying again creates no duplicates; saving *and* following a scheme still gives one message.
- **Consequential changes** say "important update" and ask the farmer to check that they still qualify. Every message says the change was checked against the official source.
- **Preferences** (`/dashboard` → Notification settings):

| Channel | Default | Needs |
|---|---|---|
| In-app | on | nothing |
| E-mail | off | SMTP configured (`SMTP_*`) + verified account e-mail. Every e-mail has a one-click unsubscribe link (`/unsubscribe`). |
| SMS | off | a configured provider + a phone number verified by code + explicit consent (time and consent-text version recorded) |

- **Consequential only:** a farmer can choose to hear only about consequential changes.
- **Inactive accounts** get nothing.

## Delivery, retries and SMS

Each e-mail or SMS is a row in `notification_deliveries`, with **at most one per (notification, channel)**. A dispatcher claims due rows with `FOR UPDATE SKIP LOCKED`, so two dispatchers never send the same one.

| Status | Meaning |
|---|---|
| `PENDING` → `SENDING` | queued / being sent |
| `SENT` | handed to SMTP or the SMS provider. **Final: never sent again.** |
| `DELIVERED` / `UNDELIVERED` | the SMS provider's signed delivery report |
| `FAILED` | temporary failure; retried after 1, 5, 30, 120, 360 minutes |
| `GAVE_UP` | `NOTIFY_MAX_ATTEMPTS` reached, or interrupted mid-send (outcome unknown, so not retried to avoid a duplicate) |
| `SKIPPED` | can't be sent and won't be retried: channel not configured, opted out, contact not verified, account deactivated |

**Re-checked at send time:** preferences and consent are checked again when a delivery is sent, so an opt-out also stops messages already queued. Without SMTP, e-mails are SKIPPED, never faked as sent.

**Retries:** a background loop retries due deliveries every `NOTIFY_DISPATCH_INTERVAL_SECONDS`. An administrator can also run them at once (`POST /admin/notifications/dispatch`) and see every status (`GET /admin/notifications/deliveries`).

**SMS** is off unless a provider is configured:
- **Provider API:** SchemeSetu POSTs `{to, message, sender, idempotency_key, status_callback}` to `SMS_HTTP_URL` with a Bearer token. The provider answers `{"message_id"}`.
- **Delivery reports** come to `POST /notifications/sms-status`, signed with HMAC-SHA256(`SMS_STATUS_SECRET`, body) in `X-Signature`. Unsigned or wrongly signed reports get 403.
- **`SMS_PROVIDER=log`** only writes a masked line to the log. It is for development and is refused in production.
- **Phone verification:**
  - **Code:** 6 digits, valid 10 minutes, locked after 5 wrong tries; only its hash is stored.
  - **One account per number:** a number verified on another account can't be used.
  - **Removing the number** also turns SMS off.

## Settings (`backend/.env`)

| Setting | Default | Purpose |
|---|---|---|
| `NOTIFY_MAX_ATTEMPTS` | 5 | delivery attempts before `GAVE_UP` |
| `NOTIFY_DISPATCH_INTERVAL_SECONDS` | 60 | background retry interval; `0` = only on publish or admin "dispatch" |
| `SMTP_HOST`, `SMTP_PORT`, `SMTP_USERNAME`, `SMTP_PASSWORD`, `SMTP_FROM`, `SMTP_STARTTLS` | unset | e-mail channel (unset = e-mail notifications unavailable) |
| `SMS_PROVIDER` | unset | `http` (real provider) or `log` (development only); unset = SMS unavailable |
| `SMS_HTTP_URL`, `SMS_HTTP_TOKEN` | unset | provider API endpoint and token |
| `SMS_STATUS_SECRET` | unset | HMAC key for delivery-status callbacks |
| `SMS_SENDER_ID` | `SCHSTU` | sender name |
| `SMS_CONSENT_VERSION` | `1` | increase when the consent text changes |
| `API_BASE_URL` | `http://localhost:8000` | public backend URL, used for the SMS status callback |
| `FRONTEND_BASE_URL` | `http://localhost:3000` | used in unsubscribe links |
| `SESSION_SECRET` | random per start | **Set it.** Unsubscribe links and phone-code hashes are signed with it; without it they stop working after a restart. |

## API

| Method | Path | Permission |
|---|---|---|
| GET | `/admin/scheme-changes/sources` | `scheme_changes:review` |
| POST | `/admin/scheme-changes/detect` `{source_name}` | `scheme_changes:review` |
| GET | `/admin/scheme-changes/batches`, `/admin/scheme-changes?batch_id=&status=` | `scheme_changes:review` |
| POST | `/admin/scheme-changes/{id}/review` `{decision, note, confirm_consequential}` | `scheme_changes:review` |
| POST | `/admin/scheme-changes/batches/{id}/discard` | `scheme_changes:review` |
| POST | `/admin/ops/jobs` `{kind: "PUBLISH_CHANGES", batch_id, dry_run, reason, confirm: "PUBLISH_CHANGES"}` | `ops:jobs:run` + `scheme_changes:review` |
| GET | `/admin/notifications/deliveries?status=` | `notifications:admin` |
| POST | `/admin/notifications/dispatch` | `notifications:admin` |
| GET | `/farmers/me/notifications?unread_only=&limit=&offset=` | `notifications:own` |
| POST | `/farmers/me/notifications/{id}/read`, `/farmers/me/notifications/read-all` | `notifications:own` |
| GET / PUT | `/farmers/me/notification-preferences` | `notifications:own` |
| GET / PUT / DELETE | `/farmers/me/subscriptions[/{scheme_id}]` | `notifications:own` |
| POST / DELETE | `/farmers/me/phone`, POST `/farmers/me/phone/verify` | `notifications:own` |
| POST | `/notifications/unsubscribe` `{token}` | public (signed token, rate-limited) |
| POST | `/notifications/sms-status` | public (HMAC signature) |

All `/farmers/me/...` routes act on the signed-in account only. Writes need `X-CSRF-Token`.

## Database (migration `0008`)

New tables:
- `scheme_change_batches`, `scheme_changes`
- `scheme_subscriptions`
- `notification_preferences`
- `notifications`
- `notification_deliveries`

Changes to existing tables:
- `farmers.phone_verified_at`
- `auth_tokens`: purpose `verify_phone`, plus `attempts` and `target`
- `admin_jobs`: kind `PUBLISH_CHANGES`, plus `params`

## Recovery

| Problem | What to do |
|---|---|
| A wrong change was published | Put the corrected file in `data/incoming/`, detect, approve the correction and publish again. The previous files are also in `data/backups/corpus-<time>/`. |
| Publish failed | Nothing was changed or sent. Read the job error on `/admin`, fix it, and publish again. |
| Many deliveries `FAILED` | Fix SMTP or the provider, then run **dispatch** (or wait for the background retry). `SENT` messages are never re-sent. |
| Deliveries stuck in `SENDING` | After 15 minutes they become `GAVE_UP` (the outcome is unknown, so they aren't re-sent). |
| Unsubscribe links stopped working | `SESSION_SECRET` changed or isn't set. Set it once and keep it. |
| Test publish left data behind (local stack) | `docker compose up -d --force-recreate backend` and then `docker compose run --rm init` restore the original corpus files and database. |

## Tests

- `backend/app/tests/test_scheme_updates.py` (46 tests) covers:
  - **detection:** each category; cosmetic re-scrapes and provenance-only changes report nothing; no duplicates on re-detection; broken records and suspicious scrapes;
  - **verification:** confirmation and note required; nothing published or notified while pending or after rejection; a stale candidate is refused; dry run; failed import rolls back and notifies nobody;
  - **notifications:** savers and followers notified once; preferences; consequential-only; inbox ownership;
  - **delivery:** retries with backoff then sent once; give up after the maximum; permanent failure skipped; e-mail not configured is skipped, not faked; opt-out after queueing; concurrent dispatchers;
  - **SMS:** provider, production guard, verified phone and consent, code lockout, number taken elsewhere, delivery-status tracking, opt-out, removing the phone;
  - **unsubscribe:** the link works and tampered links are refused.
- `backend/app/tests/test_scheme_updates_pg.py` (8 tests, opt-in `TEST_DATABASE_URL`) runs on PostgreSQL: fingerprint dedupe and the review state machine, the audience query, one notification and one delivery per channel, concurrent claims, stuck sends, phone-code locks, the SMS consent constraint, and a real publish into the database.
- `scripts/ui_updates_test.py` (12 checks, real browser against `docker compose up`). A farmer saves PM-KISAN; an admin detects a changed rule, can't approve without confirming, approves and publishes; the farmer sees exactly one "Important" notification. **Afterwards restore the corpus** with `docker compose up -d --force-recreate backend` and `docker compose run --rm init`.
