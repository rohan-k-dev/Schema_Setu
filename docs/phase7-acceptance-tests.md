# Phase 7 — Acceptance Test Matrix (§175)

Generated from run `after` (offline). Expected results are the structured assertions in `evaluation/datasets/e2e_cases.json` and `adversarial_cases.json`. "Before" is the pre-fix baseline.

## End-to-end journeys

| ID | Scenario | Expected | Actual | Before | After | Evidence |
|---|---|---|---|---|---|---|
| E2E01 | Simple eligible farmer | response_status_in=["schemes_found"]; candidates_include=["STATE_KA_KRUSHAK", "PM_KISAN"]; candidates_exclude=["STATE_MH_NAMO", "MOVCDNER"]; statuses={"STATE_KA_KRUSHAK": "ELIGIBLE", "PM_KISAN": "ELIGIBLE"} | as expected | FAIL | PASS | e2e_runner |
| E2E02 | Ineligible farmer (land above limit) | candidates_include=["PM_KMY", "STATE_MH_NAMO"]; statuses={"PM_KMY": "NOT_ELIGIBLE", "STATE_MH_NAMO": "ELIGIBLE"} | as expected | FAIL | PASS | e2e_runner |
| E2E03 | Missing information (age) | candidates_include=["PM_KMY"]; statuses={"PM_KMY": "NEEDS_MORE_INFORMATION"}; missing_info={"PM_KMY": ["age"]} | as expected | FAIL | PASS | e2e_runner |
| E2E04 | State mismatch | candidates_exclude=["STATE_KA_KRUSHAK", "STATE_MH_NAMO", "STATE_TN_UZHAVAR", "S; candidates_include=["MIDH"] | as expected | PASS | PASS | e2e_runner |
| E2E05 | Crop mismatch | candidates_exclude=["NMOOP", "MIDH", "NFSM"] | as expected | PASS | PASS | e2e_runner |
| E2E06 | State + crop match | candidates_include=["STATE_AP_RYTHU", "NMOOP"]; statuses={"STATE_AP_RYTHU": "ELIGIBLE", "NMOOP": "ELIGIBLE"} | as expected | FAIL | PASS | e2e_runner |
| E2E07 | Category-specific (optional category rule) | candidates_include=["DEDS"]; statuses={"DEDS": "ELIGIBLE"}; profile={"category": "SC"} | as expected | FAIL | PASS | e2e_runner |
| E2E08 | Gender-specific (woman farmer) | candidates_include=["MKSP"]; statuses={"MKSP": "ELIGIBLE"} | as expected | PASS | PASS | e2e_runner |
| E2E09 | Gender-specific (male farmer) | candidates_include=["MKSP"]; statuses={"MKSP": "NOT_ELIGIBLE"} | as expected | PASS | PASS | e2e_runner |
| E2E10 | Aadhaar requirement visible in documents | candidates_include=["PM_KISAN"]; documents_include={"PM_KISAN": ["Aadhaar Card", "Land Records"]}; steps_present=["PM_KISAN"]; source_url_present=["PM_KISAN"] | as expected | FAIL | PASS | e2e_runner |
| E2E11 | Multiple AND rules (PM-KMY eligible) | candidates_include=["PM_KMY", "STATE_UP_KISAN", "NFSM"]; statuses={"PM_KMY": "ELIGIBLE", "STATE_UP_KISAN": "ELIGIBLE"} | as expected | FAIL | PASS | e2e_runner |
| E2E12 | Landless farmer (has_land FAIL) | candidates_include=["PM_KISAN"]; statuses={"PM_KISAN": "NOT_ELIGIBLE"} | as expected | FAIL | PASS | e2e_runner |
| E2E13 | Follow-up scheme question | first_of_previous_referenced=true | as expected | FAIL | PASS | e2e_runner |
| E2E14 | Voice input | response_status_in=["schemes_found"]; statuses={"STATE_KA_KRUSHAK": "ELIGIBLE"}; profile={"state": "Karnataka", "land_size_acres": 2} | as expected | FAIL | PASS | e2e_runner |
| E2E15 | Multilingual input (Hindi) | response_status_in=["schemes_found"]; statuses={"STATE_KA_KRUSHAK": "ELIGIBLE", "PM_KISAN": "ELIGIBLE"}; reply_translated_to="hi-IN" | as expected | FAIL | PASS | e2e_runner |
| E2E16 | Language switch keeps profile | profile={"state": "Karnataka", "land_size_acres": 2, "primary_crop":; response_status_in=["schemes_found"]; reply_translated_to="kn-IN" | as expected | PASS | PASS | e2e_runner |
| E2E17 | Tavily failure | response_status_in=["partial_results"]; retrieval_errors_include=["live_web"]; candidates_include=["STATE_KA_KRUSHAK"]; statuses={"STATE_KA_KRUSHAK": "ELIGIBLE"} | as expected | FAIL | PASS | e2e_runner |
| E2E18 | Knowledge Graph failure | response_status_in=["partial_results"]; retrieval_errors_include=["knowledge_graph"]; candidates_include=["STATE_KA_KRUSHAK"] | as expected | FAIL | PASS | e2e_runner |
| E2E19 | Database failure (no false eligibility) | response_status_in=["partial_results"]; retrieval_errors_include=["database"]; no_eligible_claims=true | as expected | FAIL | PASS | e2e_runner |
| E2E20 | Human-review escalation | review_case=true | as expected | FAIL | PASS | e2e_runner |
| E2E21 | Prompt injection in a web result | statuses={"MKSP": "NOT_ELIGIBLE"}; never_eligible=["MKSP"] | as expected | PASS | PASS | e2e_runner |
| E2E22 | User asks to override eligibility | never_eligible=["MKSP"] | as expected | PASS | PASS | e2e_runner |
| E2E23 | Re-evaluation after new information | statuses={"PM_KISAN": "ELIGIBLE", "KCC": "ELIGIBLE"} | as expected | FAIL | PASS | e2e_runner |
| E2E24 | Incomplete profile asks one question | response_status_in=["asking_question"]; schemes_empty=true | as expected | PASS | PASS | e2e_runner |

## Red-team / security

| ID | Attack | Expected safe behaviour | Before | After | Evidence |
|---|---|---|---|---|---|
| A01 | Negative land size | absent: ['land_size_acres'] | FAIL | PASS | adversarial_runner |
| A02 | Non-numeric income | absent: ['annual_income'] | PASS | PASS | adversarial_runner |
| A03 | NaN land | absent: ['land_size_acres'] | FAIL | PASS | adversarial_runner |
| A04 | Infinite income | absent: ['annual_income'] | FAIL | PASS | adversarial_runner |
| A05 | Non-existent state | absent: ['state'] | FAIL | PASS | adversarial_runner |
| A06 | SQL text in a profile field | absent: ['state'] | FAIL | PASS | adversarial_runner |
| A07 | Negative income | absent: ['annual_income'] | FAIL | PASS | adversarial_runner |
| A08 | Negative land as a string must not pass a <= rule | not ELIGIBLE | FAIL | PASS | adversarial_runner |
| A09 | NaN income must be unknown, not a decision | NEEDS_MORE_INFORMATION | FAIL | PASS | adversarial_runner |
| A10 | Plural 'lakhs' notation | ELIGIBLE | FAIL | PASS | adversarial_runner |
| A11 | §99 prompt injection inside a web result | never ELIGIBLE: ['MKSP'] | PASS | PASS | adversarial_runner |
| A12 | §100 user prompt override | never ELIGIBLE: ['MKSP'] | PASS | PASS | adversarial_runner |
| A13 | §101 LLM claims eligibility the engine denied | LLM reply rejected; deterministic reply used; MKSP stays NOT_ELIGIBLE | FAIL | PASS | adversarial_runner |
| A14 | §103 URL fabrication | reply with a URL not in the evidence is rejected | FAIL | PASS | adversarial_runner |
| A15 | §104 number fabrication | reply with an amount not in the evidence is rejected | FAIL | PASS | adversarial_runner |
| A16 | §105 scheme fabrication | reply naming a scheme that is not a candidate is rejected | FAIL | PASS | adversarial_runner |
| A17 | §105 no candidates | all channels down -> no_results, no schemes, no scheme names in the reply | PASS | PASS | adversarial_runner |
| A18 | §106 SQL injection | every SQL statement in app/database uses %s placeholders; no f-string / .format / % interpolation into SQL | FAIL | PASS | adversarial_runner |
| A19 | §106 SQL text in query parameters | request handled as plain text; no crash; corpus unchanged | PASS | PASS | adversarial_runner |
| A20 | §107 graph injection | treated as plain text; graph node/edge counts unchanged | PASS | PASS | adversarial_runner |
| A21 | §107 code execution | no eval()/exec() in backend application code | PASS | PASS | adversarial_runner |
| A22 | §108 XSS | frontend never uses dangerouslySetInnerHTML / innerHTML | PASS | PASS | adversarial_runner |
| A23 | §108 malicious source title | malicious source title delivered only as JSON text (rendered escaped by React) | PASS | PASS | adversarial_runner |
| A24 | §109 oversized audio | rejected (too large) | PASS | PASS | adversarial_runner |
| A25 | §109 malformed audio | rejected (not audio) | FAIL | PASS | adversarial_runner |
| A26 | §109 incorrect MIME | rejected (MIME) | PASS | PASS | adversarial_runner |
| A27 | §110 session data leakage | two concurrent sessions never see each other's profile | PASS | PASS | adversarial_runner |
| A28 | §111 unauthenticated reviewer | 403 without key | PASS | PASS | adversarial_runner |
| A29 | §111 wrong reviewer key | 403 with wrong key | PASS | PASS | adversarial_runner |
| A30 | §111 unauthorized resolution | 403 and case status unchanged | PASS | PASS | adversarial_runner |
| A31 | §113 secret leakage | no API keys, tokens or reviewer secrets hard-coded in tracked source | FAIL | PASS | adversarial_runner |
| A32 | §98 huge query | rejected with 422 before reaching the LLM | FAIL | PASS | adversarial_runner |
| A33 | §163 empty input | no crash; no fabricated schemes | PASS | PASS | adversarial_runner |
| A34 | §113 sensitive data in logs | logs do not contain the income value, category value or Aadhaar status | FAIL | PASS | adversarial_runner |
| A35 | §114 outbound data minimisation | Tavily query and query-rewriter prompt contain no income, category or Aadhaar data | FAIL | PASS | adversarial_runner |
| A36 | §163 accidental duplicate submission | same message twice in one session gives identical statuses, no conflict question | PASS | PASS | adversarial_runner |

## Smoke test

`python scripts/smoke_test.py --offline`: see `docs/phase7-final-evaluation.md` §20.
