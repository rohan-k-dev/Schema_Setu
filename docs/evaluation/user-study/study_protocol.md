# User Study — Protocol

> **Status: PLANNED / NOT CONDUCTED.** No participant has taken part. Nothing in this folder is a result.

- **Objective:** measure whether farmers and comparable users can find relevant schemes, understand *why* a
  scheme matches, find documents and steps, use voice and switch language with SchemeSetu (Review-II:
  user-friendly interface, multilingual and voice interaction, explainability).
- **Design:** moderated task study with think-aloud; 30–40 minutes per participant.
- **Participants (study-design choice):** 8–12 adults; at least 3 with limited digital literacy and at least 3
  familiar with agriculture or government schemes; at least English, Kannada and Hindi speakers.
- **Setting:** phone or laptop with Chrome, SchemeSetu with live API keys. If demo mode has to be used, speech and
  translation are simulated, and this must be reported with the results.
- **Consent:** read aloud. The study evaluates the system, not the person. Participants may stop at any time.
  No names, phone numbers, Aadhaar numbers or addresses are recorded.
- **Scenario cards:** fictional farmer profiles are printed, so no real personal data is entered.
- **Procedure:** consent → 2-minute introduction → tasks T1–T9 (`tasks.md`) → comprehension questions and
  questionnaire (`questionnaire.md`) → debrief.
- **Data:** anonymous IDs (P01…) in `data/evaluation/user_study/records.json` (format:
  `records.template.json`). Analysis: `python scripts/run_evaluation.py` (user_study runner) → `analysis.md`.
