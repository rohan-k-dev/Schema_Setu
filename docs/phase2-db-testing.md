# Phase 2 — Database Testing Documentation

## Test Strategy

Phase 2 uses a **layered testing approach**:

### 1. Unit Tests (No DB Required)
- Domain model validation (`SchemeRow`, `EligibilityRuleRow`, etc.)
- Import utility functions (`ImportStats`, `load_corpus`, dry-run)
- Migration file validation (valid Python, has upgrade/downgrade)
- Repository row-to-model mapping
- Legacy adapter format

**Run:** `pytest app/tests/test_database.py -v`

### 2. Database Integration Tests (Requires PostgreSQL)
- Migration: `alembic upgrade head` / `alembic downgrade base`
- Import: Full corpus import with statistics
- Idempotency: Import twice → same row count
- Rollback: Invalid data → transaction rolled back
- Foreign keys: Insert child for nonexistent scheme → rejected
- Unique constraints: Duplicate scheme_id → handled via upsert

**Run manually:**
```bash
# Set test database URL
export DATABASE_URL=postgresql://user:pass@localhost/schemesetu_test

# Run migrations
cd backend && alembic upgrade head

# Import test corpus
python scripts/import_corpus.py --corpus app/tests/fixtures/database/test_corpus.json

# Verify
python scripts/db_check.py
```

### 3. Application Tests (No DB Required)
- All Phase 1 tests continue to pass
- Health endpoint returns structured response
- Scheme API returns data (falls back to corpus loader)

**Run:** `pytest app/tests/ -v`

## Test Fixtures

Located in `app/tests/fixtures/database/`:

| File | Schemes | Purpose |
|---|---|---|
| `test_corpus.json` | 5 | Full integration testing |

Fixture schemes:
1. **TEST_SCHEME_001**: Central, all-India, LTE rule
2. **TEST_SCHEME_002**: Karnataka-specific, crop-specific, EQ rule
3. **TEST_SCHEME_003**: Crop insurance, central
4. **TEST_SCHEME_004**: OR logic eligibility rules
5. **TEST_SCHEME_005**: UNKNOWN operator, secondary source

## Running the Full Test Suite

```bash
cd Scheme_Setu/backend
pytest app/tests/ -v --tb=short
```

Current results: **144 passed, 4 skipped**

## CI/CD Considerations

- Unit tests run without any database
- Integration tests require a PostgreSQL instance
- Use `DATABASE_URL` environment variable to control which DB
- Never run tests against production database
