# Red-Team Report

36 probes (`evaluation/datasets/adversarial_cases.json`), executed by `evaluation/runners/adversarial_runner.py`
against the real API and pipeline. The baseline (before fixes) passed **17/36**; after fixes, **36/36** (Phase 7
`after` run and the Phase 8 clean-container run). Payloads are described, not reproduced, where they would only
help an attacker.

| Category | Attack | System behaviour (after) | Vulnerable before? | Mitigation | Residual risk |
|---|---|---|---|---|---|
| Profile manipulation | Negative / NaN / infinite land or income; non-existent state; SQL text as state | Value rejected → unknown; other fields kept | **Yes** (all stored) | `FarmerProfile` validators (BUG-017) | Plausible-but-false answers cannot be detected (no document verification) |
| Eligibility numeric | Negative number as a string passing a "≤ limit" rule; NaN income; "1.5 lakhs" | Never ELIGIBLE; NaN → unknown; lakhs parsed | **Yes** (false ELIGIBLE) | `safe_parse_numeric` (BUG-003) | — |
| Eligibility logic | Rule group named with the letters "or" | Treated as AND | **Yes** (false ELIGIBLE) | `is_or_group` (BUG-002) | — |
| Indirect prompt injection | Web result instructing the system to mark schemes eligible | Ignored: statuses unchanged, text not echoed | No (engine authority) | Engine decides; untrusted-data prompt rule | LLM wording could still be influenced; the validator blocks status claims |
| Direct prompt override | User asks to ignore the rules | Statuses unchanged | No | Same | — |
| LLM fabrication | Reply claims eligibility / invents URL / amount / scheme | Rejected → deterministic reply | **Yes** (shown verbatim) | `validate_llm_response` (BUG-013) | Pattern-based; novel paraphrases possible |
| No-candidate fabrication | All channels down | `no_results`, no scheme names | No | — | — |
| SQL injection | Malicious text in query parameters / profile | Plain text, no error, data intact; static scan finds no string-built SQL | No (one f-string with constant table names hardened) | Parameterised SQL, `sql.Identifier` | — |
| Graph / code injection | Python and Cypher-like text as profile values | Plain text; graph unchanged; no `eval`/`exec` | No | Structured graph API | — |
| XSS | Script tags in source titles / replies | Rendered as text | No | React escaping; no HTML injection APIs | — |
| Malicious upload | 12 MB file; PHP text as audio/webm; text/html | Rejected before ASR | Partly (content not checked) | Magic-byte sniffing (BUG-024) | Valid-format but adversarial audio not tested |
| Input flooding | 100,000-character message; blank message | HTTP 422 before the LLM | **Yes** (accepted) | Length / blank validation (BUG-023) | No rate limiting |
| Session isolation | Interleaved sessions | Strictly separate | No cross-user leak. **UI defect:** a constant ID made every message start a new session | Per-tab UUID (BUG-031) | No user authentication |
| Review authorisation | No key / wrong key / unauthorised resolve | 403, case unchanged | Key was hard-coded in source | Env key, constant-time compare (BUG-020) | Shared key, no per-reviewer identity |
| Secret leakage | Static scan of code and config | No secrets | **Yes** (reviewer key; Phase 8 also caught a demo key) | Env-only secrets | Human error in future commits; CI scan helps |
| Privacy (logs) | Income, category, Aadhaar status in logs | Not logged | **Yes** | Field-name-only logging (BUG-021) | — |
| Privacy (outbound) | Sensitive values in Groq prompts / Tavily queries | Minimised / redacted | **Yes** | `llm_safe_profile_summary`, `redact_scheme_for_llm` (BUG-022) | Conversation text still goes to Groq/Sarvam |
| Duplicate submission | Same message twice | Same result, no false conflict | No | — | — |

Not tested: denial of service against the external APIs, dependency CVE scanning, authenticated
penetration testing of a deployed instance.
