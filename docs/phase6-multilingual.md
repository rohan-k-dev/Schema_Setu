# Phase 6 — Multilingual Architecture

## Supported Languages

| Language | Code | Sarvam Code | ASR | TTS | Translation | UI |
|----------|------|-------------|-----|-----|-------------|-----|
| English | en | en-IN | ✅ | ✅ | ✅ | ✅ |
| Hindi | hi | hi-IN | ✅ | ✅ | ✅ | ✅ |
| Kannada | kn | kn-IN | ✅ | ✅ | ✅ | ✅ |
| Tamil | ta | ta-IN | ✅ | ✅ | ✅ | ✅ |
| Telugu | te | te-IN | ✅ | ✅ | ✅ | ✅ |
| Marathi | mr | mr-IN | ✅ | ✅ | ✅ | ✅ |
| Bengali | bn | bn-IN | ✅ | ✅ | ✅ | ✅ |
| Gujarati | gu | gu-IN | ✅ | ✅ | ✅ | ✅ |
| Odia | od | od-IN | ✅ | ✅ | ✅ | ✅ |
| Punjabi | pa | pa-IN | ✅ | ✅ | ✅ | Partial |
| Malayalam | ml | ml-IN | ✅ | ✅ | ✅ | Partial |

## Architecture

```
USER → Language Selector → API (language param)
                                ↓
                        translate_to_internal()
                                ↓
                     LangGraph (English only)
                                ↓
                       translate_from_internal()
                                ↓
                        Native-language response
```

### Key Design Decisions

1. **Internal language is English** — all LangGraph processing, profile extraction, and eligibility evaluation happens in English
2. **Translation = presentation only** — translation never alters structured profile facts
3. **Language registry is centralized** — `backend/app/localization/languages.py` is the single source of truth
4. **No hardcoded language codes** — all code uses the registry's lookup helpers
5. **Safe fallback** — if translation fails, English text is returned (no crash)

## Files

| File | Purpose |
|------|---------|
| `backend/app/localization/__init__.py` | Package init |
| `backend/app/localization/languages.py` | Language registry (11 languages, support levels) |
| `backend/app/services/language_service.py` | Translation service (translate_to/from_internal) |
| `frontend/src/components/LanguageSelector.tsx` | Language selector dropdown |

## Known Limitations

- Translation quality depends on Sarvam API accuracy
- Code-mixed input (e.g., Hindi + English) handled via Sarvam but may have lower accuracy
- UI labels are only fully localized for English; other languages use native script names
