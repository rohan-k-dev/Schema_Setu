"""
Detect scheme changes from a candidate file (docs/SCHEME_UPDATES.md) — for a scraper
or a scheduled task. The scraper writes its normalised output to data/incoming/<name>.json
(the CanonicalScheme format of data/validated/schemes.json), then runs:

  python scripts/detect_scheme_changes.py scrape-2026-10-26.json
  docker compose exec backend python ../scripts/detect_scheme_changes.py scrape-2026-10-26.json

This only DETECTS: changes are stored PENDING for an administrator to verify on the
/admin page. Nothing is published and nobody is notified from here. Audited as
"cli:detect". Exit code 0 = detected (see the counts), 1 = refused.
"""

import argparse
import asyncio
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

from app.core.permissions import Permission, Principal  # noqa: E402
from app.database.connection import close_db, init_db, is_db_available, use_selector_event_loop_on_windows  # noqa: E402
from app.services import scheme_update_service as svc  # noqa: E402

use_selector_event_loop_on_windows()


async def main(source: str) -> int:
    await init_db()
    try:
        if not is_db_available():
            print("Database not connected: set DATABASE_URL.")
            return 2
        actor = Principal(role=None, label="cli:detect", via="cli",
                          permissions=frozenset({Permission.SCHEME_CHANGES_REVIEW}))
        try:
            out = await svc.detect(actor, source)
        except svc.UpdateRejected as exc:
            print(f"Refused: {exc.message}")
            return 1
        print(json.dumps(out, indent=2, ensure_ascii=False))
        print("\nReview the changes on /admin (Scheme updates) before anything is published.")
        return 0
    finally:
        await close_db()


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("source", help="file name in data/incoming/")
    sys.exit(asyncio.run(main(ap.parse_args().source)))
