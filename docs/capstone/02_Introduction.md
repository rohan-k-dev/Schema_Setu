# 2. Introduction

Government welfare schemes for farmers cover income support, crop insurance, credit, irrigation, organic
farming, mechanisation and state-specific assistance. A farmer who wants to know "which schemes apply to me?"
must find the right portals, read eligibility text in a language they may not be comfortable with, and work
out whether conditions such as land holding, crop, state, gender or social category apply.

SchemeSetu addresses this with a conversational, explainable assistant:
- the user talks (text or voice, in their language) instead of filling a long form;
- the system asks only for what it needs (state, land, crop first);
- every recommendation comes with a status (eligible, not eligible, needs more information, cannot verify),
  the criteria behind it, the documents and application steps, and the official source;
- uncertain cases go to a human reviewer instead of being guessed.

The project was built in eight phases: core platform, corpus engineering, PostgreSQL persistence, Knowledge
Graph, agentic orchestration with hybrid retrieval, a deterministic eligibility engine with XAI, multilingual
voice with human review, and evaluation and hardening, followed by this release phase. This report
describes the final implementation (v1.0.0) and its measured evaluation.
