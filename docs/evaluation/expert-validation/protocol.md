# Expert Validation — Protocol

> **Status: SAMPLE PREPARED, NOT CONDUCTED.** No expert has rated any output. No approval of any kind is claimed.

- **Reviewers:** one or two people from agriculture-domain faculty, agricultural extension, or farmer-welfare
  scheme administration. Only their role is recorded.
- **Material:** `data/evaluation/expert_validation/sample_outputs.json`, regenerated from real system outputs on
  every evaluation run (scheme data, eligibility evidence, explanation, documents, steps, source).
- **Task per sample:** the status the expert would expect; accuracy (CORRECT / PARTIALLY_CORRECT /
  INCORRECT); explanation (XAI_CORRECT / XAI_INCORRECT); source (SOURCE_CORRECT / SOURCE_INCORRECT); comments.
- **Recording:** `data/evaluation/expert_validation/ratings.json` (template: `ratings.template.json`).
- **Disagreements** never change system output automatically. Each is investigated and classified as corpus /
  rule / source conflict / model / evaluator, then logged in `docs/phase7-bug-register.md` if it is a defect.
