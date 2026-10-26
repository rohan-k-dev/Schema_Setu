# Farmer Dashboard

`/dashboard` (signed in) shows, from the farmer's **saved profile** (docs/PROFILE.md):

- **Eligibility for every active scheme.** Tabs: Eligible / Needs more information / Not eligible / Can't verify. Results are paged, with a "Why this result?" list per scheme.
- **Details to check:** missing and conflicting profile details. Each can be fixed in place; eligibility is then recalculated automatically.
- **Saved schemes & applications:** a Save button on each eligibility row. Each saved scheme has a user-reported application checklist ([SAVED_SCHEMES.md](SAVED_SCHEMES.md)), and is flagged when its status or the scheme's information has changed since it was saved.
- **Recent searches:** delete one, or clear all.

## Who decides eligibility

Only the deterministic eligibility engine (`app/eligibility`) decides, using the official rules stored in PostgreSQL. The LLM is never asked.
- A detail that isn't saved is **unknown**: it gives "Needs more information", never "Not eligible".
- A scheme with no checkable rules, or with rules that contradict each other, is "Can't verify" and comes with a note.

## Stale results

Every result carries a **basis**:
- the profile version;
- a SHA-256 fingerprint of the active scheme records and their rules;
- the engine version.

The page re-reads the current basis every minute and whenever the tab regains focus. If anything differs (the profile was changed in chat or on another device, scheme data was updated, or the engine changed), a notice says what changed, with a **Recalculate now** button. A detail fixed on the dashboard is saved with the profile version (a newer edit elsewhere gives 409 and is never overwritten), then the result is recalculated.

## Missing and conflicting details

- **Missing:** fields that the engine marked unknown for "Needs more information" schemes, with the schemes they affect. `has_land` is shown as Land size.
- **Conflicting:** saved details that can't all be true. Today's only check: category EWS with income above ₹10 lakh (EWS requires family income below ₹8 lakh).

## Recent searches: retention policy

| Rule | Value |
|---|---|
| Recorded when | a signed-in farmer who agreed to keep their details ("consent") makes a chat or voice request that searches schemes (`schemes_found`, `partial_results`, `no_results`). Follow-up questions and errors aren't recorded. Anonymous use is never recorded. |
| Stored | the request text as typed or transcribed (trimmed to 200 characters), number of results, language, time |
| Kept | the newest **50** per farmer, for at most **90 days**. Older entries are deleted (not hidden) on every save and every read. |
| Deleted | per entry or all at once by the farmer, and automatically with the account (`ON DELETE CASCADE`) |

## API (signed in; DELETE needs `X-CSRF-Token`)

| Method | Path | Notes |
|---|---|---|
| GET | `/farmers/me/eligibility?status=&page=1&page_size=10` | `counts` (all statuses), one page of ranked `items`, `missing_details`, `conflicts`, `saved_status_changes`, `basis`, `computed_at`. `page_size` ≤ 50; invalid values give 422; scheme data down gives 503. |
| GET | `/farmers/me/eligibility/basis` | Current basis, for stale checks. |
| GET | `/farmers/me/search-history?limit=10&offset=0` | Newest first; total in the `X-Total-Count` header. |
| DELETE | `/farmers/me/search-history/{id}` | 204. Another farmer's entry gives **404**, the same as a missing one. |
| DELETE | `/farmers/me/search-history` | `{"deleted": n}` |
| GET | `/farmers/me/dashboard` | Unchanged: account, profile and saved schemes (`recent_searches` now follows the retention policy). |
| … | `/farmers/me/saved-schemes/*` | Saving, unsaving and checklists — see [SAVED_SCHEMES.md](SAVED_SCHEMES.md). |

**Ownership:** no farmer id is accepted anywhere. Every query is filtered by the signed-in account's id.

## Tests

- `backend/app/tests/test_dashboard.py` (38 tests) runs through the HTTP API with real sessions for two farmers and the real engine. It covers:
  - statuses and ranking; no-profile behaviour; missing and conflicting details;
  - recalculation after profile changes and after rule or scheme changes (basis and fingerprint);
  - pagination and validation; 503 when scheme data is down;
  - ownership and 401/403 checks;
  - history consent, the 50-entry / 90-day limits, deleting one entry, clearing all, cross-user deletion (404), CSRF, and a chat turn being recorded.
- `backend/app/tests/test_search_history_pg.py` (opt-in `TEST_DATABASE_URL`) runs the real SQL: paging, the 50 limit, 90-day deletion, owner-scoped delete, clear, and account cascade.
- `scripts/ui_auth_test.py` covers the dashboard in a real browser: eligibility tabs, fixing a missing detail, the stale notice, deleting a search, and clearing history.
