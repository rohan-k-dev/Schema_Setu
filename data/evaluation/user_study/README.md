# User study data (anonymised)

Protocol: `docs/phase7-user-study-report.md`. Analysis: `evaluation/runners/user_study_runner.py`
(runs as part of `python scripts/run_evaluation.py`).

Record real sessions in `records.json` (copy `records.template.json`). **Never** store names,
phone numbers, Aadhaar numbers, e-mail or addresses — the runner flags those keys as privacy violations.

- `participants[]`: `participant_id` (P01…), `language`, `group` (student / non-technical /
  limited digital literacy / agriculture-familiar), `digital_literacy` (low/medium/high)
- `task_results[]`: `participant_id`, `task_id` (T1–T9), `completed` (bool), `completion_time_s`,
  `comprehension_score` (0–1), `trust_rating` (1–5), `usability_rating` (1–5), `voice_rating` (1–5 or null),
  `comments`, `themes` (subset of: ease_of_use, trust, language, voice, explanation, missing_information, difficulties)

Until real records exist every user-study metric is reported as NOT_MEASURED.
