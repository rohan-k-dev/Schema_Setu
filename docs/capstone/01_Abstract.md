# 1. Abstract

Indian farmers are entitled to many central and state welfare schemes, but the information about them is
scattered, written mostly in English, and eligibility conditions are hard to interpret. SchemeSetu is a
conversational assistant that collects a farmer's profile through text or voice in 11 Indian languages.
It retrieves candidate schemes in parallel from a canonical PostgreSQL database, a derived Knowledge Graph
and live web search. A **deterministic rule engine** with three-valued (Kleene) logic decides eligibility, and
the system explains each decision with evidence-grounded explanations. A LangGraph multi-agent workflow
orchestrates profile extraction, completeness checking, follow-up questions, retrieval, eligibility,
ranking and response generation. Large language models are used only for language understanding and
wording, never for the eligibility decision. Their output is validated against the evidence before it is shown.
Uncertain cases are escalated to a human-review queue.

The system was evaluated with an offline framework of about 400 hand-labelled cases (eligibility, retrieval,
explainability, multilingual parity, voice plumbing, red-team, end-to-end journeys) in which external AI
services are mocked. A measure–fix–re-measure cycle found and fixed 35 defects. The scorecard moved from
19/45 measured metrics passing to 47/47, including 100% scheme-level eligibility accuracy on 104 cases, 0%
false positives, retrieval recall of targeted schemes 0.25 → 1.0, and rejection of 128/128 fabricated
explanations. Live latency against the 10–15 s target, speech-recognition accuracy, a user study and expert
validation have **not yet been measured**; they are reported as open items.
