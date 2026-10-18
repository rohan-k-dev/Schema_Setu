# SchemeSetu Data Directory

This directory contains the Government Scheme Knowledge Base — the data foundation for SchemeSetu AI.

## Directory Structure

```
data/
├── raw/                    # Raw source material (preserved for reproducibility)
│   └── sources/
│       ├── myscheme/       # MyScheme.gov.in raw data
│       ├── central/        # Central government sources
│       ├── state/          # State government sources
│       └── agriculture/    # Agriculture ministry sources
│
├── extracted/              # Text extracted from raw sources
│   └── documents/          # Extracted text files
│
├── normalized/             # Normalized canonical data
│   └── schemes.json        # Canonical scheme records
│
├── validated/              # Validated and quality-checked corpus
│   ├── schemes.json        # Final validated corpus
│   ├── validation_report.json
│   ├── validation_report.md
│   └── manual_review_queue.json
│
├── snapshots/              # Versioned corpus snapshots
│   └── YYYY-MM-DD/
│       ├── schemes.json
│       └── manifest.json
│
├── evaluation/             # Test data and golden cases
│   └── golden_queries.json
│
└── metadata/               # Corpus metadata
    ├── corpus_manifest.json
    ├── source_registry.json
    └── schema_version.json
```

## Source Policy

1. **Official sources are ALWAYS preferred** (central government > state government > scheme portal > secondary)
2. **No data fabrication** — if a field is unknown, store `null` or `"unknown"`, never invent values
3. **Source text is always preserved** for traceability
4. **LLM-extracted data must be verified** against the actual source

## How to Rebuild the Corpus

```bash
cd Scheme_Setu

# Build from seed data
python scripts/build_corpus.py

# Validate
python scripts/validate_corpus.py

# Export (with dry-run option)
python scripts/export_corpus.py --dry-run
python scripts/export_corpus.py
```

## How to Add a New Scheme

1. Add the scheme data to `scripts/build_corpus.py` with all required fields
2. Include at least one `SourceRecord` with a verifiable URL
3. Run `python scripts/build_corpus.py` to rebuild
4. Run `python scripts/validate_corpus.py` to verify
5. Check `data/validated/validation_report.md` for any issues

## How to Add a New Source

1. Add the source to `data/metadata/source_registry.json`
2. Place raw data files in `data/raw/sources/<source_name>/`
3. Reference the source_id in scheme records

## Schema

See `docs/phase1-corpus-schema.md` for the complete field documentation.

## Versioning

- Every corpus build creates a dated snapshot in `data/snapshots/`
- The `corpus_manifest.json` tracks version, hash, and generation metadata
- Previous snapshots are never overwritten
