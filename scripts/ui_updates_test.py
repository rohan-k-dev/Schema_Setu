"""
UI test of the scheme-update pipeline in a real browser (Playwright) against the
running stack (`docker compose up`). docs/SCHEME_UPDATES.md.

    python scripts/ui_updates_test.py [--base-url http://localhost:3000]

A farmer saves PM-KISAN; a candidate file with a changed eligibility rule is put in
the backend's data/incoming/; the administrator detects it, can't approve the
consequential change without confirming, approves it, publishes; the farmer sees one
"Important" notification. Afterwards restore the original corpus with
`docker compose run --rm init` (the published change is real in the database).
"""

import argparse
import json
import re
import subprocess
import sys
import tempfile
import time
import uuid
from pathlib import Path

import httpx
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
API = "http://localhost:8000"
PASSWORD = "UpdatesUi2468farm"
results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f" — {detail}" if detail and not ok else ""))


def sh(*args):
    return subprocess.run(list(args), cwd=ROOT, capture_output=True, text=True)


def account(tag):
    email = f"{tag}-{uuid.uuid4().hex[:8]}@example.com"
    c = httpx.Client(base_url=API, headers={"Origin": "http://localhost:3000"})
    assert c.post("/auth/register", json={"email": email, "password": PASSWORD}).status_code == 202
    csrf = c.post("/auth/login", json={"email": email, "password": PASSWORD}).json()["csrf_token"]
    return email, c, csrf


def sign_in(page, base, email):
    page.goto(f"{base}/auth")
    page.locator("#email").fill(email)
    page.locator("#password").fill(PASSWORD)
    page.get_by_role("button", name="Sign In").click()
    page.wait_for_url(f"{base}/dashboard", timeout=15000)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base-url", default="http://localhost:3000")
    base = ap.parse_args().base_url.rstrip("/")

    farmer, fc, fcsrf = account("upd-farmer")
    check("farmer saves PM-KISAN", fc.post("/farmers/me/saved-schemes", json={"scheme_id": "PM_KISAN"},
                                           headers={"X-CSRF-Token": fcsrf}).status_code in (200, 201))
    admin, ac, _ = account("upd-admin")
    check("administrator promoted on the server",
          sh("docker", "compose", "exec", "-T", "backend", "python", "../scripts/set_role.py", admin, "ADMIN").returncode == 0)
    acsrf = ac.post("/auth/login", json={"email": admin, "password": PASSWORD}).json()["csrf_token"]
    for b in ac.get("/admin/scheme-changes/batches").json()["items"]:      # leftovers from an earlier run
        if b["status"] == "OPEN":                                          # (their pending changes would dedupe)
            ac.post(f"/admin/scheme-changes/batches/{b['id']}/discard", headers={"X-CSRF-Token": acsrf})

    verified = json.loads((ROOT / "data" / "validated" / "schemes.json").read_text(encoding="utf-8"))
    pmk = next(s for s in verified if s["scheme_id"] == "PM_KISAN")
    pmk["eligibility_rules"].append({"field": "age", "operator": "GTE", "value": 18, "required": True,
                                     "logical_group": "AND"})
    name = f"ui-scrape-{uuid.uuid4().hex[:6]}.json"
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as tmp:
        json.dump(verified, tmp, ensure_ascii=False)
    sh("docker", "compose", "exec", "-T", "backend", "mkdir", "-p", "/srv/data/incoming")
    cp = sh("docker", "compose", "cp", tmp.name, f"backend:/srv/data/incoming/{name}")
    check("candidate file placed in data/incoming/", cp.returncode == 0, cp.stderr)

    with sync_playwright() as p:
        try:
            browser = p.chromium.launch()
        except Exception:
            browser = p.chromium.launch(channel="msedge")
        page = browser.new_page()
        sign_in(page, base, admin)
        page.goto(f"{base}/admin")
        panel = page.locator("section", has=page.get_by_role("heading", name=re.compile("Scheme updates")))
        panel.wait_for(timeout=15000)
        panel.locator("#upd-source").select_option(name)
        panel.get_by_role("button", name="Detect changes").click()
        panel.get_by_role("status").filter(has_text=re.compile(r"1 new change")).wait_for(timeout=15000)
        check("detection finds exactly the one real change", True)
        change = panel.locator("li.adm-change", has_text="Pradhan Mantri Kisan")
        check("the change is marked consequential and pending",
              "consequential" in change.inner_text() and "PENDING" in change.inner_text())
        approve = change.get_by_role("button", name="Approve")
        check("Approve is disabled until it is confirmed with a note", approve.is_disabled())
        change.get_by_placeholder(re.compile("What did you check")).fill("Checked on pmkisan.gov.in today")
        change.get_by_label("I checked this against the official source").check()
        approve.click()
        panel.locator("li.adm-change", has_text="APPROVED").wait_for(timeout=10000)
        check("approved with the reviewer recorded", admin in panel.locator("li.adm-change").first.inner_text())
        panel.get_by_role("button", name=re.compile("Publish approved changes")).click()
        panel.get_by_role("status").filter(has_text="Publishing started").wait_for(timeout=15000)
        row = ""
        for _ in range(60):                                   # the jobs table refreshes on demand
            page.get_by_role("button", name="Refresh").click()
            time.sleep(1)
            jobs = page.locator("tr", has_text="PUBLISH_CHANGES")
            row = jobs.first.inner_text() if jobs.count() else ""
            if "SUCCEEDED" in row or "FAILED" in row:
                break
        check("publishing job succeeded", "SUCCEEDED" in row, row)
        page.close()

        page = browser.new_page()
        sign_in(page, base, farmer)
        notif = page.locator("#notifications")
        notif.get_by_text(re.compile("Pradhan Mantri Kisan.*important update")).wait_for(timeout=15000)
        check("farmer sees one 'Important' notification",
              notif.get_by_text("Important").count() == 1 and "1 new" in notif.inner_text())
        notif.locator("summary").first.click()
        check("the message says it was verified and to re-check eligibility",
              "checked by the SchemeSetu team" in notif.inner_text() and "still qualify" in notif.inner_text())
        page.get_by_role("heading", name=re.compile("Notification settings")).wait_for(timeout=10000)
        check("SMS shows as unavailable without a provider",
              page.get_by_text("SMS isn't available on this server").count() == 1)
        browser.close()

    r = fc.get("/farmers/me/notifications").json()
    check("exactly one notification for the farmer (no duplicates)", r["total"] == 1, str(r["total"]))
    print(f"\n{sum(results)}/{len(results)} scheme-update UI checks passed")
    print("Restore the original corpus in the database: docker compose run --rm init")
    sys.exit(0 if all(results) else 1)


if __name__ == "__main__":
    main()
