"""
Run the query-time official-source check for one question against the REAL network
(docs/LIVE_VERIFICATION.md) and print exactly which sources were searched, fetched or failed,
which fields were verified, and with what timestamps. Nothing here is mocked.

    python scripts/live_check.py "crop insurance" --state Karnataka --crop ragi [--json out.json]
    docker compose exec backend python ../scripts/live_check.py "pm kisan" --state Karnataka

Needs DATABASE_URL (stored schemes) — without it only discovered pages are checked. Tavily
discovery runs only when TAVILY_API_KEY is configured; otherwise the stored official pages of
the top stored schemes are re-checked directly.
"""

import argparse
import asyncio
import json
import os
import sys
import time
from datetime import datetime, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

from app.database.connection import close_db, init_db, use_selector_event_loop_on_windows  # noqa: E402

use_selector_event_loop_on_windows()


async def main(question, state, crop, out):
    from app.core.config import settings
    from app.live.discovery import topic_keywords
    from app.live.service import live_service
    from app.retrieval.db_retriever import search_db
    from app.retrieval.models import RetrievalRequest
    await init_db()
    try:
        req = RetrievalRequest(query=question, contextual_query=question, state=state, crop=crop)
        try:
            db_results = await search_db(req)
        except Exception as exc:
            print(f"(stored schemes unavailable: {type(exc).__name__})")
            db_results = []
        t0, started_at = time.monotonic(), datetime.now(timezone.utc)
        discovery = await live_service.discover(topic_keywords(question), state, crop)
        outcome = await live_service.verify(discovery, db_results, started=t0,
                                            deadline=t0 + settings.LIVE_BUDGET_SECONDS, started_at=started_at,
                                            question=question)
        r = outcome.report
        print(f"\nQuestion: {question!r} state={state} crop={crop}  ({r['duration_ms']} ms)")
        print(f"Discovery: {r['discovery']['status']}")
        for s in r["discovery"]["searches"]:
            print(f"  search[{s['group']}] {s['status']} results={s['results']} official={s['official']} "
                  f"domains={','.join(s['domains'][:4])}")
        print("Sources:")
        for s in r["sources"]:
            print(f"  {s.get('status',''):16} {s.get('http_status') or '-':>4} {s.get('method') or '-':7} {s['url']}")
            if s.get("fields_found"):
                print(f"      fields: {', '.join(s['fields_found'])}   retrieved_at={s.get('retrieved_at')}")
            if s.get("reason"):
                print(f"      reason: {s['reason']}")
        print("Schemes:")
        for sid, f in outcome.freshness.items():
            print(f"  {sid:18} {f['status']:16} {f['label']}")
            if f.get("verified_fields"):
                print(f"      verified now: {', '.join(f['verified_fields'])}")
            for c in f.get("conflicts", []):
                print(f"      CONFLICT {c['field']}: stored={c['stored']} live={c['live']}")
        print("Summary:", r["coverage_note"])
        for w in r["warnings"]:
            print("Warning:", w)
        if out:
            with open(out, "w", encoding="utf-8") as fh:
                json.dump({"report": r, "freshness": outcome.freshness}, fh, ensure_ascii=False, indent=2, default=str)
            print("Saved", out)
    finally:
        await close_db()


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("question")
    ap.add_argument("--state")
    ap.add_argument("--crop")
    ap.add_argument("--json")
    a = ap.parse_args()
    asyncio.run(main(a.question, a.state, a.crop, a.json))
