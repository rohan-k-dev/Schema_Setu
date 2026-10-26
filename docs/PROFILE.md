# Farmer Profile

A signed-in farmer can save their details once instead of repeating them in every
chat. The profile is stored in PostgreSQL (`farmer_profiles`, one row per account)
and fills in the chat's profile before eligibility is checked.

## What is stored, and why

The profile collects only what the eligibility rules or scheme search use. Every field is optional.

| Field | Values | Used by |
|---|---|---|
| state | Indian state / UT (abbreviations like "KA" accepted) | state schemes, search |
| district | text | search |
| land_size + land_unit | number + `acre` / `hectare` / `guntha` / `cent` | converted to `land_size_acres`: PM-KISAN (has land), PM-KMY (≤ 5 acres), PKVY (≥ 0.5 acre) |
| primary_crop | crop (synonyms normalised, e.g. finger millet → ragi) | NMOOP, crop schemes |
| occupation | e.g. farmer, agricultural labourer | 8 schemes require "farmer" |
| age | 1–119 | PM-KMY, PMJJBY, PMSBY |
| gender | male / female / other | MKSP |
| category | General / OBC / SC / ST / EWS | DEDS |
| residence | rural / urban | MGNREGA |
| income_range | below ₹1 lakh … above ₹10 lakh | no rule today; kept as a range, never as an exact amount |
| other_crops, farming_type | optional crop details | display only |

**Not collected:**
- Aadhaar number: never collected.
- Aadhaar status: no eligibility rule needs it. Aadhaar appears only as a required *document* on scheme cards.
- Exact income: stored only as a range.

Migration `0004` converted existing exact incomes to ranges and cleared the stored values and Aadhaar statuses.
Bigha isn't offered as a land unit, because its size differs from state to state.

## Unknown is not "no"

- A field that isn't given is stored as `NULL` and returned as `null`, meaning unknown. The eligibility engine treats it as UNKNOWN, giving "needs more information", never "not eligible".
- No yes/no field defaults to "no". Zero is a real value (0 acres = landless), not unknown.

## API (signed in; see docs/AUTH.md)

| Method | Path | Notes |
|---|---|---|
| GET | `/farmers/me/profile` | 200 profile, 404 if none saved yet |
| PUT | `/farmers/me/profile` | Partial update, needs `X-CSRF-Token` |
| DELETE | `/farmers/me/profile` | Withdraw consent: deletes the profile and the search history recorded under it ([PRIVACY.md](PRIVACY.md)) |

PUT rules:
- **Left out** = unchanged; **`null`** = clear to unknown (correcting "I'm not sure any more").
- **`consent_given: true`** is required on the first save (403 otherwise).
- **Validation** (422): unknown state, negative land, land without a unit (or a unit without a value), age outside 1–119, unknown gender / category / range / residence, blank or `<script>`-like text, more than 10 extra crops.
- **Unexpected fields are rejected (422)**, including `aadhaar_number`, `has_aadhaar`, `annual_income` and `farmer_id`.
- **Conflicting edits:** send `expected_version` (from the last GET). If the profile changed meanwhile (in chat or on another device), the save gets **409** and nothing is overwritten; reload, check and save again. Every save increases `version`.

## Whose profile

There is no farmer id in any URL or request body. The account always comes from the
signed-in session. Every query is filtered by that account's id, so one farmer can't read or
change another's profile, even by sending another farmer's id (422) or a stolen
cookie from another browser (401).

## Chat and the saved profile

- **With consent ("keep my details"):** the saved profile is loaded at the start of every chat turn and wins over what the chat remembered, so profile-page corrections apply immediately. After the turn, only the fields the farmer changed in that turn are written back. A stale chat value can't overwrite a newer correction.
- **Without consent:** saved values only fill gaps, and nothing is written.
- An exact income said in chat is saved only as its range. Aadhaar status is never saved.

## Tests

- `backend/app/tests/test_profile_module.py`: API with real sessions for two farmers. Covers save/load, unit conversion, unknown values, partial updates and corrections, validation, version conflicts, the chat merge policy, cross-user attempts and signed-out / CSRF-less requests.
- `backend/app/tests/test_profile_repository_pg.py` (opt-in `TEST_DATABASE_URL`): migration 0004 data conversion, clearing, version conflicts (also with 4 simultaneous saves), per-account isolation, and database constraints.
- `scripts/ui_auth_test.py`: profile save with a land unit and a stale-edit conflict, in a real browser.
