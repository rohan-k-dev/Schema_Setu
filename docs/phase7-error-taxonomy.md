# Phase 7 — Error Taxonomy

Every bug in `docs/phase7-bug-register.md` and every remaining limitation is classified below (§158).

| Category | Definition | Phase 7 bugs | Remaining limitations |
|---|---|---|---|
| PROFILE | Wrong, missing or invalid profile data after extraction/merge | BUG-004, BUG-017 | LLM extraction accuracy not measured offline; `residence` not modelled |
| RETRIEVAL | Wrong, missing or duplicated candidates; failures not surfaced | BUG-006, BUG-008, BUG-009, BUG-010, BUG-011, BUG-028 | no fuzzy name search; no crop taxonomy (ragi ↛ millets) |
| DATA | Corpus or golden-dataset content errors | BUG-029 (label) | 22/40 schemes have no structured rules → UNVERIFIABLE |
| ELIGIBILITY | Wrong rule or scheme decision | BUG-002, BUG-003, BUG-029 (engine), BUG-030 | — |
| XAI | Explanations or replies not grounded in evidence | BUG-013, BUG-014, BUG-015 | validator is pattern-based (see limitations) |
| LANGUAGE | Translation / multilingual handling | — (none found offline) | live Sarvam quality not measured |
| VOICE | ASR/TTS flow and audio handling | BUG-024 | WER not measured |
| UI | Frontend behaviour and contract | BUG-012, BUG-031, BUG-032 | no reviewer UI (API only) |
| SECURITY | Injection, secrets, auth, input limits | BUG-013, BUG-020, BUG-023, BUG-026 | shared-secret reviewer auth |
| HUMAN_REVIEW | Escalation, queue, audit | BUG-005 | in-memory queue, not persisted |
| PERFORMANCE | Latency, memory, scalability | BUG-025 | live latency not measured |
| OTHER | Environment, API contract hygiene | BUG-001, BUG-019, BUG-027, BUG-033 (accessibility) | — |

Interpretation rule used (§149): a weak result is traced to its component before blaming the LLM. In Phase 7,
none of the measured failures were caused by LLM output. All were deterministic code, data or contract defects.
