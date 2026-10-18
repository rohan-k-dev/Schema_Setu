# SchemeSetu Architecture

Every diagram below matches the code at release v1.0.0. File paths are relative to the repository root.

**Responsibilities**

| Layer | Role | Code |
|---|---|---|
| PostgreSQL | Canonical system of record for scheme data (40 schemes, rules, documents, steps, sources, corpus versions) | `backend/alembic/`, `backend/app/database/` |
| Knowledge Graph (NetworkX) | *Derived* relationship and traversal layer, built from the same canonical corpus; candidate discovery only | `backend/app/knowledge_graph/` |
| LangGraph | Workflow / orchestration of the agents | `backend/app/graph/workflow.py` |
| Eligibility engine | Deterministic decision system (rules × profile → status) | `backend/app/eligibility/` |
| XAI | Evidence-based explanations and validation | `backend/app/xai/` |
| LLM (Groq, Llama 3.3 70B) | Language understanding (profile extraction), query rewriting, reply wording. **Never decides eligibility** | `backend/app/services/llm_service.py`, `agents/` |
| Tavily | External discovery; untrusted; never overwrites canonical data | `backend/app/retrieval/web_retriever.py` |
| Sarvam | ASR, TTS, translation | `backend/app/services/voice_service.py`, `language_service.py` |
| Human review | Exception path on deterministic triggers | `backend/app/services/review_service.py`, `api/review.py` |

## 1. High-level system architecture

```mermaid
flowchart LR
    U[User<br/>browser / phone] -->|text, voice, language| FE[Next.js 15 frontend<br/>frontend/src]
    FE -->|JSON / multipart over HTTPS| API[FastAPI backend<br/>backend/app/main.py]
    API --> LG[LangGraph workflow<br/>graph/workflow.py]
    API --> LS[Language service<br/>Sarvam translate]
    API --> VS[Voice service<br/>Sarvam ASR/TTS]
    LG --> LLM[Groq LLM<br/>extraction, rewrite, wording]
    LG --> RET[Hybrid retrieval]
    RET --> PG[(PostgreSQL<br/>canonical schemes)]
    RET --> KG[(Knowledge Graph<br/>NetworkX snapshot)]
    RET --> TV[Tavily web search]
    LG --> EE[Deterministic eligibility engine]
    EE --> XAI[XAI templates + validators]
    LG --> HR[Human review queue<br/>in memory]
    API --> HR
    Reviewer[Reviewer] -->|X-Review-Key| API
```

## 2. Request lifecycle (POST /chat)

```mermaid
sequenceDiagram
    participant B as Browser
    participant A as /chat (api/chat.py)
    participant T as language_service
    participant G as LangGraph (kisan_agent)
    participant S as BoundedMemorySaver
    B->>A: {message, thread_id, language}
    A->>A: validate (≤2000 chars, not blank)
    A->>T: translate_to_internal (non-English only)
    A->>G: ainvoke(messages, session_id, review flags reset)
    G->>S: load session state (thread_id)
    G->>G: profile → completeness → (question | rewrite → retrieval → eligibility → recommendation → formatter)
    G->>S: save session state
    G-->>A: final state
    A->>A: build_chat_response (status, reply, schemes, profile, review, thread_id)
    A->>T: translate_from_internal (reply text only)
    A-->>B: ChatResponse JSON
```

## 3. LangGraph workflow

```mermaid
flowchart TD
    START((start)) --> P[profile_agent<br/>LLM structured extraction → FarmerProfile validators → merge, conflict detection]
    P --> C[completeness_agent<br/>deterministic: state, land, crop]
    C -->|conflict or missing field| Q[question_agent<br/>one question; template fallback; LLM-unavailable notice]
    C -->|complete| R[query_rewriter<br/>deterministic ordinal resolution, then LLM or keyword fallback]
    R -->|needs clarification| Q
    R -->|clear| RT[retrieval_agent<br/>parallel DB + Graph + Web]
    RT --> E[eligibility_agent<br/>batch rule load, evaluate_scheme per candidate]
    E --> REC[recommendation_agent<br/>deterministic ranking + review escalation]
    REC --> F[response_formatter<br/>LLM wording → grounding validator → deterministic fallback]
    Q --> END((end))
    F --> END
```

Session state is checkpointed per `thread_id` in `BoundedMemorySaver` (`graph/workflow.py`), capped at
`MAX_SESSIONS`, with constant-cost equality and repr.

## 4. Retrieval architecture

```mermaid
flowchart LR
    REQ[RetrievalRequest<br/>state, crop, district, category, gender, occupation, intent, referenced id] --> G{{asyncio.gather<br/>per-channel timeouts}}
    G --> DB[db_retriever<br/>SQL search → targeting-first order → batch details]
    G --> GR[graph_retriever<br/>profile → candidate schemes, restrictions respected]
    G --> WB[web_retriever<br/>Tavily; state + crop only in query]
    DB --> M[merger<br/>dedupe by canonical scheme_id, DB authoritative,<br/>conflicts recorded, targeted first]
    GR --> M
    WB --> M
    M -->|referenced scheme only, if any| OUT[≤ MAX_CANDIDATES candidates + errors + conflicts]
```

Failures are raised by each channel and recorded in `retrieval_errors`. The other channels still answer.
Web results that cannot be mapped to a corpus scheme are dropped.

## 5. Knowledge Graph structure (corpus v1.0.0 snapshot: 179 nodes, 356 edges)

