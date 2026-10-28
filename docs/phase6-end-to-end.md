# Phase 6 — End-to-End User Flow

## Complete User Journey (§150)

1. **Open SchemeSetu** → landing page with language selector
2. **Choose language** → select from 11 Indian languages
3. **Use text OR voice** → both use same LangGraph pipeline
4. **Provide profile** → "I am from Karnataka, 2 acres, growing ragi"
5. **Receive follow-up** → "What is your annual income?"
6. **Complete profile** → answer follow-up questions
7. **Get candidates** → DB + Graph + Web parallel retrieval
8. **Eligibility evaluated** → deterministic rule engine
9. **See why it matches** → XAI evidence breakdown
10. **See why it doesn't** → failed criteria with specific rules
11. **See missing info** → fields needed for evaluation
12. **View benefits** → scheme benefit summaries
13. **View documents** → expandable required document list
14. **View steps** → how to apply instructions
15. **Open source** → official URL link
16. **Ask follow-up** → "What documents for the first scheme?"
17. **Switch language** → profile preserved, only presentation changes
18. **Switch to voice** → same session, same thread
19. **Receive spoken response** → TTS in selected language
20. **Trigger review** → UNVERIFIABLE case → review queue

## Acceptance Tests (§151–§165)

| Test | Input | Expected |
|------|-------|----------|
| §151 | Kannada voice: "I am from Mandya, grow ragi on 2 acres" | Profile extracted → eligibility → Kannada TTS |
| §155 | "Actually, I have 5 acres, not 2" | Profile update → re-evaluation |
| §157 | Tavily unavailable | DB + Graph results still work |
| §159 | TTS unavailable | Text response displayed |
| §160 | Mic permission denied | Text input fully usable |
| §161 | Language: Hindi → Kannada | Profile unchanged |
| §163 | Aadhaar spoken | Only has_aadhaar retained |
| §165 | No scheme candidates | "No matching scheme found" |
