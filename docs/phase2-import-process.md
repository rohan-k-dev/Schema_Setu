# Phase 2 — Import Process Documentation

## Prerequisites

1. PostgreSQL database available (Neon or local)
2. `DATABASE_URL` or `NEON_DATABASE_URL` set in `.env`
3. Phase 1 validated corpus exists at `data/validated/schemes.json`
4. Python dependencies installed (`alembic`, `psycopg`, `psycopg_pool`)

## Complete Setup Workflow

```bash
# 1. Run migrations to create tables
cd Scheme_Setu/backend
alembic upgrade head

# 2. Validate corpus (optional but recommended)
cd Scheme_Setu
python scripts/validate_corpus.py

# 3. Import corpus into PostgreSQL
python scripts/import_corpus.py

# 4. Verify database integrity
python scripts/db_check.py

# 5. Start application
cd backend
uvicorn app.main:app --reload
```

## Import Commands

### Full Import
```bash
python scripts/import_corpus.py
```

### Dry Run (no DB changes)
```bash
python scripts/import_corpus.py --dry-run
```

### Force Import (continue on errors)
```bash
python scripts/import_corpus.py --force
```

### Custom Corpus Path
```bash
python scripts/import_corpus.py --corpus /path/to/schemes.json
```

### Production Safety
```bash
# Production requires explicit flag
python scripts/import_corpus.py --allow-production
```

## Import Process

1. **Load** validated corpus from `data/validated/schemes.json`
2. **Load** corpus manifest from `data/metadata/corpus_manifest.json`
3. **Verify** corpus format (scheme_ids present, valid structure)
4. **Begin** PostgreSQL transaction
5. **Create/get** corpus version record
6. **Create** ingestion run record (status=RUNNING)
7. For each scheme:
   - Check if scheme_id exists in DB
   - If exists: UPDATE scheme + DELETE/re-INSERT child records
   - If new: INSERT scheme + INSERT child records
   - Child records: aliases, states, districts, crops, beneficiaries, benefits, rules, documents, steps, sources
8. **Update** ingestion run (status=SUCCESS, counts)
9. **Commit** transaction

## Idempotency

Running the import twice with the same corpus produces the same database state:
- Existing schemes are updated (not duplicated)
- Child records are replaced (delete + re-insert)
- Corpus version is reused if version string matches

## Transaction Safety

- All changes happen in a single transaction
- On error: automatic ROLLBACK — no partial data
- Ingestion run status reflects: SUCCESS, FAILED, or PARTIAL

## Rollback

### Alembic Rollback
```bash
cd backend
alembic downgrade -1    # Roll back one version
alembic downgrade base  # Roll back all migrations
```

### Re-import After Changes
```bash
# 1. Update corpus (rebuild)
python scripts/build_corpus.py

# 2. Validate
python scripts/validate_corpus.py

# 3. Re-import (idempotent)
python scripts/import_corpus.py
```

## Version Upgrade

```bash
# Update corpus to new version
python scripts/build_corpus.py  # with new data

# Import new version
python scripts/import_corpus.py
# → Creates new corpus_version record
# → Updates scheme records
# → Historical corpus version preserved
```

## Troubleshooting

| Issue | Solution |
|---|---|
| "Database not available" | Set DATABASE_URL in .env |
| "Validated corpus not found" | Run `python scripts/build_corpus.py` |
| "Production environment detected" | Use `--allow-production` flag |
| Duplicate scheme_id error | Import is idempotent — safe to re-run |
| Partial import | Transaction rolled back automatically |
| Migration errors | Check `alembic current` and `alembic history` |

## Database Backup

The canonical data source is `data/validated/schemes.json`. The database can be fully reconstructed from:
1. Migration: `alembic upgrade head`
2. Import: `python scripts/import_corpus.py`
3. Corpus snapshots in `data/snapshots/` provide historical versions
