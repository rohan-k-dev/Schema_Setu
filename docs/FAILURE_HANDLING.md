# Failure Handling & Fallback Matrix

Each row is implemented in the code referenced and verified by the test or evaluation listed
(`evaluation/runners/*`, `backend/app/tests/*`).

| Failure | Detection | Fallback | User sees | Logged | Recovery | Evidence |
|---|---|---|---|---|---|---|
| **Database unavailable** | `db_retriever` raises (`DatabaseUnavailableError` after an empty result plus a failed health check; pool errors); rule batch load fails | Graph + web candidates still retrieved; with no rules every candidate is **UNVERIFIABLE** (never ELIGIBLE); SYSTEM_ERROR review if ≥2 channels fail | `partial_results`; schemes marked "Needs additional verification"; `/health` → `degraded` | `Database retrieval failed`, `Database unavailable for rule loading` | On the next request once the DB is back (psycopg_pool re-opens connections; an outage-and-recovery cycle was not tested) | Failure matrix F03/F05/F06, E2E19 |
| **Knowledge Graph unavailable** (snapshot missing or corrupt) | `init_knowledge_graph()` returns False at start-up; `graph_retriever` raises `Knowledge Graph unavailable` | DB + web | `partial_results`; `/health` `graph_available:false` | `Knowledge Graph not available` | Rebuild: `python scripts/build_knowledge_graph.py`, restart | F02/F04, E2E18 |
| **Tavily unavailable / no key** | `search_service` raises `ExternalServiceError` / `ConfigurationError` | DB + graph | `partial_results` | `Tavily web search failed` | Automatic | F01, E2E17 |
| **LLM (Groq) unavailable / no key / timeout** | Exception in profile extraction; rewriter / formatter / question exceptions | Profile: known profile kept, request flagged. Rewriter: keyword intent + deterministic ordinal resolution. Formatter: deterministic evidence-based reply. Question: field template | If the profile can't be read: `status:error`, code `LANGUAGE_SERVICE_UNAVAILABLE`, "I can't understand free-text answers right now…". Otherwise normal results with deterministic wording | `Profile extraction error: <type>` | Automatic; `GROQ_TIMEOUT` (30 s, 1 retry) | test_phase8_llm_unavailable…, offline evaluation (LLM down throughout) |
| **LLM reply fabricates** | `validate_llm_response` | Deterministic reply | Grounded reply | `LLM reply rejected by grounding validator` | — | A13–A16 |
| **Sarvam unavailable (translation)** | `ExternalServiceError` in `language_service` | Inbound: original text passed on. Outbound: English reply | English reply; structured results unchanged | `Translation … failed` | Automatic | MLF1/MLF2, VF04 |
| **STT (ASR) unavailable** | `transcribe_audio` raises | Text input remains available | `status:error`, "Voice processing failed. Please try again or use text input." | `Sarvam ASR …` | Automatic | VF01 |
| **ASR returns empty** | empty transcript | — | `VOICE_TRANSCRIPTION_FAILED`, "couldn't understand the audio… type your question" | `Sarvam ASR returned empty transcript` | User retries | VF02 |
| **TTS unavailable** | `/tts` returns `error` | Text reply only (TTS is best-effort) | Reply text; no audio | `Sarvam TTS …` | Automatic | VF03 |
| **Voice / TTS not configured** | `ConfigurationError` | Text | "Voice service is not configured…" (no internal details) | Full message | Set `SARVAM_API_KEY` | API probe (Phase 8) |
| **Malformed / oversized / wrong-type audio** | `validate_audio_upload`: size ≤10 MB, MIME allow-list, magic bytes must match | Rejected before any ASR call | `VALIDATION_ERROR` with reason | `Audio validation failed` | User re-records | VF05–VF09, A24–A26 |
| **Invalid profile value** (negative, NaN, unknown state, SQL text) | `FarmerProfile` validators | Value becomes unknown; other fields kept | The assistant asks for that field again | — (no values logged) | User answers | PL08/PL19, A01–A07 |
| **Incomplete profile** | `completeness_agent` | — | One question (state → land → crop) | Missing field names | User answers | PL04–PL07 |
| **Changed / contradictory statement** | `_detect_conflicts` | New value applied tentatively | "You previously mentioned … confirm …" | Conflicting field names | User confirms | PL02, PL03, D09 |
| **No schemes found** | no candidates from any channel | — | `no_results`, "I could not find matching schemes…"; no invented schemes | `All retrieval sources failed or returned empty` | Change profile | A17 |
| **Conflicting scheme information** (rules or DB vs web) | `_detect_rule_conflicts`; `conflict_detector` | DB value kept; scheme UNVERIFIABLE (rules) | "Needs additional verification" + review notice | conflict logged | Human review / corpus fix | CF01, X17, C01 |
| **Retrieval timeout** | `asyncio.wait_for` per channel | Other channels answer | `partial_results` | `… search timed out after Ns` | Automatic | parallel benchmark; timeouts in `.env` |
| **Rate limit** | SchemeSetu has **no rate limiter** (no 429 from this API). Upstream 429s from Groq/Tavily/Sarvam surface as exceptions | Same as the service-unavailable rows above | Same as above | Exception logged | Automatic | — (limitation) |
| **Network failure (server side)** | External calls raise | Local DB + graph continue | `partial_results` / deterministic replies | Per service | Automatic | failure matrix |
| **Network failure (browser)** | `fetch` throws | Message kept for **Retry** | "I could not reach the server… press Retry"; status pill turns red ("Server unreachable") | console | Retry button / auto health poll (30 s) | frontend code |
| **Message too long / blank** | Pydantic validation | — | HTTP 422 | — | User shortens | A32, A33 |
| **Eligibility error for one scheme** | exception in `evaluate_scheme` | That scheme → UNVERIFIABLE; others unaffected | "Needs additional verification" | `Eligibility evaluation failed for …` | Fix the rule | eligibility agent |
| **Session store full** | `BoundedMemorySaver` > `MAX_SESSIONS` | Oldest conversation evicted | The evicted user starts a new conversation | — | — | test_bug025 |
