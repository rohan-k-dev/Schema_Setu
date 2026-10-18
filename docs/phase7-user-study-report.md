# Phase 7 — User Study: Protocol and Report

**Status: NOT CONDUCTED — 0 participants recorded.** The protocol, task set, data model and analysis
pipeline are implemented. No participant data has been collected, so every user-study metric is reported as
`NOT_MEASURED` in `data/evaluation/user_study_report.json` and the final scorecard. Nothing in this
document may be read as a result.

## 1. Objective
Measure whether farmers and comparable users can use SchemeSetu to find schemes, understand *why* a scheme
matches, find documents and steps, use voice, switch language and interpret an eligibility result correctly
(Review-II: user-friendly interface, multilingual & voice interaction, explainability).

## 2. Participants (project study-design choice, §80)
- Target: **8–12 participants** (capstone-sized, descriptive statistics only).
- Mix: students; non-technical adults; at least 3 users with limited digital literacy; at least 3 users
  familiar with agriculture or government schemes.
- Languages: at least English, Kannada and Hindi; one or more additional supported languages if feasible.
- Recorded per participant: anonymous ID (P01…), language, group, self-rated digital literacy. **No names,
  phone numbers, Aadhaar, e-mail or address** (§87). The analysis runner flags such keys as privacy violations.

## 3. Procedure
1. Consent read aloud; explain that the system is a prototype and that the study tests the system, not the participant.
2. Participant receives a **printed scenario card** with a fictional farmer profile, so no real personal data is entered.
3. Tasks T1–T9 are attempted in order on a phone (Chrome, 360 px width) with think-aloud.
   The moderator records completion (yes/no), time and observations. No help is given unless the participant
   is stuck for more than 2 minutes, in which case the task is marked not completed.
4. Post-task questions (comprehension) and a post-session questionnaire (1–5 Likert scales; neutral wording, §86).

| Task | Description | Success criterion |
|---|---|---|
| T1 | Provide the farmer profile (state, land, crop) | Profile panel shows all three |
| T2 | Find relevant schemes | Scheme list shown |
| T3 | Understand why one scheme matches | Participant states the matched criterion |
| T4 | Find required documents | Names at least one listed document |
| T5 | Find application steps | Reads the first step |
| T6 | Ask a follow-up ("documents for the first one?") | Answer is about the right scheme |
| T7 | Use voice for one turn | Transcript appears and the turn continues |
| T8 | Change language | Reply arrives in the new language and the profile is kept |
| T9 | Interpret an eligibility result | Correctly explains ELIGIBLE / NEEDS_MORE_INFORMATION |

## 4. Comprehension questions (§83–§85)
- "Why did this scheme match your profile?" Correct if the actual matched criterion is named.
- "Where did this information come from?" Correct if the official source / link is identified.
- "Does the system guarantee that you will receive this scheme?" Correct answer: **No**, it only checks
  published criteria.

Comprehension score per participant = correct answers / 3.

## 5. Questionnaire (1–5)
Ease of use · trust in the results · voice usability (if used) · language usability · clarity of the explanation.

## 6. Data model and analysis
Records are stored in `data/evaluation/user_study/records.json` (format in that folder's README; template
`records.template.json`). `evaluation/runners/user_study_runner.py` computes completion rate, average task
time, comprehension score, average trust / ease / voice ratings, per-task completion and qualitative themes
(ease_of_use, trust, language, voice, explanation, missing_information, difficulties). It reports a small-sample
caveat and makes no significance claims (§156).

## 7. Results
| Metric | Value |
|---|---|
| Participants | 0 |
| Task completion rate | NOT_MEASURED |
| Average task time | NOT_MEASURED |
| Comprehension score | NOT_MEASURED |
| Average trust / ease of use / voice / language | NOT_MEASURED |

## 8. Limitations
The study has not been run. Before final submission it must be run with real participants, the records
entered, and `python scripts/run_evaluation.py` re-run. The scorecard will then show measured values.
