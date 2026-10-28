"""
UI test of the live-verification display (docs/LIVE_VERIFICATION.md) in a real browser (Playwright)
against the running stack (`docker compose up`).

    python scripts/ui_live_check_test.py [--base-url http://localhost:3000]

Step 1 runs the REAL retrieval step inside the backend container (live verification on, real
network, real database) for one question and keeps its live_check report and per-scheme freshness.
Step 2 serves that real result as the /chat reply in the browser — only the language-model step is
bypassed (it needs a Groq key) — and checks what the farmer sees: a "Verified live" badge only on
schemes actually read live, with the official source link and retrieval time; "stored" labels with
the reason on the others; the summary of sources read / not readable; the coverage note and warnings.
"""

import argparse
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
QUESTION = "agriculture infrastructure fund loan for warehouse storage"
results = []

AGENT = r'''
import asyncio, json, sys
from app.database.connection import close_db, init_db
async def main():
    await init_db()
    try:
        from app.agents.retrieval_agent import retrieval_agent_node
        out = await retrieval_agent_node({"profile": {"state": "Maharashtra"}, "query_intent": "scheme_search",
                                          "contextual_query": sys.argv[1], "user_message": sys.argv[1]})
        schemes = [{"scheme_id": c.get("scheme_id"), "name": c.get("name") or c.get("scheme_id"),
                    "official_url": c.get("official_url"), "eligibility_status": "UNVERIFIABLE",
                    "freshness": c.get("freshness")} for c in out.get("merged_candidates", [])[:5]]
        print("@@" + json.dumps({"live_check": out.get("live_check"), "schemes": schemes}, default=str))
    finally:
        await close_db()
asyncio.run(main())
'''


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f" - {detail}" if detail and not ok else ""))


def real_retrieval():
    env = {**os.environ, "MSYS_NO_PATHCONV": "1"}
    with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False) as f:
        f.write(AGENT)
    subprocess.run(["docker", "compose", "cp", f.name, "backend:/tmp/ui_live_agent.py"], cwd=ROOT, env=env,
                   check=True, capture_output=True)
    os.unlink(f.name)
    out = subprocess.run(["docker", "compose", "exec", "-T", "-e", "PYTHONPATH=/srv/backend", "-w", "/srv/backend",
                          "backend", "python", "/tmp/ui_live_agent.py", QUESTION], cwd=ROOT, env=env,
                         capture_output=True, text=True, timeout=120).stdout
    line = next(l for l in out.splitlines() if l.startswith("@@"))
    return json.loads(line[2:])


def main(base):
    data = real_retrieval()
    lc, schemes = data["live_check"], data["schemes"]
    live = [s for s in schemes if (s.get("freshness") or {}).get("status") == "LIVE_VERIFIED"]
    stored = [s for s in schemes if (s.get("freshness") or {}).get("status") != "LIVE_VERIFIED"]
    check("real retrieval ran a live check", lc and lc.get("performed"), str(lc)[:200])
    print(f"  real run: {lc.get('sources_accessed')} read, {lc.get('sources_failed')} not readable, "
          f"hosts {lc.get('hosts_accessed')}, live-verified: {[s['scheme_id'] for s in live]}")
    reply = {"status": "schemes_found", "reply": "Here are schemes (served from a real retrieval run).",
             "schemes": schemes, "live_check": lc, "request_id": "ui-live-test"}

    with sync_playwright() as p:
        try:
            browser = p.chromium.launch()
        except Exception:
            browser = p.chromium.launch(channel="msedge")
        page = browser.new_page()
        page.route("**/chat", lambda route: route.fulfill(status=200, content_type="application/json",
                                                         body=json.dumps(reply)))
        page.goto(base, wait_until="networkidle")
        page.get_by_label("Type your message").fill(QUESTION)
        page.get_by_label("Send message").click()
        page.wait_for_selector("[data-testid=live-check]", timeout=15000)

        summary = page.locator("[data-testid=live-check]").inner_text()
        check("summary counts sources read", f"{lc['sources_accessed']} read" in summary, summary)
        check("summary counts sources not readable", lc["sources_failed"] == 0 or "not readable" in summary, summary)
        check("coverage note says other sites weren't checked", "were not checked" in summary, summary)
        for w in lc["warnings"]:
            check(f"warning shown: {w[:40]}…", w in summary, summary)

        badges = page.locator("[data-testid=freshness] [data-status]")
        statuses = [badges.nth(i).get_attribute("data-status") for i in range(badges.count())]
        check("every scheme card has a freshness label", len(statuses) == len(schemes), str(statuses))
        check("'Verified live' only where the real run verified live",
              statuses.count("LIVE_VERIFIED") == len(live), str(statuses))
        cards = page.locator("[data-testid=freshness]")
        for i, s in enumerate(schemes):
            text = cards.nth(i).inner_text()
            f = s["freshness"]
            if f["status"] == "LIVE_VERIFIED":
                check(f"{s['scheme_id']}: badge says verified live", "Verified live" in text, text)
                cards.nth(i).get_by_role("button", name="Sources and checks").click()
                text = cards.nth(i).inner_text()
                src = f["sources"][0]
                href = cards.nth(i).locator("a").first.get_attribute("href")
                check(f"{s['scheme_id']}: official source link", href == src["url"], f"{href} vs {src['url']}")
                check(f"{s['scheme_id']}: retrieval time shown", "retrieved" in text, text)
                check(f"{s['scheme_id']}: fields verified listed", "Found on the official page now" in text, text)
            else:
                check(f"{s['scheme_id']}: not shown as live", "Verified live" not in text, text)
                check(f"{s['scheme_id']}: says stored / not checked", "stored" in text.lower(), text)

        if lc["sources_failed"]:
            page.get_by_role("button", name="Which sources couldn't be read?").click()
            failed_text = page.locator("[data-testid=live-check]").inner_text()
            check("unreadable sources listed with reasons", "not read" in failed_text, failed_text)
        page.set_viewport_size({"width": 390, "height": 900})
        overflow = page.evaluate("document.documentElement.scrollWidth > window.innerWidth + 1")
        check("no horizontal scroll at phone width", not overflow)
        page.screenshot(path=str(ROOT / "evaluation" / "results" / "ui_live_check.png"), full_page=True)
        browser.close()
    print(f"\n{sum(results)}/{len(results)} passed")
    return all(results)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--base-url", default="http://localhost:3000")
    sys.exit(0 if main(ap.parse_args().base_url) else 1)
