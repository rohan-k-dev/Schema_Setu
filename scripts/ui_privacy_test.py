"""
UI test of the Privacy and Data Settings page in a real browser (Playwright) against the running
stack (`docker compose up`). docs/PRIVACY.md.

    python scripts/ui_privacy_test.py [--base-url http://localhost:3000]

Signed out: every profile field with required / optional, purpose and external sharing; the
external processors; the deletion exceptions. Signed in: what is stored, a JSON export of your
own data only, deleting saved schemes, withdrawing consent (deleting the profile), and deleting
the account with the password and the typed confirmation — after which the session is gone and
another farmer's data is untouched. Uses 2 sign-ups (5 per IP per hour).
"""

import argparse
import asyncio
import json
import re
import sys
import uuid

import httpx
from playwright.sync_api import sync_playwright

API = "http://localhost:8000"
PASSWORD = "PrivacyUi2468farm"
results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f" - {detail}" if detail and not ok else ""))


def account(tag):
    """An account with a saved profile, a saved scheme and a followed scheme (through the API)."""
    email = f"{tag}-{uuid.uuid4().hex[:8]}@example.com"
    c = httpx.Client(base_url=API, headers={"Origin": "http://localhost:3000"})
    r = c.post("/auth/register", json={"email": email, "password": PASSWORD})
    assert r.status_code == 202, f"register {r.status_code} (sign-up limit? restart the backend)"
    csrf = c.post("/auth/login", json={"email": email, "password": PASSWORD}).json()["csrf_token"]
    h = {"X-CSRF-Token": csrf}
    assert c.put("/farmers/me/profile", json={"state": "Karnataka", "age": 39, "primary_crop": "ragi",
                                              "consent_given": True}, headers=h).status_code == 200
    assert c.post("/farmers/me/saved-schemes", json={"scheme_id": "PM_KISAN"}, headers=h).status_code in (200, 201)
    c.put("/farmers/me/subscriptions/PM_KISAN", headers=h)
    return email, c


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base-url", default="http://localhost:3000")
    base = ap.parse_args().base_url.rstrip("/")
    me, _ = account("pv-me")
    other, other_client = account("pv-other")
    try:
        run_browser(base, me, other, other_client)
    except asyncio.InvalidStateError:
        pass               # Playwright's own teardown after the final redirect; every check has already run
    print(f"\n{sum(results)}/{len(results)} privacy UI checks passed")
    sys.exit(0 if all(results) and len(results) == 12 else 1)


def run_browser(base, me, other, other_client):
    with sync_playwright() as p:
        try:
            browser = p.chromium.launch()
        except Exception:
            browser = p.chromium.launch(channel="msedge")
        page = browser.new_page(accept_downloads=True)

        # ── public part ──
        page.goto(f"{base}/privacy")
        page.get_by_role("heading", name="Farmer profile details").wait_for(timeout=15000)
        table = page.locator("table", has=page.locator("caption", has_text="Farmer profile details"))
        rows = table.locator("tbody tr")
        check("every profile field is listed with required / optional", rows.count() >= 12
              and table.get_by_text("Optional").count() >= 12)
        age = table.locator("tr", has_text="Age").inner_text()
        check("age: why, used for eligibility, not sent from the saved profile",
              "Age limits" in age and "Yes" in age and "not sent from your saved profile" in age)
        state = table.locator("tr", has_text="State").first.inner_text()
        check("state: disclosed as sent to the AI model and web search", "Groq" in state and "Tavily" in state)
        procs = page.locator("table", has=page.locator("caption", has_text="External services")).inner_text()
        check("external processors disclosed (LLM, web search, translation/speech, e-mail, SMS)",
              all(x in procs for x in ("Groq", "Tavily", "Sarvam", "E-mail", "SMS")))
        check("no claim that external processing is local",
              "fully local" not in page.content().lower() and "own terms and retention" in page.content())
        check("deletion exceptions documented", page.get_by_text("Security record (audit log)").count() >= 1)

        # ── signed in ──
        page.goto(f"{base}/auth")
        page.locator("#email").fill(me)
        page.locator("#password").fill(PASSWORD)
        page.get_by_role("button", name="Sign In").click()
        page.wait_for_url(f"{base}/dashboard", timeout=15000)
        page.get_by_role("button", name=re.compile("Privacy")).click()
        page.wait_for_url(f"{base}/privacy", timeout=10000)
        yours = page.locator("#your-data")
        yours.get_by_text("Saved profile").wait_for(timeout=15000)
        text = yours.inner_text()
        check("your data: profile and counts shown", "detail(s) filled" in text and "Saved schemes" in text)

        with page.expect_download(timeout=15000) as dl:
            yours.get_by_role("button", name=re.compile("Download all my data")).click()
        data = json.loads(Path(dl.value.path()).read_text(encoding="utf-8"))
        check("export: my own data, no password hash, nothing of the other farmer",
              data["account"]["email"] == me and data["profile"]["age"] == 39
              and data["saved_schemes"] and "password" not in json.dumps(data["account"])
              and other not in json.dumps(data))

        yours.get_by_role("button", name="Delete saved schemes").click()
        yours.get_by_role("button", name="Yes, delete saved schemes").click()
        page.get_by_text("Your saved schemes were deleted.").wait_for(timeout=10000)
        yours.get_by_role("button", name="Delete profile").click()
        yours.get_by_role("button", name="Yes, delete profile").click()
        page.get_by_text("Your profile and search history were deleted.").wait_for(timeout=10000)
        yours.get_by_text("No profile saved").wait_for(timeout=10000)          # after the panel reloads
        check("withdrawing consent deletes the profile", "No profile saved" in yours.inner_text())

        page.locator("#pv-password").fill(PASSWORD)
        page.locator("#pv-confirm").fill("DELETE MY ACCOUNT")
        page.get_by_role("button", name="Delete my account").click()
        page.wait_for_url(re.compile(r"/privacy\?deleted=1"), timeout=15000)
        page.get_by_text("Your account and its data were deleted").wait_for(timeout=10000)
        status = page.evaluate(f"fetch('{API}/farmers/me/data', {{credentials: 'include'}}).then(r => r.status)")
        check("account deleted and signed out", status == 401, str(status))
        login = httpx.post(f"{API}/auth/login", json={"email": me, "password": PASSWORD},
                           headers={"Origin": "http://localhost:3000"}).status_code
        check("the deleted account can't sign in", login == 401, str(login))
        theirs = other_client.get("/farmers/me/data").json()
        check("the other farmer's data is untouched",
              theirs["has_profile"] and theirs["counts"]["saved_schemes"] == 1)
        try:
            browser.close()
        except Exception:
            pass                           # teardown noise after the final navigation; checks are done


if __name__ == "__main__":
    main()
