"""
UI test of the account flows in a real browser (Playwright, headless Chromium),
against the running local stack (`docker compose up`).

    python scripts/ui_auth_test.py [--base-url http://localhost:3000]

Covers: register → refused before verification → verify link → sign in (cookie is
HttpOnly: not visible to JavaScript, nothing in localStorage) → session survives a
reload → change password → sign out (server session ends) → forgot password →
reset link → old password rejected, new accepted → reused reset link rejected.
Also the profile page (land units, 409 on stale edits) and the dashboard
(eligibility tabs, fixing a missing detail, stale-result notice, deleting and
clearing search history, saving a scheme and its user-reported checklist).

Without SMTP the backend writes e-mails to its log; links are read from
`docker compose logs backend`. Exit code 0 = all checks passed.
"""

import argparse
import re
import subprocess
import sys
import time
import uuid
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
API = "http://localhost:8000"
results = []


def check(name, ok, detail=""):
    results.append(ok)
    print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f" — {detail}" if detail and not ok else ""))


def latest_link(kind: str, since: str) -> str:
    out = subprocess.run(["docker", "compose", "logs", "backend", "--since", since],
                         cwd=ROOT, capture_output=True, text=True).stdout
    links = re.findall(rf"http://localhost:3000/{kind}\?token=[A-Za-z0-9_-]+", out)
    if not links:
        raise SystemExit(f"no {kind} link found in backend log (is SMTP configured?)")
    return links[-1]


