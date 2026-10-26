# SchemeSetu — Demo Script (about 10 minutes)

One farmer, one story: **a ragi farmer from Karnataka with 2 acres** (scenarios D12, D01, D07, D08, D10, D11 in
`evaluation/datasets/demo_scenarios.json`, which are verified by `backend/app/tests/test_golden_demo.py`).

## Before the demo (5 minutes)
Choose one mode and **say which one you are using**.

- **Live mode** (API keys in `backend/.env`): `docker compose up --build`, then open http://localhost:3000.
  Language understanding, speech and translation are real. Wording may vary from below.
- **Demo mode** (no keys, fully deterministic):
  ```bash
  docker compose up -d postgres init        # or any PostgreSQL with the corpus imported
  set DATABASE_URL=postgresql://schemesetu:schemesetu@localhost:5432/schemesetu   # PowerShell: $env:DATABASE_URL=...
  python scripts/demo_server.py             # note the reviewer key it prints
  cd frontend && npm run build && npm start
  ```
  The yellow banner states what is simulated: language understanding, speech and translation for the scripted
  lines. Scheme data, retrieval, eligibility, explanations and review are real. Type the lines **exactly** as
  written.
- Open a second tab with http://localhost:8000/docs (review step). Check that the header shows "System ready".

## Narrative

| # | Time | Do / say | Show (screenshot) |
|---|---|---|---|
| 1 | 0:00 | **Problem.** Farmers miss schemes because information is scattered, written in English, and eligibility is hard to read. SchemeSetu finds schemes, checks published criteria and explains why. | — |
| 2 | 0:45 | Open SchemeSetu. Point out language, "New chat" and the status pill. | `01-landing.png` |
| 3 | 1:15 | **Conversational onboarding.** Type `Hello, I need help finding schemes` → it asks for the state. Type `I live in Karnataka` → it asks for land. | `02-onboarding-questions.png` |
| 4 | 2:00 | **Profile extraction + missing-information question.** Type `I have 2 acres`, then `I grow ragi and I am a farmer`. The profile panel fills in (state, land, crop, occupation). | `03-profile-and-results.png` |
| 5 | 2:45 | **Scheme search (hybrid).** Explain: PostgreSQL (canonical), Knowledge Graph (relationships) and web run in parallel and are merged into one candidate per scheme. | right panel |
| 6 | 3:15 | **Knowledge Graph contribution.** On a card, rank reasons include "Knowledge graph match". The Karnataka state scheme is found because the graph links schemes to states; schemes restricted to other states and crops are excluded. | scheme cards |
| 7 | 3:45 | **Eligibility reasoning.** PM-KISAN is ELIGIBLE: occupation = farmer, land holding = yes (2 acres > 0). PM-KMY needs your age (NEEDS_MORE_INFORMATION). Decisions are deterministic; the LLM never decides. | `04-…png` |
| 8 | 4:45 | **Explainability.** Expand PM-KISAN: "Why it matches" lists the evidence. Unknown information is shown as missing, never as failed. | `04-eligibility-documents-steps-source.png` |
| 9 | 5:15 | **Documents** (Aadhaar Card, Bank Account Details, Land Records) and **application steps** from the canonical database, plus "View official source" (pmkisan.gov.in). | same |
| 10 | 5:45 | **Follow-up.** Type `What documents do I need for the first one?` → the answer is about scheme #1, resolved deterministically from the previous answer. | `05-follow-up-documents.png` |
| 11 | 6:30 | **Language switching.** Select हिन्दी and type `पहली योजना के लिए कौन से दस्तावेज़ चाहिए?`. The profile is kept and the pipeline still runs in English internally. (In demo mode the reply stays in English because translation of new replies is simulated only for the scripted inputs — say so.) | `06-language-switch-hindi.png` |
| 12 | 7:30 | **Voice.** "New chat", select ಕನ್ನಡ, press the microphone, speak, press again. The transcript bubble appears and the same pipeline returns the same schemes. (Demo mode: ASR is simulated and returns the scripted Kannada sentence.) | `07-voice-kannada.png` |
| 13 | 8:30 | **Human review.** The reply ends: "Some results could not be verified automatically and have been flagged for review…" (schemes without structured rules). In `/docs`, authorise with the key, `GET /review-cases?status=PENDING`, then `POST …/resolve` with `REQUEST_INFORMATION` and then `APPROVE`. Show the audit log via `GET /review-cases/{id}`. | `10-api-docs-review-endpoints.png` |
| 14 | 9:30 | **Summary.** Agentic workflow + Knowledge Graph + deterministic eligibility + evidence-based explanations + 11 languages + voice + human review. Evaluation: 47 measured metrics pass (offline); live latency, user study and expert review are still open (be explicit). | `docs/phase7-final-scorecard.md` |

## Backup plan
- Backend down: show the screenshots in `docs/assets/screenshots/` (captured from the running app).
- Voice blocked by the browser: skip to step 13 and mention the voice test results (`docs/phase7-final-evaluation.md` §10).

## Do not claim
Guaranteed approval; 22 languages; live latency within 10–15 s (not measured); user-study or expert results (not conducted).
