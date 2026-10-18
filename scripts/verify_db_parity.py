"""
Verify that the real PostgreSQL repositories return the same results as the
offline corpus fixture used by Phase 7 evaluation (and that the batched
`= ANY(%s)` queries work on a real server).

Usage (from Scheme_Setu/, DATABASE_URL set, corpus imported):
    python scripts/verify_db_parity.py

Exit code 0 = every compared query matches.
"""

import asyncio
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import evaluation  # noqa: E402,F401  (backend import path)
from app.database.connection import init_db, close_db, is_db_available  # noqa: E402
from app.database.repositories.scheme_repository import SchemeRepository  # noqa: E402
from app.database.repositories.rule_repository import RuleRepository  # noqa: E402
from evaluation.fixtures.corpus_db import CorpusDB  # noqa: E402
from evaluation.runners.common import load_dataset  # noqa: E402


def _ids(rows):
    # Compared as sets: PostgreSQL's locale collation orders names differently from
    # Python, and the DB retriever re-sorts in Python before truncation anyway.
    return sorted(r.scheme_id for r in rows)


def _rule_key(r):
    return (r.field_name, r.operator, repr(r.value_json), r.logical_group, r.required, r.source_text, r.rule_order)


async def main() -> int:
    await init_db()
    if not is_db_available():
        print("[FAIL] database not available — set DATABASE_URL and import the corpus first")
        return 1
    fx = CorpusDB()
    checks, failures = 0, []

    def compare(name, real, fixture):
        nonlocal checks
        checks += 1
        if real != fixture:
            failures.append((name, real, fixture))

    ds = load_dataset("retrieval_cases.json")
    for case in ds["profile_cases"]:
        p = case["profile"]
        state, crop = p.get("state"), p.get("primary_crop")
        if state and crop:
            compare(f"{case['case_id']} state+crop", _ids(await SchemeRepository.search_by_state_and_crop(state, crop)),
                    _ids(await fx.search_by_state_and_crop(state, crop)))
        if state:
            compare(f"{case['case_id']} state", _ids(await SchemeRepository.search_by_state(state)),
                    _ids(await fx.search_by_state(state)))
        if crop:
            compare(f"{case['case_id']} crop", _ids(await SchemeRepository.search_by_crop(crop)),
                    _ids(await fx.search_by_crop(crop)))
    for q in ("Kisan Credit Card", "Soil Health", "weather forecast in Paris", "'; DROP TABLE schemes; --"):
        compare(f"name '{q}'", _ids(await SchemeRepository.search_by_name(q)),
                _ids(await fx.search_by_name(q)))

    ids = fx.scheme_ids()
    real_d = await SchemeRepository.get_details_for_scheme_ids(ids)
    fx_d = await fx.get_details_for_scheme_ids(ids)
    for sid in ids:
        compare(f"{sid} states", sorted(real_d[sid]["states"]), sorted(fx_d[sid]["states"]))
        compare(f"{sid} crops", sorted(real_d[sid]["crops"]), sorted(fx_d[sid]["crops"]))
        compare(f"{sid} documents", [d.name for d in real_d[sid]["documents"]], [d.name for d in fx_d[sid]["documents"]])
        compare(f"{sid} steps", [s.description for s in real_d[sid]["application_steps"]],
                [s.description for s in fx_d[sid]["application_steps"]])
    real_r = await RuleRepository.list_for_scheme_ids(ids)
    fx_r = await fx.list_for_scheme_ids(ids)
    for sid in ids:
        compare(f"{sid} rules", [_rule_key(r) for r in real_r[sid]], [_rule_key(r) for r in fx_r[sid]])
        compare(f"{sid} rules (single)", [_rule_key(r) for r in await RuleRepository.list_for_scheme_by_sid(sid)],
                [_rule_key(r) for r in fx_r[sid]])
    row = await SchemeRepository.get_by_scheme_id("PM_KISAN")
    compare("PM_KISAN official_url", row.official_url if row else None, fx.official_url("PM_KISAN"))
    await close_db()

    for name, real, fixture in failures[:20]:
        print(f"[DIFF] {name}\n   postgres: {real}\n   fixture:  {fixture}")
    print(f"{checks - len(failures)}/{checks} comparisons identical")
    return 0 if not failures else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
