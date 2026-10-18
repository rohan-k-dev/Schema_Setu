# Phase 4 — Conversation Context & Memory

## Session Management

Each conversation session is identified by a unique `thread_id`:
- `MemorySaver` checkpointer stores state per thread_id
- Sessions are fully isolated (profile, candidates, etc.)
- New unique UUIDs are generated if default_session is provided

## Profile Persistence

The farmer profile accumulates across turns:
1. User says "I am from Karnataka" → profile.state = "Karnataka"
2. User says "I have 2 acres" → profile.land_size_acres = 2.0
3. Profile.state is still "Karnataka" (never erased by None)

## Profile Conflict Detection

When a user contradicts their own profile:
1. Conflict is recorded: `{field: "state", old: "Karnataka", new: "Rajasthan"}`
2. User is asked to confirm
3. New value takes precedence after detection

## Contextual Query Resolution

The Query Rewriter handles follow-up references:

| User Message | Resolution |
|--------------|-----------|
| "Tell me about the first scheme" | scheme_id from position 1 in last response |
| "What documents for PM-KISAN?" | scheme_id = PM_KISAN |
| "The second one" | scheme_id from position 2, if available |
| "The third one" (only 2 exist) | needs_clarification = true |

## Multi-Turn Flow Example

```
Turn 1: "I am from Karnataka"
  → ProfileAgent: {state: "Karnataka"}
  → CompletenessAgent: missing = [land_size_acres, primary_crop]
  → QuestionAgent: "How many acres of land do you have?"

Turn 2: "I have 2 acres"
  → ProfileAgent: {state: "Karnataka", land_size_acres: 2.0}
  → CompletenessAgent: missing = [primary_crop]
  → QuestionAgent: "What is the main crop you grow?"

Turn 3: "I grow ragi"
  → ProfileAgent: {state: "Karnataka", land_size_acres: 2.0, primary_crop: "ragi"}
  → CompletenessAgent: complete!
  → QueryRewriter: {query: "schemes for ragi farmers in Karnataka", intent: scheme_search}
  → RetrievalAgent: DB + Graph + Web in parallel
  → ResponseFormatter: "Here are 3 relevant schemes..."

Turn 4: "What documents do I need for the first one?"
  → ProfileAgent: no change
  → CompletenessAgent: complete!
  → QueryRewriter: {intent: documents, referenced_scheme_id: "PM_KISAN"}
  → RetrievalAgent: exact DB lookup for PM_KISAN
  → ResponseFormatter: "For PM-KISAN you need..."
```

## Voice + Text Session Continuity

Voice and text use the same LangGraph workflow with the same thread_id, ensuring seamless context continuity:

```
Turn 1 (voice): "I am from Karnataka" → ASR → same graph
Turn 2 (text): "I have 2 acres" → same graph, same session
Turn 3 (voice): "I grow ragi" → same graph, same session
```
