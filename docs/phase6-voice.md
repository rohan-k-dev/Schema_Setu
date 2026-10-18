# Phase 6 — Voice Architecture

## Pipeline

```
Browser Mic → Audio Validation → ASR → Translation → LangGraph → Eligibility → XAI → TTS → Browser
```

### Detailed Flow

1. **Browser recording**: MediaRecorder API detects supported MIME type (WebM/OGG/WAV)
2. **Audio validation**: MIME type check, file size limit (10MB), extension mapping
3. **ASR** (Sarvam speech-to-text-translate): language-aware with hint from user selection
4. **Translation** (Sarvam translate): native language → English canonical text
5. **LangGraph**: Same pipeline as text — profile → retrieval → eligibility → XAI
6. **Response translation**: English → native language
7. **TTS** (Sarvam text-to-speech): generates audio in user's selected language
8. **Browser playback**: HTML5 Audio with base64 data URI

## Voice State Machine (§24)

```
IDLE → RECORDING → UPLOADING → TRANSCRIBING → PROCESSING → IDLE
  ↘                                                      ↙
                         ERROR
```

## Critical Design Principle

**Voice and text use the SAME LangGraph pipeline** (§5). Voice is only an input/output channel:
- ASR normalizes voice → text
- TTS normalizes text → audio
- The "intelligence" is one system, regardless of modality

## Fallback Behavior

| Failure | Behavior |
|---------|----------|
| Mic denied | Text input remains usable (§160) |
| ASR fails | Error message + "use text" prompt (§29) |
| TTS fails | Text response still displayed (§159) |
| MediaRecorder unsupported | Text-only mode (§116) |

## Files

| File | Purpose |
|------|---------|
| `backend/app/services/voice_service.py` | ASRResult model, language-aware ASR/TTS |
| `backend/app/api/voice.py` | Voice API with language param + translation |
| `frontend/src/components/ChatInput.tsx` | Voice state machine UI |
| `frontend/src/app/page.tsx` | Recording + playback orchestration |

## Browser Compatibility (§116–§117)

- **Chrome/Edge**: WebM with Opus codec (primary)
- **Firefox**: OGG with Opus codec
- **Safari**: May require WAV fallback
- Unsupported browsers: text input remains fully available
