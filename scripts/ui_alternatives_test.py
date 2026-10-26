"""
UI test of "Eligible Schemes" + "More Relevant Schemes & Alternatives" (docs/RECOMMENDATIONS.md) in a
real browser (Playwright) against the running stack (`docker compose up`).

    python scripts/ui_alternatives_test.py [--base-url http://localhost:3000]

Step 1 runs the REAL scheme pipeline (retrieval → eligibility → recommendation → response) inside the
backend container against the real PostgreSQL corpus for a dairy farmer in Telangana. Step 2 serves that
result as the /chat reply in the browser — only the language-model wording step is bypassed (it needs a
Groq key) — and checks: eligible schemes first and only those; the alternatives section with reasons and
"not confirmed"; missing information vs known mismatch shown differently; links and verification dates;
no scheme in two sections; "Show more" paging; the collapsed not-matching group; and the empty state.
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
QUESTION = "dairy cattle support"
PROFILE = {"state": "Telangana", "occupation": "dairy farmer", "age": 30, "land_size_acres": 3.0}
results = []

PIPELINE = r'''
import asyncio, json, sys
from app.database.connection import close_db, init_db
async def main():
    await init_db()
    try:
        from app.agents.retrieval_agent import retrieval_agent_node
        from app.agents.eligibility_agent import eligibility_agent
        from app.agents.recommendation_agent import recommendation_agent
        from app.agents.response_formatter import response_formatter_node
        from app.utils.serialization import build_chat_response
        state = {"profile": json.loads(sys.argv[2]), "original_query": sys.argv[1], "contextual_query": sys.argv[1],
                 "query_intent": "scheme_search", "session_id": "ui-alternatives-test"}
        for node in (retrieval_agent_node, eligibility_agent, recommendation_agent, response_formatter_node):
            state.update(await node(state))
        body = build_chat_response({**state, "messages": []})
        body["_engine"] = {r.scheme_id: r.status.value for r in state["eligibility_results"]}
        print("@@" + json.dumps(body, default=str))
    finally:
        await close_db()
asyncio.run(main())
'''


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f" - {detail}" if detail and not ok else ""))


def real_pipeline():
    env = {**os.environ, "MSYS_NO_PATHCONV": "1"}
    with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False) as f:
        f.write(PIPELINE)
    subprocess.run(["docker", "compose", "cp", f.name, "backend:/tmp/ui_alt_pipeline.py"], cwd=ROOT, env=env,
                   check=True, capture_output=True)
    os.unlink(f.name)
    out = subprocess.run(["docker", "compose", "exec", "-T", "-e", "PYTHONPATH=/srv/backend", "-e",
                          "LIVE_VERIFICATION_ENABLED=false", "-w", "/srv/backend", "backend", "python",
                          "/tmp/ui_alt_pipeline.py", QUESTION, json.dumps(PROFILE)], cwd=ROOT, env=env,
                         capture_output=True, text=True, timeout=180).stdout
    return json.loads(next(l for l in out.splitlines() if l.startswith("@@"))[2:])


def serve(page, body):
    page.unroute("**/chat")
    page.route("**/chat", lambda route: route.fulfill(status=200, content_type="application/json",
                                                     body=json.dumps(body)))


def ask(page, base):
    page.goto(base, wait_until="networkidle")
    page.get_by_label("Type your message").fill(QUESTION)
    page.get_by_label("Send message").click()


def main(base):
    body = real_pipeline()
    engine = body.pop("_engine")
    schemes = body["schemes"]
    eligible = [s for s in schemes if s["recommendation_section"] == "ELIGIBLE"]
    alts = [s for s in schemes if s["recommendation_section"] == "ALTERNATIVE"]
    nm = [s for s in schemes if s["recommendation_section"] == "NOT_MATCHING"]
    print(f"  real pipeline: {len(engine)} evaluated, {len(eligible)} eligible, {len(alts)} alternatives, "
          f"{len(nm)} not matching")
    check("section A = engine's ELIGIBLE set",
          {s["scheme_id"] for s in eligible} == {k for k, v in engine.items() if v == "ELIGIBLE"} -
          {"PMKISAN_MAN_DHAN"})
    check("enough alternatives to page", len(alts) > 5, str(len(alts)))

    with sync_playwright() as p:
        try:
            browser = p.chromium.launch()
        except Exception:
            browser = p.chromium.launch(channel="msedge")
        page = browser.new_page()
        serve(page, body)
        ask(page, base)
        page.wait_for_selector("[data-testid=alternatives-section]", timeout=15000)

        heading = page.get_by_role("heading", name=f"Eligible Schemes ({len(eligible)})")
        check("eligible heading with count", heading.count() == 1)
        alt_head = page.get_by_role("heading", name=f"More Relevant Schemes & Alternatives ({len(alts)})")
        check("alternatives heading with count", alt_head.count() == 1)
        eligible_cards = page.locator("[role=article][aria-label^='Scheme: ']")
        check("eligible cards shown first and only eligible ones", eligible_cards.count() == len(eligible))
        first_alt_y = page.locator("[data-testid=alternative]").first.bounding_box()["y"]
        last_elig_y = eligible_cards.last.bounding_box()["y"] if eligible else 0
        check("eligible section above alternatives", last_elig_y < first_alt_y)
        check("'not confirmed' explained", "eligibility for these is not confirmed" in
              page.locator("[data-testid=alternatives-section]").inner_text().lower())

        cards = page.locator("[data-testid=alternatives-section] > div > [data-testid=alternative]")
        check("first page shows 5 alternatives", cards.count() == 5, str(cards.count()))
        first = cards.first.inner_text()
        check("top alternative is the stated need (livestock)", "National Livestock Mission" in first, first[:200])
        check("reason shown", "Why it may be relevant" in first and "livestock and dairy" in first)
        check("official source link", cards.first.get_by_role("link", name="Official source").count() == 1)
        check("verification date shown", "Last verified" in first or "Verification date not recorded" in first)
        texts = [cards.nth(i).inner_text() for i in range(cards.count())]
        check("no alternative claims eligibility", not any("Matches criteria" in t for t in texts))

        page.get_by_role("button", name="Show more").click()
        check("Show more adds up to 5", cards.count() == min(10, len(alts)), str(cards.count()))
        while page.get_by_role("button", name="Show more").count():
            page.get_by_role("button", name="Show more").click()
        check("all alternatives reachable", cards.count() == len(alts), f"{cards.count()} vs {len(alts)}")

        statuses = {cards.nth(i).get_attribute("data-status") for i in range(cards.count())}
        if "ADDITIONAL_INFORMATION_REQUIRED" in statuses:
            info = page.locator("[data-testid=alternative][data-status=ADDITIONAL_INFORMATION_REQUIRED]").first.inner_text()
            check("missing information shown as 'more information needed'",
                  "more information needed" in info and "Still to check" in info, info[:200])
        if "KNOWN_MISMATCH" in statuses:
            mm = page.locator("[data-testid=alternatives-section] [data-status=KNOWN_MISMATCH]").first.inner_text()
            check("known mismatch shown differently, with the reason",
                  "Doesn't match a published criterion" in mm and "Why it doesn't match now" in mm, mm[:200])

        names = [n.lower() for n in page.locator("[role=article] h3, [role=article] h4").all_inner_texts()]
        check("no scheme shown twice", len(names) == len(set(names)), str(names))

        if nm:
            check("not-matching group collapsed", page.locator("[data-testid=not-matching]").count() == 0)
            page.get_by_role("button", name=f"Show schemes that don't match your details ({len(nm)})").click()
            check("not-matching group expands", page.locator("[data-testid=not-matching] [data-testid=alternative]")
                  .count() == len(nm))

        page.set_viewport_size({"width": 390, "height": 900})
        check("no horizontal scroll at phone width",
              not page.evaluate("document.documentElement.scrollWidth > window.innerWidth + 1"))
        page.screenshot(path=str(ROOT / "evaluation" / "results" / "ui_alternatives.png"), full_page=True)

        # Empty state: the same real reply with its alternatives removed (rendering check only)
        page.set_viewport_size({"width": 1280, "height": 900})
        serve(page, {**body, "schemes": eligible})
        ask(page, base)
        page.wait_for_selector("[data-testid=alternatives-empty]", timeout=15000)
        check("empty state for no alternatives", "No other related schemes" in
              page.locator("[data-testid=alternatives-empty]").inner_text())
        browser.close()
    print(f"\n{sum(results)}/{len(results)} passed")
    return all(results)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--base-url", default="http://localhost:3000")
    sys.exit(0 if main(ap.parse_args().base_url) else 1)
