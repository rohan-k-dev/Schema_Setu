# Data Flow & Authority

## Who is authoritative for what

| Information | Authority | Never decided by |
|---|---|---|
| Scheme facts (name, description, benefits, documents, steps, official URL) | **PostgreSQL** (imported from `data/validated/schemes.json`, corpus v1.0.0) | Web results (they may add a source record, never overwrite) |
| Which schemes are *candidates* | DB search + Knowledge Graph (+ web discovery mapped to corpus IDs) | LLM |
| Eligibility status | **Deterministic engine** (`eligibility/evaluator.py`) over DB rules | LLM, web, graph |
| Explanation content (criteria, numbers, sources) | **Rule evidence** (`RuleResult`), deterministic templates | LLM. It may only rephrase, and its text is validated against the evidence |
| Conversation state (profile, last answer) | LangGraph checkpointer, per `thread_id` | Other sessions |
| Language of presentation | Sarvam translation of the reply text | Structured data is never translated |

## End-to-end flow

```
User text / voice
  │  (voice: ASR → transcript;  non-English: translate → English)
  ▼
profile_agent ── LLM structured extraction (untrusted) ──► FarmerProfile validators
  │                                                    (canonical state/crop/category/gender,
  │                                                     invalid → unknown, never guessed)
  ▼ merge with session profile (changed values → confirmation question)
completeness_agent (deterministic) ── missing state/land/crop? → one question
  ▼
query_rewriter ── ordinal follow-up resolved deterministically against the previous answer
  ▼
retrieval_agent ── parallel:  PostgreSQL (canonical) │ Knowledge Graph (derived) │ Tavily (untrusted)
  ▼ merge: one candidate per canonical scheme_id; DB fields win; conflicts recorded
eligibility_agent ── rules from PostgreSQL × profile → PASS/FAIL/UNKNOWN → status
  ▼
recommendation_agent ── deterministic ranking; review escalation on deterministic triggers
  ▼
response_formatter ── scheme cards (DB facts + evidence + deterministic explanation)
                     LLM wording → grounding validator → else deterministic reply
  ▼ reply translated to the user's language; scheme cards unchanged
User
```

## Origin labels the user can see
- Each scheme card shows `retrieval_sources` (DATABASE / KNOWLEDGE_GRAPH / LIVE_WEB), `sources`, and
  `official_url` from the canonical record ("View official source").
- Matched / failed / missing criteria come from `RuleResult` evidence, each with the rule's source text and
  the scheme's official URL (`source_references`).
- The frontend states that results are "checked against the published criteria in SchemeSetu's scheme
  database" and are not a guarantee of approval.

## What leaves the server
| Destination | Data sent |
|---|---|
| Groq | Recent conversation messages; profile summary limited to state, district, land, crop, occupation; top-10 scheme cards with sensitive user values (income, category, gender, Aadhaar status, age) replaced by "(provided by user)" |
| Tavily | Query built from state and crop only |
| Sarvam | User text or audio for ASR/translation; reply text for translation/TTS |
| Logs | Field *names*, lengths, IDs, statuses. No profile values, no transcripts |

## Canonical data update path
`data/raw` → `scripts/build_corpus.py` / `validate_corpus.py` → `data/validated/schemes.json` →
`scripts/import_corpus.py` (idempotent upsert, new `corpus_versions` row) → `scripts/build_knowledge_graph.py`
(new snapshot). Live web content is never written to the database.
