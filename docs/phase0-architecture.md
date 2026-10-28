# SchemeSetu AI — Phase 0 Architecture

## Overview

SchemeSetu AI is an AI-powered conversational platform that helps Indian farmers discover government schemes they're eligible for. It uses voice input in native languages, an intelligent LangGraph-based conversational agent, and text-to-speech to make government benefits accessible.

## Current Architecture (Phase 0)

```
┌─────────────────┐     ┌──────────────────┐     ┌──────────────────────┐
│  Next.js         │────▶│  FastAPI          │────▶│  LangGraph Agent     │
│  Frontend        │◀────│  Backend          │◀────│  (Groq LLaMA 3.3)   │
│                  │     │                   │     │                      │
│  Components:     │     │  API Routes:      │     │  Nodes:              │
│  - ChatInput     │     │  - /chat          │     │  - extract_profile   │
│  - MessageList   │     │  - /voice         │     │  - check_completeness│
│  - ProfilePanel  │     │  - /tts           │     │  - ask_user          │
│  - SchemeList    │     │  - /health/*      │     │  - filter_schemes    │
│  - StatusIndicator│    │                   │     │                      │
└─────────────────┘     └──────────────────┘     └──────────────────────┘
                               │
                    ┌──────────┴──────────┐
                    │                      │
              ┌─────┴─────┐        ┌──────┴─────┐
              │  Sarvam AI │        │  Neon DB    │
              │  (ASR/TTS) │        │ (PostgreSQL)│
              └───────────┘        └────────────┘
                    │
              ┌─────┴─────┐
              │  Tavily    │
              │  (Search)  │
              └───────────┘
```

## Backend Structure

```
backend/
    app/
        main.py                    # FastAPI app creation, middleware, lifespan
        
        core/
            config.py              # Centralized Pydantic Settings
            logging.py             # Structured logging configuration
            exceptions.py          # Custom exception hierarchy
        
        api/
            chat.py                # POST /chat route
            voice.py               # POST /voice, POST /tts routes
            health.py              # GET /, /health, /health/live, /health/ready
        
        models/
            profile.py             # FarmerProfile with merge & completeness
            scheme.py              # Scheme and RecommendedScheme
            requests.py            # ChatRequest, TTSRequest
            responses.py           # ChatResponse, TTSResponse, HealthResponse
        
        services/
            llm_service.py         # Groq LLM abstraction
            search_service.py      # Tavily web search abstraction
            voice_service.py       # Sarvam ASR + TTS abstraction
            scheme_service.py      # Multi-source scheme discovery
        
        graph/
            state.py               # LangGraph state definition
            nodes.py               # Graph node functions
            workflow.py            # Graph construction & compilation
            routing.py             # Routing decision functions
        
        database/
            connection.py          # Lifecycle-safe connection pool
            repositories.py        # SchemeRepository (SQL abstraction)
        
        utils/
            serialization.py       # Response building, message extraction
            validation.py          # Audio upload validation
        
        tests/
            test_profile.py        # Profile model & merge tests
            test_routing.py        # Routing logic tests
            test_serialization.py  # Response building tests
            test_validation.py     # Audio validation tests
            test_api_health.py     # Health endpoint integration tests
            test_config.py         # Configuration & exception tests
```

## Frontend Structure

```
frontend/src/
    app/
        page.tsx                   # Main page (composition root)
        layout.tsx                 # Root layout with metadata
        globals.css                # Global styles
    
    components/
        ChatInput.tsx              # Text input + voice button
        MessageList.tsx            # Chat message display
        ProfilePanel.tsx           # Extracted farmer profile display
        SchemeList.tsx             # Recommended schemes with XAI
        StatusIndicator.tsx        # Header with status indicator
    
    lib/
        api.ts                     # Centralized API client
        types.ts                   # TypeScript type definitions
```

## Request Flow

### Text Chat Flow
```
User types message
    → ChatInput component
    → sendChat() in lib/api.ts
    → POST /chat (api/chat.py)
    → LangGraph kisan_agent.ainvoke()
        → extract_profile (llm_service)
        → check_completeness (deterministic)
        → [ask_user OR filter_schemes]
    → build_chat_response (serialization)
    → ChatResponse to frontend
    → MessageList + ProfilePanel update
```

### Voice Flow
```
User records audio (actual browser MIME type)
    → sendVoice() in lib/api.ts  
    → POST /voice (api/voice.py)
    → validate_audio_upload
    → transcribe_audio (voice_service → Sarvam ASR)
    → LangGraph kisan_agent.ainvoke()
    → build_chat_response
    → ChatResponse to frontend
    → Auto-TTS playback
```

### TTS Flow
```
Agent reply text
    → generateTTS() in lib/api.ts
    → POST /tts (api/voice.py)
    → generate_speech (voice_service → Sarvam TTS)
    → TTSResponse with base64 audio
    → Browser Audio playback
```

## LangGraph Workflow

```
    ┌─────────────────┐
    │  extract_profile │  ← LLM structured extraction
    └────────┬────────┘
             │
    ┌────────▼────────┐
    │check_completeness│  ← Deterministic field check
    └────────┬────────┘
             │
       ┌─────┴─────┐
       │            │
  ┌────▼───┐  ┌────▼────────┐
  │ask_user│  │filter_schemes│
  │(question)│ │(search+reason)│
  └────┬───┘  └────┬────────┘
       │            │
       ▼            ▼
      END          END
```

## Configuration

All configuration is centralized in `app/core/config.py` using Pydantic Settings.
The application does NOT crash if API keys are missing — services validate at usage time.

## Error Handling

Custom exceptions (`app/core/exceptions.py`) are caught by:
1. Route-level try/except → structured ChatResponse/TTSResponse
2. FastAPI global exception handler → JSON error response

Error responses follow this format:
```json
{
    "status": "error",
    "error": {
        "code": "EXTERNAL_SERVICE_ERROR",
        "message": "User-safe message",
        "request_id": "abc123"
    }
}
```

## Phase 0 → Phase 1 Extension Points

| Extension Point | Current | Future |
|---|---|---|
| `SchemeRepository` | Basic SQL search | Knowledge Graph + semantic search |
| `search_service` | Tavily only | Multi-source fusion |
| `llm_service` | Single Groq model | Multi-agent supervisor |
| `voice_service` | Sarvam direct | Advanced multilingual pipeline |
| `FarmerProfile` | 9 fields | Expanded with eligibility fields |
| `routing.py` | Binary complete/incomplete | Multi-branch with eligibility engine |
| `MemorySaver` | In-memory | Persistent PostgreSQL checkpointer |