def wait_text(page, text, timeout=8000):
    page.get_by_text(text, exact=False).first.wait_for(timeout=timeout)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base-url", default="http://localhost:3000")
    base = ap.parse_args().base_url.rstrip("/")
    email = f"ui-{uuid.uuid4().hex[:8]}@example.com"
    pw1, pw2, pw3 = "UiFirst4321farm", "UiSecond8765farm", "UiThird2468farm"

    with sync_playwright() as p:
        try:
            browser = p.chromium.launch()
        except Exception:
            # Windows Smart App Control can block Playwright's downloaded Chromium;
            # the system Microsoft Edge (same engine, signed) works instead.
            browser = p.chromium.launch(channel="msedge")
        page = browser.new_page()

        page.goto(f"{base}/auth")
        page.get_by_role("tab", name="Create Account").click()
        page.locator("#email").fill(email)
        page.locator("#password").fill(pw1)
        page.locator("#confirmPassword").fill(pw1)
        page.get_by_role("button", name="Create Account").click()
        wait_text(page, "verification link")
        check("register shows generic 'check your e-mail' message", True)

        page.locator("#password").fill(pw1)
        page.get_by_role("button", name="Sign In").click()
        wait_text(page, "verify your e-mail")
        check("sign-in refused before e-mail verification", page.url.endswith("/auth"))

        page.goto(latest_link("verify-email", "2m"))
        wait_text(page, "Your e-mail is verified")
        check("verification link accepted and removed from address bar", "token=" not in page.url)

        page.goto(f"{base}/auth")
        page.locator("#email").fill(email)
        page.locator("#password").fill(pw1)
        page.get_by_role("button", name="Sign In").click()
        page.wait_for_url(f"{base}/dashboard", timeout=10000)
        check("sign-in lands on dashboard", True)
        check("session cookie not readable by JavaScript", page.evaluate("document.cookie") == "")
        check("no tokens in localStorage", page.evaluate("Object.keys(localStorage).length") == 0)
        cookie = next(c for c in page.context.cookies() if c["name"] == "ss_session")
        check("cookie is HttpOnly and SameSite=Lax", cookie["httpOnly"] and cookie["sameSite"] == "Lax")

        page.reload()
        wait_text(page, "Namaste")
        check("session survives a page reload", page.url.endswith("/dashboard"))

        # ── profile module: save with a land unit, unknowns stay unknown, stale edit → 409 ──
        page.goto(f"{base}/profile")
        page.locator("#state").select_option("Karnataka")
        page.locator("#land_size").fill("40")
        page.locator("#land_unit").select_option("guntha")
        page.locator("#primary_crop").select_option("ragi")
        page.locator("#occupation").select_option("farmer")
        page.locator("#residence").select_option("rural")
        page.locator("#consent_given").check()
        page.get_by_role("button", name="Save Profile").click()
        wait_text(page, "Profile saved")
        prof = page.evaluate(f"fetch('{API}/farmers/me/profile', {{credentials: 'include'}}).then(r => r.json())")
        check("profile saved: 40 guntha stored as 1 acre for the engine",
              prof["land_size"] == 40 and prof["land_unit"] == "guntha" and prof["land_size_acres"] == 1)
        check("fields left empty stay unknown (null), Aadhaar not collected",
              prof["age"] is None and prof["gender"] is None and "has_aadhaar" not in prof)
        page.evaluate("""async ([api]) => {
            const s = await fetch(api + '/auth/session', {credentials: 'include'}).then(r => r.json());
            await fetch(api + '/farmers/me/profile', {method: 'PUT', credentials: 'include',
              headers: {'Content-Type': 'application/json', 'X-CSRF-Token': s.csrf_token},
              body: JSON.stringify({district: 'Hassan'})});
        }""", [API])                                              # edit from "another device"
        page.locator("#age").fill("35")
        page.get_by_role("button", name="Save Profile").click()
        wait_text(page, "changed somewhere else")
        check("stale profile edit is refused (409) instead of overwriting", True)
        page.get_by_role("button", name="Reload latest profile").click()
        check("reload shows the other device's change",
              page.locator("#district").input_value() == "Hassan")

        # ── dashboard: eligibility from the saved profile, fix a missing detail, stale notice ──
        def eligibility():
            return page.evaluate(f"fetch('{API}/farmers/me/eligibility?page_size=50', "
                                 "{credentials: 'include'}).then(r => r.json())")

        page.goto(f"{base}/dashboard")
        wait_text(page, "Your Scheme Eligibility")
        page.locator(".elig-item").first.wait_for(timeout=15000)
        before = eligibility()
        eligible_tab = page.get_by_role("tab", name=re.compile(r"^Eligible \d+"))
        check("eligibility tabs show the engine's counts",
              eligible_tab.inner_text().split()[-1] == str(before["counts"]["ELIGIBLE"])
              and sum(before["counts"].values()) == before["basis"]["scheme_count"])
        page.get_by_role("tab", name=re.compile(r"^Not eligible")).click()
        page.wait_for_function("document.querySelector('[role=tab][aria-selected=true]')"
                               ".textContent.startsWith('Not eligible')")
        # the previous list stays on screen (aria-busy) until the filtered one arrives
        page.locator("#elig-results[aria-busy=false]").wait_for(timeout=10000)
        badges = page.locator(".elig-item .elig-badge").all_inner_texts()
        check("status filter shows only that status", all(b == "Not eligible" for b in badges))

        page.get_by_role("tab", name=re.compile(r"^All")).click()
        page.locator("#fix-age").fill("30")
        page.locator(".fix-item", has=page.locator("#fix-age")).get_by_role(
            "button", name="Save & recheck").click()
        wait_text(page, "Age saved")
        after = eligibility()
        check("fixing a missing detail saves it and recalculates eligibility",
              after["basis"]["profile_version"] == before["basis"]["profile_version"] + 1
              and "age" not in {m["field"] for m in after["missing_details"]}
              and after["counts"] != before["counts"])

        page.evaluate("""async ([api]) => {
            const s = await fetch(api + '/auth/session', {credentials: 'include'}).then(r => r.json());
            await fetch(api + '/farmers/me/profile', {method: 'PUT', credentials: 'include',
              headers: {'Content-Type': 'application/json', 'X-CSRF-Token': s.csrf_token},
              body: JSON.stringify({district: 'Mandya'})});
        }""", [API])                                              # profile changed elsewhere
        page.evaluate("window.dispatchEvent(new Event('focus'))")
        wait_text(page, "may be out of date")
        page.get_by_role("button", name="Recalculate now").click()
        page.get_by_text("may be out of date").wait_for(state="detached", timeout=10000)
        check("stale result is flagged and cleared by recalculating", True)

        # ── search history: delete one, clear all (entries inserted as the chat would) ──
        for q in ("ragi seed subsidy", "pm kisan status"):
            subprocess.run(["docker", "compose", "exec", "-T", "postgres", "psql", "-U", "schemesetu",
                            "-d", "schemesetu", "-c",
                            "INSERT INTO search_history (farmer_id, query, results_count, language) "
                            f"SELECT id, '{q}', 3, 'en' FROM farmers WHERE email = '{email}'"],
                           cwd=ROOT, check=True, capture_output=True)
        page.reload()
        wait_text(page, "pm kisan status")
        page.get_by_role("button", name="Delete search “pm kisan status”").click()
        page.locator(".hist-row", has_text="pm kisan status").wait_for(state="detached", timeout=8000)
        check("a single search can be deleted",
              page.locator(".hist-row", has_text="ragi seed subsidy").is_visible())
        page.get_by_role("button", name="Clear all").click()
        page.get_by_role("button", name="Yes, delete all").click()
        wait_text(page, "No saved searches")
        total = page.evaluate(f"fetch('{API}/farmers/me/search-history', {{credentials: 'include'}})"
                              ".then(r => r.headers.get('X-Total-Count'))")
        check("clear all empties the search history", total == "0", f"total {total}")

        # ── saved schemes: save, checklist progress persists, reference, milestone, unsave ──
        def saved_list():
            return page.evaluate(f"fetch('{API}/farmers/me/saved-schemes', {{credentials: 'include'}})"
                                 ".then(r => r.json())")

        row = page.locator(".elig-item").filter(has=page.get_by_role("button", name=re.compile(r"☆ Save"))).first
        name = row.locator(".elig-item-name").inner_text()
        row.get_by_role("button", name=re.compile(r"☆ Save")).click()
        page.locator(".elig-item", has_text=name).get_by_text("★ Saved").wait_for(timeout=8000)
        panel = page.locator("#saved-schemes")
        panel.get_by_text(name).first.wait_for(timeout=8000)
        listed = saved_list()
        check("Save on an eligibility row adds it to Saved Schemes with a checklist",
              len(listed) == 1 and listed[0]["scheme_name"] == name and listed[0]["progress"]["total"] > 0)
        dup = page.evaluate("""async ([api, sid]) => {
            const s = await fetch(api + '/auth/session', {credentials: 'include'}).then(r => r.json());
            const r = await fetch(api + '/farmers/me/saved-schemes', {method: 'POST', credentials: 'include',
              headers: {'Content-Type': 'application/json', 'X-CSRF-Token': s.csrf_token},
              body: JSON.stringify({scheme_id: sid})});
            return [r.status, (await r.json()).created];
        }""", [API, listed[0]["scheme_id"]])
        check("saving it again creates no duplicate", dup == [200, False] and len(saved_list()) == 1, str(dup))

        def open_checklist():
            panel.get_by_role("button", name="Open checklist").click()
            panel.locator(".sv-checklist").wait_for(timeout=8000)

        open_checklist()
        check("checklist says progress is user-reported, not government-confirmed",
              panel.get_by_text("not connected to any government").first.is_visible())
        first_box = panel.locator(".sv-check").first
        first_box.check()
        page.wait_for_function("document.querySelector('#saved-schemes .sv-check').checked === true")
        panel.get_by_text("1 of").first.wait_for(timeout=8000)
        panel.locator("input[id^=ref-]").fill("PMK/2026/000123")
        panel.get_by_role("button", name="Save reference").click()
        panel.get_by_text("Ref: PMK/2026/000123").wait_for(timeout=8000)
        panel.locator("input[id^=ms-]").fill("Field verification visit done")
        panel.get_by_role("button", name="Add milestone").click()
        panel.get_by_text("Field verification visit done").wait_for(timeout=8000)

        page.reload()
        panel.get_by_text(name).first.wait_for(timeout=15000)
        open_checklist()
        detail = page.evaluate(f"fetch('{API}/farmers/me/saved-schemes/{listed[0]['scheme_id']}', "
                               "{credentials: 'include'}).then(r => r.json())")
        check("ticks, reference and milestone persist after a reload",
              panel.locator(".sv-check").first.is_checked()
              and detail["application_reference"] == "PMK/2026/000123"
              and detail["checklist"][-1]["source"] == "USER"
              and detail["progress"]["completed"] == 1)

        panel.get_by_role("button", name=f"Remove {name}", exact=True).click()
        panel.get_by_role("button", name="Yes, remove").click()
        wait_text(page, "No saved schemes yet")
        page.locator(".elig-item", has_text=name).get_by_role("button", name=re.compile(r"☆ Save")).wait_for(timeout=8000)
        check("remove deletes the saved scheme and its checklist", saved_list() == [])

        page.goto(f"{base}/account/security")
        page.locator("#current-password").fill(pw1)
        page.locator("#new-password").fill(pw2)
        page.locator("#confirm-password").fill(pw2)
        page.get_by_role("button", name="Change password").click()
        wait_text(page, "Password changed")
        check("change password (CSRF-protected) succeeds", True)

        page.goto(f"{base}/dashboard")
        page.get_by_role("button", name="Sign Out").click()
        page.wait_for_url(f"{base}/auth", timeout=10000)
        status = page.evaluate(f"fetch('{API}/auth/session', {{credentials: 'include'}}).then(r => r.status)")
        check("sign out ends the server session", status == 401, f"session status {status}")

        page.get_by_role("button", name="Forgot password?").click()
        page.locator("#email").fill(email)
        page.get_by_role("button", name="Send Reset Link").click()
        wait_text(page, "If an account exists")
        check("forgot password shows generic message", True)

        reset = latest_link("reset-password", "2m")
        page.goto(reset)
        page.locator("#new-password").fill(pw3)
        page.locator("#confirm-password").fill(pw3)
        page.get_by_role("button", name="Set new password").click()
        wait_text(page, "Your password has been changed")
        check("reset link sets a new password", True)

        def api_login(pw):
            return page.evaluate(
                "([e, p]) => fetch('%s/auth/login', {method: 'POST', credentials: 'include', "
                "headers: {'Content-Type': 'application/json'}, body: JSON.stringify({email: e, password: p})})"
                ".then(r => r.status)" % API, [email, pw])

        check("old password rejected after reset", api_login(pw2) == 401)
        check("new password accepted", api_login(pw3) == 200)
        reuse = page.evaluate(
            "([t]) => fetch('%s/auth/reset-password', {method: 'POST', headers: {'Content-Type': 'application/json'},"
            " body: JSON.stringify({token: t, new_password: 'Another1357farm'})}).then(r => r.status)" % API,
            [reset.split("token=")[1]])
        check("reset link cannot be reused", reuse == 400, f"status {reuse}")
        browser.close()

    print(f"\n{sum(results)}/{len(results)} UI checks passed")
    sys.exit(0 if all(results) else 1)


if __name__ == "__main__":
    t0 = time.time()
    main()
