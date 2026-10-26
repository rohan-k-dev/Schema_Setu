# SchemeSetu Data Policy

## 1. Source Priority

When the same scheme appears in multiple sources, prefer:

1. **Official Central Government source** (e.g., ministry website, scheme portal)
2. **Official State Government source** (e.g., state agriculture department)
3. **Official Scheme Portal** (e.g., MyScheme.gov.in)
4. **Trusted Secondary source** (e.g., Vikaspedia)

Never silently replace an official source with an unverified web page.

## 2. No-Fabrication Policy

If the source does not provide a field value:
- Store `null` or `"unknown"`
- **Never** let the LLM fill the gap
- **Never** infer values from general assumptions

Examples:
- `income_requirement = unknown` (NOT `income_requirement = false`)
- `application_url = null` (NOT a guessed URL)
- `land_size_acres <= 5` only if the source **explicitly** states this threshold

## 3. Uncertainty Policy

The corpus distinguishes between:
- **Known**: Value confirmed by source
- **Unknown**: Value not available in source
- **Not applicable**: Field does not apply to this scheme

Unknown must be first-class. Never convert missing information to `false` or `0`.

## 4. Duplicate Policy

- Duplicates are detected by normalized name, aliases, and official URL
- Detected duplicates are **flagged**, never auto-merged
- A manual review queue is generated for uncertain cases
- Domain-only URLs (e.g., `https://agricoop.nic.in`) do NOT trigger duplicate detection

## 5. Conflict Policy

When two sources disagree on a value:
- Do NOT choose one silently
- Prefer the higher-priority source (see Source Priority)
- If unresolvable, flag for manual review
- Preserve both source references

## 6. Source Verification Policy

- Every scheme must have at least one source record
- Source records must include retrieval timestamp
- Verification timestamps are separate from retrieval timestamps
- Source URLs must be valid HTTP/HTTPS format

## 7. Versioning Policy

- Every corpus build creates a dated snapshot
- Previous snapshots are never overwritten
- The corpus manifest tracks version, hash, and generation metadata
- Schema version is tracked separately from corpus version

## 8. LLM Usage Policy

- LLMs may assist in data extraction, but output must be verified against source
- If LLM extraction conflicts with source text, **source wins**
- Conflicting records are flagged for review
- The source document remains authoritative at all times
