# Saved Schemes and Application Checklists

A signed-in farmer can save a scheme and keep track of applying for it. Saved schemes are on the
dashboard under **Saved Schemes & Applications**. To save one, press **Save** on a row of the eligibility
list, or on a scheme card in the AI chat.

## Progress is user-reported

SchemeSetu is **not connected to any government application-tracking system**. Every tick, note and
reference is what the farmer recorded. The API marks every saved scheme with
`progress_source: "USER_REPORTED"`, `official_tracking: false` and a `progress_notice`. The UI shows
"Your own record — not confirmed by any government department" wherever progress appears.

## The checklist

It is built from the scheme's own data in PostgreSQL when the scheme is saved:

| Section | Items |
|---|---|
| Documents | One per required document (`scheme_documents`), marked "Required" or "Needed in some cases". With no list in the database, the item is "Find out which documents are needed". |
| Preparation | "Read the official eligibility conditions", "Keep the originals and photocopies of your documents together" |
| How to apply | The official application steps (`application_steps`), with mode / portal / office. With none, the item is "Find out how to apply". |
| Submission | "Submit your application", with the application URL if the scheme has one |
| Acknowledgement | "Get an acknowledgement or application number" |
| Your own milestones | Added by the farmer, e.g. "Field verification visit done" (at most 20 per scheme) |

The farmer can:
- mark any item done or not done;
- add, change or remove a note on each item (≤ 500 characters);
- write notes for the scheme (≤ 1000 characters);
- record an **application reference** — only if they choose to (≤ 64 characters: letters, numbers, spaces and `/ . _ -`). It is never required, and SchemeSetu does not check it.

The **stage** comes only from the farmer's own ticks: Not started → Preparing → Submitted → Acknowledgement received.
Items that came from the scheme can only be unticked, not deleted. The farmer's own milestones can be deleted.

## Scheme version

Each saved scheme records the **scheme version**: a SHA-256 hash of the scheme's name, `data_version`,
official and application URLs, documents and application steps. The corpus import deletes and re-inserts
documents and steps with new database ids, so the version (and the checklist item keys) comes from the
content, not from ids. A re-import with the same content changes nothing.

`saved_scheme_version` is the version at the time of saving; `scheme_version` is the version the checklist is synced to.

When the scheme data changes, the checklist is brought up to date the next time it is read:
- Items that are still listed **keep their ticks and notes**. Their wording and order are refreshed.
- New items are added and marked "New".
- Items the scheme no longer lists are **kept** under "No longer listed by the scheme" and are not counted in the progress.
- A notice shows what was added and removed until the farmer presses "OK, got it" (`acknowledge_scheme_update`).

A scheme that is no longer in the database keeps its saved record (`scheme_available: false`).

## Duplicates

One saved row per farmer and scheme (`UNIQUE (farmer_id, scheme_id)`), and one checklist item per key
(`UNIQUE (saved_scheme_id, item_key)`). Saving a scheme that is already saved returns **200** with
`created: false` and changes nothing: notes, ticks and the date saved are kept. Four simultaneous saves
still give one row and one checklist (tested on PostgreSQL).

## Whose data

- No farmer id is accepted anywhere: the account always comes from the session.
- Every query is filtered by the account's id. Another farmer's scheme or item gives **404**, the same as a missing one.
- In the database, a checklist item's `(saved_scheme_id, farmer_id)` must match its saved scheme (composite foreign key). So an item can never belong to a different farmer than its saved scheme.
- Unsaving deletes the checklist. Deleting the account deletes both (`ON DELETE CASCADE`).

## API (signed in; PATCH / POST / DELETE need `X-CSRF-Token`)

| Method | Path | Notes |
|---|---|---|
| GET | `/farmers/me/saved-schemes` | Newest first, with progress, stage and any update notice |
| POST | `/farmers/me/saved-schemes` | `{scheme_id, eligibility_status?, notes?}`. Returns 201 with the checklist, or 200 `created: false`. Gives 404 for a scheme not in the database, 409 for an inactive one, 422 for unknown fields. The name always comes from the database. |
| GET | `/farmers/me/saved-schemes/{scheme_id}` | Detail with the checklist (synced first) |
| PATCH | `/farmers/me/saved-schemes/{scheme_id}` | `{notes?, application_reference?, acknowledge_scheme_update?: true}`. A field left out is unchanged; `null` clears it. |
| DELETE | `/farmers/me/saved-schemes/{scheme_id}` | 204 (checklist deleted too); 404 if not saved |
| PATCH | `/farmers/me/saved-schemes/{scheme_id}/checklist/{item_id}` | `{completed?: true\|false, note?}`. Repeating it is harmless. |
| POST | `/farmers/me/saved-schemes/{scheme_id}/checklist` | `{label, note?, completed?}`: your own milestone (201); 409 above 20 |
| DELETE | `/farmers/me/saved-schemes/{scheme_id}/checklist/{item_id}` | Your own milestones only (409 for scheme items) |

If the database is down, these routes return 503 with a generic message and no internal details.

## Database (migration `0005`)

- `saved_schemes` gains: `scheme_version`, `saved_scheme_version`, `scheme_data_version`,
  `previous_scheme_version`, `scheme_changed_at`, `scheme_update_seen`, `application_reference`
  (+ `_updated_at`), `updated_at`, a 1000-character limit on `notes` (any longer note is cut to 1000),
  and `UNIQUE (id, farmer_id)`.
- `saved_scheme_checklist_items` is new. Its check constraints:
  - category is one of the six above;
  - `USER` items are always milestones;
  - a note is at most 500 characters;
  - `completed_at` is set only when the item is completed.
- Schemes saved before `0005` get their checklist the first time they are read. They don't show an update notice.
- `0005` is reversible (tested: upgrade → downgrade to `0004` → upgrade).

## Tests

- `backend/app/tests/test_saved_schemes.py` (35 tests) uses the HTTP API with real sessions for two farmers. It covers:
  - save / unsave, duplicate saves, unknown and inactive schemes, validation;
  - ticking and unticking, notes, the reference, milestones and their limit;
  - stage; scheme updates and re-imports; a scheme removed from the database; a database outage (503);
  - cross-user access, missing CSRF, and a stolen cookie.
- `backend/app/tests/test_saved_schemes_pg.py` (10 tests, opt-in `TEST_DATABASE_URL`) runs the real SQL on PostgreSQL. It covers:
  - the migration and its reversal; concurrent saves; persistence across connections;
  - a scheme update after a re-import with new ids; ownership in the queries and by the foreign key;
  - cascades, constraints, and a scheme saved before the migration.
- `scripts/ui_auth_test.py` covers it in a real browser: Save on the dashboard, no duplicate, the user-reported label, a tick, the reference and a milestone surviving a reload, and Remove.
