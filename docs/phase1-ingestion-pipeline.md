# Phase 1 — Ingestion Pipeline Documentation

## Pipeline Architecture

```
RAW SOURCE
    |
FETCH (fetcher) - download source material, store raw content
    |
RAW STORAGE - data/raw/sources/<source>/
    |
TEXT EXTRACTION (extractor) - extract text from HTML/PDF
    |
SCHEME EXTRACTION - identify individual schemes from source
    |
FIELD NORMALIZATION (normalizer) - normalize states, crops, categories
    |
ELIGIBILITY RULE NORMALIZATION - convert eligibility to structured rules
    |
DOCUMENT NORMALIZATION - structure required documents
    |
APPLICATION STEP NORMALIZATION - structure application steps
    |
SOURCE ATTACHMENT - attach source provenance records
    |
DEDUPLICATION (deduplicator) - detect and flag duplicates
    |
VALIDATION (validator) - check data quality
    |
MANUAL REVIEW QUEUE - flag uncertain records
    |
VALIDATED CORPUS - data/validated/schemes.json
    |
VERSIONED SNAPSHOT - data/snapshots/YYYY-MM-DD/
```

## Current Implementation

### Phase 1 implements:
- **Normalizer** (`backend/app/ingestion/normalizer.py`) — state/crop/category/gender normalization with alias tables
- **Validator** (`backend/app/ingestion/validator.py`) — hard errors + soft warnings
- **Deduplicator** (`backend/app/ingestion/deduplicator.py`) — name/alias/URL-based duplicate detection
- **Exporter** (`backend/app/ingestion/exporter.py`) — JSON export, snapshots, manifests, reports
- **Corpus Loader** (`backend/app/ingestion/corpus_loader.py`) — runtime in-memory search

### Phase 1 uses manual curation for:
- Source fetching (schemes are curated in `scripts/build_corpus.py`)
- Field extraction (data entered from verified sources)

### Future phases will add:
- Automated fetching with Playwright/BeautifulSoup
- LLM-assisted extraction with source verification
- Incremental ingestion with change detection

## CLI Commands

```bash
# Build corpus from seed data
python scripts/build_corpus.py

# Validate existing corpus
python scripts/validate_corpus.py

# Export corpus (with dry-run)
python scripts/export_corpus.py --dry-run
python scripts/export_corpus.py --version 1.1.0
python scripts/export_corpus.py --force  # export even with errors
```

## Validation Rules

### Hard Errors (block validation)
- Missing scheme_id
- Missing name
- Duplicate scheme_id
- No source records
- Invalid URL format
- Invalid eligibility rule operator

### Soft Warnings (reported but don't block)
- Missing eligibility summary
- Missing benefits
- Missing required documents
- Missing application steps
- Missing application URL
- UNKNOWN status
- Only secondary sources
- Possible duplicate flag

## Error Types

| Error Type | When |
|---|---|
| FETCH_ERROR | Source download fails |
| PARSE_ERROR | HTML/PDF parsing fails |
| EXTRACTION_ERROR | Scheme data extraction fails |
| NORMALIZATION_ERROR | Field normalization fails |
| VALIDATION_ERROR | Data quality check fails |
| DUPLICATE_WARNING | Possible duplicate detected |
| CONFLICT_WARNING | Sources disagree on a value |