```mermaid
flowchart LR
    SCHEME((SCHEME ×40))
    SCHEME -- APPLIES_TO_STATE ×14 --> STATE((STATE ×14))
    STATE -- PART_OF ×14 --> COUNTRY((COUNTRY ×1))
    SCHEME -- GLOBAL_APPLICABILITY ×33 --> COUNTRY
    SCHEME -- TARGETS_CROP ×18 --> CROP((CROP ×18))
    SCHEME -- TARGETS_BENEFICIARY ×78 --> BEN((BENEFICIARY ×35))
    SCHEME -- TARGETS_CATEGORY ×2 --> CAT((CATEGORY ×2))
    SCHEME -- TARGETS_GENDER ×1 --> GEN((GENDER ×1))
    SCHEME -- TARGETS_OCCUPATION ×8 --> OCC((OCCUPATION ×1))
    SCHEME -- HAS_ELIGIBILITY_RULE ×25 --> RULE((ELIGIBILITY_RULE ×25))
    SCHEME -- REQUIRES_DOCUMENT ×41 --> DOC((DOCUMENT ×15))
    SCHEME -- PROVIDES_BENEFIT ×40 --> BNF((BENEFIT ×8))
    SCHEME -- OFFERED_BY_MINISTRY ×40 --> MIN((MINISTRY ×13))
    MIN -- BELONGS_TO_DEPARTMENT ×2 --> DEP((DEPARTMENT ×1))
    SCHEME -- HAS_SOURCE ×40 --> SRC((SOURCE ×5))
```

The graph is built by `scripts/build_knowledge_graph.py` from `data/validated/schemes.json` (the same file
imported into PostgreSQL) and saved to `data/graph/current/`. It is loaded once at start-up. It is **not** the
eligibility engine.

## 6. Eligibility pipeline

```mermaid
flowchart LR
    RULES[(eligibility_rules<br/>PostgreSQL)] --> EV
    PROF[FarmerProfile<br/>canonical values] --> N[normalize<br/>state/crop/category aliases, lakh/crore, reject negative/NaN]
    N --> EV[evaluate_rule ×N<br/>11 operators → PASS / FAIL / UNKNOWN]
    EV --> CF{conflicting rules?<br/>numeric bounds or disjoint values}
    CF -->|yes| UV[UNVERIFIABLE + review]
    CF -->|no| LG[Kleene AND/OR groups<br/>required rules only]
    LG -->|PASS| EL[ELIGIBLE]
    LG -->|FAIL| NE[NOT_ELIGIBLE]
    LG -->|UNKNOWN| NM[NEEDS_MORE_INFORMATION]
    NORULES[no structured rules] --> UV
```

Derived field (documented policy): `has_land = land_size_acres > 0` when `has_land` is not stated.

## 7. Voice pipeline

```mermaid
sequenceDiagram
    participant M as Microphone (MediaRecorder, real MIME e.g. audio/webm;codecs=opus)
    participant V as /voice
    participant ASR as Sarvam ASR
    participant T as Sarvam translate
    participant G as same LangGraph pipeline
    participant TTS as /tts → Sarvam TTS
    M->>V: multipart upload + thread_id + language
    V->>V: size ≤10 MB, MIME allow-list, magic-byte sniffing, server-generated filename
    V->>ASR: audio
    ASR-->>V: transcript (or failure → error + "use text input")
    V->>T: to English (failure → untranslated text)
    V->>G: same path as /chat
    G-->>V: reply + schemes
    V->>T: reply to user language (failure → English)
    V-->>M: ChatResponse incl. user_transcript
    M->>TTS: reply text (best effort; failure → text only; user can stop audio)
```

## 8. Multilingual pipeline

```mermaid
flowchart LR
    IN[User text in hi/kn/ta/te/mr/bn/gu/od/pa/ml] --> TI[translate_to_internal → English]
    TI --> P[Pipeline runs in English<br/>profile, retrieval, eligibility, XAI evidence]
    P --> S[Structured schemes & statuses<br/>never translated]
    P --> R[Reply text]
    R --> TO[translate_from_internal → user language]
```

11 languages are declared in `localization/languages.py`. Offline parity tests cover all 11. Live Sarvam
quality is not measured.

## 9. Human-review flow

```mermaid
stateDiagram-v2
    [*] --> PENDING: escalate_if_needed()<br/>RULE_CONFLICT · UNVERIFIABLE · SOURCE_CONFLICT · SYSTEM_ERROR<br/>(one open case per session and reason)
    PENDING --> IN_REVIEW: REQUEST_INFORMATION
    PENDING --> DISMISSED: dismiss
    IN_REVIEW --> RESOLVED: APPROVE / REJECT / MARK_UNVERIFIABLE
    IN_REVIEW --> DISMISSED: dismiss
    RESOLVED --> [*]
    DISMISSED --> [*]
```

## 10. Deployment architecture (docker-compose.yml)

```mermaid
flowchart LR
    subgraph Host
      FE[frontend<br/>node server.js :3000]
      BE[backend<br/>uvicorn :8000]
      INIT[init one-shot<br/>alembic → import_corpus → db_check]
      PG[(postgres:16<br/>volume pgdata)]
    end
    Browser -->|:3000| FE
    Browser -->|:8000 NEXT_PUBLIC_API_BASE_URL| BE
    INIT --> PG
    BE --> PG
    BE -->|HTTPS| Groq & Tavily & Sarvam
```
