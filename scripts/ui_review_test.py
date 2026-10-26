"""
UI test of the reviewer dashboard in a real browser (Playwright) against the running stack
(`docker compose up`). docs/HUMAN_REVIEW.md.

    python scripts/ui_review_test.py [--base-url http://localhost:3000]

A farmer's result is escalated (a real UNVERIFIABLE engine result, raised with
scripts/raise_review_case.py and linked to the farmer); the farmer sees it as "being checked"
and unconfirmed; a farmer can't open /review; a REVIEWER that isn't approved can't either, until
an administrator approves it on /admin; in the queue the case is a summary only (no evidence)
until reviewer 1 takes it; reviewer 1 then sees the evidence, comments, requests verification and
approves it; reviewer 2, acting on a stale view, is refused and never sees the case; the farmer
then sees the outcome. Uses 4 sign-ups (5 per IP per hour).
"""

import argparse
import re
import subprocess
import sys
import uuid
from pathlib import Path

import httpx
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
API = "http://localhost:8000"
PASSWORD = "ReviewUi2468farm"
results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f" — {detail}" if detail and not ok else ""))


def sh(*args):
    return subprocess.run(list(args), cwd=ROOT, capture_output=True, text=True)


def account(tag, role=None, approve=False):
    email = f"{tag}-{uuid.uuid4().hex[:8]}@example.com"
    c = httpx.Client(base_url=API, headers={"Origin": "http://localhost:3000"})
    r = c.post("/auth/register", json={"email": email, "password": PASSWORD})
    assert r.status_code == 202, f"register {r.status_code} (sign-up limit? restart the backend)"
    token = re.findall(r"verify-email\?token=([A-Za-z0-9_-]+)",
                       sh("docker", "compose", "logs", "backend", "--since", "2m").stdout)[-1]
    assert c.post("/auth/verify-email", json={"token": token}).status_code == 200
    if role:
        assert sh("docker", "compose", "exec", "-T", "backend", "python", "../scripts/set_role.py",
                  email, role, *(["--approve"] if approve else [])).returncode == 0
    return email


def sign_in(browser, base, email):
    page = browser.new_page()
    page.goto(f"{base}/auth")
    page.locator("#email").fill(email)
    page.locator("#password").fill(PASSWORD)
    page.get_by_role("button", name="Sign In").click()
    page.wait_for_url(f"{base}/dashboard", timeout=15000)
    return page


def find_in_queue(page, case_id):
    """The case's queue button, paging forward (oldest first: a new case may be on a later page)."""
    item = page.locator("button.rv-case", has_text=case_id)
    page.locator("button.rv-case").first.wait_for(timeout=15000)
    nxt = page.get_by_role("button", name="Next →")
    while not item.count() and nxt.count() and nxt.is_enabled():
        nxt.click()
        page.wait_for_timeout(800)
    item.wait_for(timeout=15000)
    return item


