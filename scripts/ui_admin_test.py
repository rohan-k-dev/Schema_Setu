"""
UI test of the administrator operations dashboard in a real browser (Playwright),
against the running local stack (`docker compose up`). docs/ADMIN_OPERATIONS.md.

    python scripts/ui_admin_test.py [--base-url http://localhost:3000]

Creates a farmer and an administrator (promoted with scripts/set_role.py inside the
backend container), then checks: the farmer is refused /admin and its API; the
admin sees every dashboard section, validates data, inspects conflicts, runs a
dry-run graph job, can't start a real run without typing the confirmation, finds
the job in the audit log and verifies the hash chain. Exit code 0 = all passed.
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
PASSWORD = "AdminUi2468farm"
results = []


def check(name, ok, detail=""):
    results.append(ok)
    print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f" — {detail}" if detail and not ok else ""))


def make_account(tag: str) -> str:
    email = f"{tag}-{uuid.uuid4().hex[:8]}@example.com"
    c = httpx.Client(base_url=API, headers={"Origin": "http://localhost:3000"})
    assert c.post("/auth/register", json={"email": email, "password": PASSWORD}).status_code == 202
    return email


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
    farmer, admin = make_account("ui-farmer"), make_account("ui-admin")
    r = subprocess.run(["docker", "compose", "exec", "-T", "backend", "python", "../scripts/set_role.py", admin,
                        "ADMIN"], cwd=ROOT, capture_output=True, text=True)
    check("administrator created on the server with set_role.py", r.returncode == 0, r.stdout + r.stderr)

    with sync_playwright() as p:
        try:
            browser = p.chromium.launch()
        except Exception:
            browser = p.chromium.launch(channel="msedge")

        page = browser.new_page()
        sign_in(page, base, farmer)
        check("farmer's dashboard has no Operations button",
              page.get_by_role("button", name=re.compile("Operations")).count() == 0)
        page.goto(f"{base}/admin")
        page.get_by_text("Administrator access required").wait_for(timeout=10000)
        check("farmer opening /admin sees 'access required' and no data",
              page.get_by_text("System health").count() == 0)
        status = page.evaluate(f"fetch('{API}/admin/ops/overview', {{credentials: 'include'}}).then(r => r.status)")
        check("farmer calling the admin API directly gets 403", status == 403, str(status))
        page.close()

        page = browser.new_page()
        sign_in(page, base, admin)
        page.get_by_role("button", name=re.compile("Operations")).click()
        page.wait_for_url(f"{base}/admin", timeout=10000)
        page.get_by_text("System health").wait_for(timeout=15000)
        sections = ["System health", "Scheme corpus", "Ingestion jobs", "Graph synchronisation",
                    "Pending reviews", "Recent errors"]
        check("dashboard shows every section", all(page.get_by_role("region", name=re.compile(s)).count() > 0
                                                    for s in sections))
        check("no section is unavailable", page.get_by_text("Unavailable:").count() == 0)
        mig = page.get_by_text(re.compile(r"/ expected \d{4}")).first.inner_text()
        current = re.match(r"\W*(\w+) / expected (\w+)", mig)
        check("migration is up to date", current and current.group(1) == current.group(2), mig)

        page.get_by_role("button", name="Validate scheme data").click()
        page.get_by_text(re.compile(r"^Overall:")).wait_for(timeout=20000)     # the report, not the corpus card
        check("validation report lists the checks",
              page.get_by_role("cell", name="knowledge graph").count() > 0
              and page.get_by_role("cell", name="file vs database").count() > 0)
        check("file and database corpus versions are both read (not 'None')",
              page.get_by_text(re.compile(r"vs file None")).count() == 0)

        page.get_by_role("button", name="Inspect conflicts").click()
        page.get_by_text("Contradictory rules").wait_for(timeout=10000)
        check("conflict inspection shows source conflicts, rule conflicts and flags",
              page.get_by_text(re.compile("Source conflicts")).count() > 0
              and page.get_by_text("Flagged schemes").count() > 0)

        jobs = page.locator("section", has=page.get_by_role("heading", name=re.compile("Ingestion .* graph jobs")))
        jobs.locator("select.adm-input").select_option("REBUILD_GRAPH")
        page.get_by_placeholder(re.compile("corpus v1.1")).fill("UI test: graph dry run")
        page.get_by_role("button", name="Start dry run").click()
        page.get_by_text(re.compile(r"Job REBUILD_GRAPH \(dry run\)")).wait_for(timeout=10000)
        page.locator(".adm-block .adm-badge", has_text="SUCCEEDED").first.wait_for(timeout=60000)
        check("dry-run graph job succeeds and shows its result", page.get_by_text('"nodes"').count() > 0)

        page.get_by_label("Dry run (check only, change nothing)").uncheck()
        run_button = page.get_by_role("button", name="Run for real")
        check("real run is disabled until the job name is typed", run_button.is_disabled())
        page.get_by_label(re.compile("to confirm")).fill("REBUILD")
        check("a wrong confirmation keeps it disabled", run_button.is_disabled())
        page.get_by_label("Dry run (check only, change nothing)").check()

        page.locator("#aud-action").fill("JOB_REQUESTED")
        page.get_by_role("button", name="Filter").click()
        page.locator(".adm-table td", has_text="JOB_REQUESTED").first.wait_for(timeout=10000)
        row = page.locator("tr", has_text="JOB_REQUESTED").first
        check("audit log shows the job with actor, outcome and correlation id",
              admin in row.inner_text() and "SUCCESS" in row.inner_text()
              and re.search(r"[0-9a-f]{32}", row.inner_text()) is not None)
        page.get_by_role("button", name="Verify integrity").click()
        page.get_by_text(re.compile("Hash chain intact")).wait_for(timeout=15000)
        check("audit hash chain verifies as intact", True)
        browser.close()

    print(f"\n{sum(results)}/{len(results)} admin UI checks passed")
    sys.exit(0 if all(results) else 1)


if __name__ == "__main__":
    main()
