"""
Raise a human-review case from a REAL eligibility result (docs/HUMAN_REVIEW.md) — for demos
and the browser test, without needing the LLM. Picks an active scheme that has no structured
eligibility rules in the database (the engine says UNVERIFIABLE), escalates it exactly as the
chat pipeline would, and optionally links it to an account so that farmer can follow it.

    python scripts/raise_review_case.py [--email farmer@example.com] [--session demo-1]
    docker compose exec backend python ../scripts/raise_review_case.py --email farmer@example.com

Prints the case id. Nothing in the scheme data is changed.
"""

import argparse
import asyncio
import os
import sys
import uuid

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

from app.database.connection import close_db, init_db, is_db_available, use_selector_event_loop_on_windows  # noqa: E402

use_selector_event_loop_on_windows()


async def main(email, session):
    await init_db()
    try:
        if not is_db_available():
            print("Database not connected: set DATABASE_URL.")
            return 2
        from app.database.repositories import auth_repository
        from app.database.repositories.rule_repository import RuleRepository
        from app.database.repositories.scheme_repository import SchemeRepository
        from app.eligibility.evaluator import evaluate_scheme
        from app.services import review_workflow as wf

        schemes = await SchemeRepository.list_active()
        rules = await RuleRepository.list_for_scheme_ids([s.scheme_id for s in schemes])
        scheme = next((s for s in schemes if not rules.get(s.scheme_id)), None)
        if scheme is None:
            print("Every active scheme has rules; nothing would be UNVERIFIABLE.")
            return 1
        profile = {"state": "Karnataka", "occupation": "farmer", "land_size_acres": 2.0}
        result = evaluate_scheme(scheme.scheme_id, scheme.name, [], profile, source_url=scheme.official_url)
        case = await wf.escalate(session or f"demo-{uuid.uuid4().hex[:8]}", f"Am I eligible for {scheme.name}?",
                                 profile, [result],
                                 [{"scheme_id": scheme.scheme_id, "official_url": scheme.official_url}], [], {})
        if email:
            account = await auth_repository.get_farmer_by_email(email.lower())
            if account is None:
                print(f"No account {email}; case created but not linked.")
            else:
                await wf.link_farmer(case["case_id"], account.id)
        print(case["case_id"])
        return 0
    finally:
        await close_db()


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--email")
    ap.add_argument("--session")
    a = ap.parse_args()
    sys.exit(asyncio.run(main(a.email, a.session)))
