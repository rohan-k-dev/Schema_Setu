# 3. Problem Statement

Design and implement a system that helps Indian farmers discover the government schemes they may be eligible
for, such that:
1. information is gathered conversationally, by text or voice, in the user's language;
2. candidate schemes come from a trustworthy, versioned scheme database, complemented by relationship-based
   discovery and live search;
3. eligibility is decided **deterministically and reproducibly** from published criteria, never guessed by a
   language model, and missing information is treated as unknown rather than as failure;
4. every decision is **explained** with the evidence it was based on, including documents, application steps
   and sources;
5. uncertain or conflicting cases are routed to **human review**;
6. the system degrades gracefully when external services fail, and protects users' personal information.

Success is measured by eligibility correctness, retrieval quality, explanation grounding, language parity,
robustness to failures and attacks, and (pending) user and expert assessment.