def open_queue_item(page, base, case_id):
    """Select a pending case in the queue: a summary card (no evidence) with "Take this case"."""
    page.goto(f"{base}/review")
    page.get_by_role("tab", name=re.compile("^Pending")).wait_for(timeout=15000)
    item = find_in_queue(page, case_id)
    item.click()
    page.locator("#queue-title").wait_for(timeout=10000)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base-url", default="http://localhost:3000")
    base = ap.parse_args().base_url.rstrip("/")

    farmer = account("rv-farmer")
    rev1, rev2 = account("rv-one", "REVIEWER"), account("rv-two", "REVIEWER", approve=True)
    admin = account("rv-admin", "ADMIN")
    out = sh("docker", "compose", "exec", "-T", "backend", "python", "../scripts/raise_review_case.py",
             "--email", farmer)
    case_id = out.stdout.strip().splitlines()[-1] if out.returncode == 0 else ""
    check("a real UNVERIFIABLE result is escalated and linked to the farmer", bool(case_id), out.stderr[-300:])

    with sync_playwright() as p:
        try:
            browser = p.chromium.launch()
        except Exception:
            browser = p.chromium.launch(channel="msedge")

        # ── farmer: unresolved case clearly communicated ──
        fp = sign_in(browser, base, farmer)
        panel = fp.locator("#review-status")
        panel.wait_for(timeout=15000)
        text = panel.inner_text()
        check("farmer sees the open check, marked unconfirmed",
              "Being checked" in text and "unconfirmed" in text and case_id in text)
        scheme_name = panel.locator(".rs-head strong").first.inner_text()
        fp.goto(f"{base}/review")
        fp.get_by_text("Reviewer access required").wait_for(timeout=15000)
        check("a farmer can't open the review queue", True)

        # ── reviewer 1 has the REVIEWER role but isn't approved yet ──
        p1 = sign_in(browser, base, rev1)
        p1.goto(f"{base}/review")
        p1.get_by_text("Reviewer access required").wait_for(timeout=15000)
        check("an unapproved reviewer can't open the review queue", True)

        # ── an administrator approves reviewer 1 on /admin ──
        pa = sign_in(browser, base, admin)
        pa.goto(f"{base}/admin")
        reviewers = pa.locator("section[aria-labelledby=reviewers-title]")
        row = reviewers.locator("tr", has_text=rev1)
        row.wait_for(timeout=15000)
        row.get_by_role("button", name=re.compile("^Approve")).click()
        pa.get_by_text("can now work review cases").wait_for(timeout=10000)
        check("administrator approves the reviewer (audited)", "Approved" in reviewers.locator("tr", has_text=rev1).inner_text())

        # ── reviewer 2 selects the case first (this view will go stale) ──
        p2 = sign_in(browser, base, rev2)
        open_queue_item(p2, base, case_id)
        card = p2.locator("section[aria-labelledby=queue-title]").inner_text()
        check("queue shows a summary only: no question, profile or evidence",
              scheme_name in card and "Am I eligible" not in card and "Karnataka" not in card)

        # ── reviewer 1 works the case ──
        p1.goto(f"{base}/dashboard")
        p1.get_by_role("button", name=re.compile("Review queue")).click()
        p1.wait_for_url(f"{base}/review", timeout=10000)
        p1.locator("#rv-reason").select_option("UNVERIFIABLE")
        p1.wait_for_timeout(800)
        find_in_queue(p1, case_id)
        check("queue filtered by reason shows the case", True)
        open_queue_item(p1, base, case_id)
        p1.locator("section[aria-labelledby=queue-title]").get_by_role("button", name="Take this case").click()
        p1.locator("#case-title").wait_for(timeout=10000)
        detail = p1.locator("section[aria-labelledby=case-title]")
        dtext = detail.inner_text()
        check("after taking it: scheme, reason, official link, minimal profile, assigned to them",
              scheme_name in dtext and "couldn't be verified automatically" in dtext
              and detail.get_by_role("link", name=re.compile("Official website")).count() >= 1
              and "state" in dtext.lower() and "(you)" in dtext and "farmer@" not in dtext)
        p1.locator("#rv-comment").fill("Checking the scheme guidelines PDF")
        detail.get_by_role("button", name="Add comment").click()
        p1.get_by_text("Comment added.").wait_for(timeout=10000)
        detail.get_by_label(re.compile("Request additional verification")).check()
        p1.locator("#rv-note").fill("Asked the district agriculture office to confirm")
        detail.get_by_role("button", name="Save").click()
        p1.get_by_text("Additional verification requested.").wait_for(timeout=10000)
        try:
            detail.get_by_text("Awaiting additional verification").first.wait_for(timeout=10000)
            awaiting = True
        except Exception:
            awaiting = False
        check("verification requested, case stays in review", awaiting, detail.inner_text()[:600])

        # ── reviewer 2 acts on the stale view: refused, and the case is no longer visible to them ──
        p2.locator("section[aria-labelledby=queue-title]").get_by_role("button", name="Take this case").click()
        warn = p2.locator(".rv-warn")
        warn.wait_for(timeout=10000)
        check("a second reviewer acting on a stale view is refused",
              "Someone else has just taken this case" in warn.inner_text())
        status = p2.evaluate(f"fetch('{API}/review-cases/{case_id}', {{credentials: 'include'}}).then(r => r.status)")
        check("the other reviewer's case doesn't exist for them (direct API call -> 404)", status == 404, str(status))

        detail.get_by_label(re.compile("^Approve")).check()
        p1.locator("#rv-note").fill("District office confirmed the published criteria")
        detail.get_by_role("button", name="Save").click()
        p1.get_by_text("Decision saved.").wait_for(timeout=10000)
        hist = detail.locator(".rv-history").inner_text()
        check("decision recorded with full history",
              all(s in hist for s in ("Case opened", "Assigned", "Comment", "Additional verification requested",
                                      "Approved")) and "RESOLVED" in detail.inner_text().upper())
        p1.get_by_role("tab", name=re.compile("^Resolved")).click()
        p1.locator("button.rv-case", has_text=case_id).wait_for(timeout=10000)
        check("resolved filter lists the case", True)

        # ── farmer sees the outcome, without reviewer details ──
        fp.goto(f"{base}/dashboard")
        panel = fp.locator("#review-status")
        panel.get_by_text("confirmed the result").wait_for(timeout=15000)
        ptext = panel.inner_text()
        check("farmer sees the outcome, no reviewer name or notes",
              "Checked" in ptext and rev1 not in ptext and "District office" not in ptext)
        browser.close()

    print(f"\n{sum(results)}/{len(results)} review UI checks passed")
    sys.exit(0 if all(results) else 1)


if __name__ == "__main__":
    main()
