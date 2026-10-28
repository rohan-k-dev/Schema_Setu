# 6. Literature Survey

> **Note to the authors:** this survey positions SchemeSetu against well-known published work. Before submission,
> check every citation in `24_References.md` against the original publication and add any papers from your
> Review-I/II literature review. No reference here has been invented, but bibliographic details must be confirmed
> by the team.

## 6.1 Retrieval-augmented and tool-using language models
Retrieval-Augmented Generation [1] grounds a language model's output in retrieved documents instead of its
parametric memory alone. ReAct [2] interleaves reasoning with tool calls, the basis of today's agent frameworks.
SchemeSetu follows the retrieval-grounding idea but goes further for the critical decision: retrieved *rules*
are evaluated by deterministic code, and the LLM only phrases the result. Agent orchestration uses LangGraph
[16], a graph-structured state-machine framework, rather than a free-running ReAct loop, so routing is
deterministic and testable.

## 6.2 Hallucination and prompt injection
Surveys of hallucination in natural-language generation [4] show that fluent but unsupported content is a
systematic risk. Greshake et al. [5] demonstrate *indirect* prompt injection, where instructions embedded in
retrieved content hijack an LLM-integrated application. SchemeSetu's controls follow from both. The engine, not
the LLM, decides eligibility. Web content is treated as untrusted data. LLM replies are validated against
structured evidence (claims, numbers, URLs, scheme names) before display.

## 6.3 Knowledge graphs
Hogan et al. [3] survey knowledge graphs as a way to represent entities and relations for integration and
traversal. SchemeSetu uses a small, derived property graph (NetworkX [10]) linking schemes to states, crops,
beneficiaries, documents, rules and sources. It supports profile-to-scheme candidate discovery with explicit
match evidence, while PostgreSQL remains the system of record.

## 6.4 Explainability
Post-hoc explanation methods such as LIME [6] and SHAP [7] approximate why an opaque model produced an output.
Doshi-Velez and Kim [8] argue for rigorous, task-grounded evaluation of interpretability. SchemeSetu's decisions
come from transparent rules, so explanations can be *exact* rather than approximate: every statement is derived
from a rule result with its source text. Phase 7 evaluates explanation grounding quantitatively.

## 6.5 Reasoning with incomplete information
Kleene's strong three-valued logic [9] defines AND/OR over true/false/unknown. SchemeSetu uses it so that a
missing profile value yields "needs more information" rather than a false "not eligible".

## 6.6 Multilingual and speech technology for Indian languages
Large-scale weakly supervised speech recognition [13] and Indic machine translation covering the 22 scheduled
languages [14] have made multilingual voice interfaces practical. SchemeSetu uses a commercial Indic speech and
translation API (Sarvam [19]) and keeps all reasoning in English, with translation applied only at the edges.

## 6.7 Human-AI interaction and human-in-the-loop
Guidelines for human-AI interaction [11] recommend making clear what a system can do and supporting correction
when it is wrong. Human-in-the-loop machine learning [12] studies where people should intervene. SchemeSetu
applies this at decision time: deterministic triggers (unverifiable, conflicting rules or sources, system errors)
open review cases. Reviewers act through an audited API, and canonical data is never silently changed.

## 6.8 Existing government platforms
The national myScheme portal [17] offers scheme search and eligibility-based filtering. Individual scheme portals
such as PM-KISAN [18] provide authoritative details and application. SchemeSetu does not replace these. It adds a
conversational, multilingual, voice-capable front end with per-criterion explanations, and links back to the
official sources.

## 6.9 Gap addressed
Existing work offers either authoritative but form-based portals, or fluent but unverifiable LLM chatbots.
SchemeSetu combines conversational access with deterministic, evidence-backed eligibility decisions,
relationship-based discovery, validation of LLM output, and a human escalation path. It is evaluated with
labelled datasets and red-team tests.
