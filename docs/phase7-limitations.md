# Phase 7 — Known Limitations (§196)

These are stated plainly so that no project claim goes beyond the evidence.

## Evaluation coverage
- **Offline evaluation mocks every external service.** Groq, Tavily and Sarvam were not called during Phase 7
  (no API keys in this environment). Offline results measure SchemeSetu's own logic: profile handling after
  extraction, retrieval, eligibility, XAI, ranking, translation plumbing, review and security.
- **Not measured:** LLM profile-extraction accuracy, real Tavily result quality, Sarvam translation quality,
  ASR accuracy / WER, real TTS audio, and **end-to-end live latency against the Review-II 10–15 s target**.
  `scripts/run_evaluation.py --live` implements the extraction and latency measurements. It must be run with
  keys before claiming them.
- **User study and expert validation have not been conducted** (0 participants, 0 ratings). The protocol,
  sample and analysis are ready (`docs/phase7-user-study-report.md`, `docs/phase7-expert-validation.md`).
- **Stability:** a 10-minute offline soak was run, not the 1–2 hour target. Browser memory and microphone
  cleanup were checked by code review only (no automated browser run).
- **Database:** offline runs use a corpus-backed fixture that mirrors the repository SQL semantics. Connection
  pool behaviour under load and the new batched queries (`get_details_for_scheme_ids`,
  `list_for_scheme_ids` using `= ANY(%s)`) were not executed against PostgreSQL in this environment (Docker
  daemon not running). They need one run against a real database (Phase 8 deployment check).

## Languages
- 11 languages are declared in the registry and all pass the **offline** parity tests (same meaning → same
  profile, candidates, statuses, evidence). Real translation quality per language is unverified. SchemeSetu
  does **not** claim support for all 22 scheduled languages.
- Numbers written as words in Indian languages (e.g. "दो एकड़") depend on Sarvam translation and the LLM.
  This is untested live.

## Voice
- WER not measured: there is no recorded audio with ground-truth transcripts.
- ASR / TTS fall back safely (text reply kept, clear error codes), but real audio quality, accents and noise
  were not evaluated.

## Corpus and eligibility
- 40 curated schemes (corpus v1.0.0, 2026-09-26). **22 of 40 have no structured eligibility rules**, so they
  are always UNVERIFIABLE (45% of evaluations for fully stated profiles). This is the biggest quality limit and a
  corpus problem, not an engine one.
- Structured rules cover only the conditions extracted in Phase 1 (e.g. PM-KISAN exclusion criteria such as
  income-tax payers or institutional land holders are not encoded). ELIGIBLE means "matches the available
  published criteria", which the UI and replies state explicitly.
- `residence` (MGNREGA) has no profile field, so MGNREGA is always NEEDS_MORE_INFORMATION.
- No crop taxonomy: ragi does not map to NFSM's "millets".
- Source freshness: the corpus was verified on 2026-09-26. Scheme rules change and the corpus must be refreshed.

## Retrieval
- No fuzzy or transliterated scheme-name search (typos and Devanagari names return nothing rather than a
  guess).
- Web results that cannot be mapped to a known corpus scheme are dropped (safe, but limits discovery).
- Source-conflict detection compares structured fields only. Web results carry free text, so DB-vs-web
  conflicts are rarely detectable in practice.

## XAI / LLM safety
- The LLM-reply validator is pattern-based (eligibility claims, URLs, money amounts, bold scheme names). It
  blocked every probe in the red-team set, but a paraphrased false claim could evade it. The structured
  `eligibility_status` per scheme is always the engine's, and the deterministic reply is used whenever the
  validator rejects.

## Human review
- The review queue is **in memory** (academic simulation): it is lost on restart and not capped. The
  reviewer API uses one shared key (`REVIEW_API_KEY`), not per-user accounts. There is no reviewer UI; review
  happens through the documented API. Cases with UNVERIFIABLE results are frequent because of the corpus rule
  gap (one open case per session is kept to avoid flooding).

## Performance and deployment
- Offline per-request processing is about 0.1 s. The real latency is dominated by Groq, Tavily and Sarvam
  and is not measured.
- CPU-bound pipeline work runs on the event loop, so concurrent requests are largely serialised within one
  process. Scale-out requires multiple workers. Conversation state is in process memory (bounded at
  `MAX_SESSIONS`, default 1000), so multiple workers would also need sticky sessions or a shared checkpointer.
- No production deployment has been performed. Release status is *release candidate* only.
