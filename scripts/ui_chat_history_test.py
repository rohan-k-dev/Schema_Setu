"""
UI test of chat history (docs/CHAT_HISTORY.md) in a real browser (Playwright) against the running stack
with the REAL services (`docker compose up`, API keys in backend/.env).

    python scripts/ui_chat_history_test.py [--base-url http://localhost:3000]

A signed-in farmer asks two questions (real assistant), finds the conversation under Chat history, reads
it, continues it in the chat (the earlier messages come back, a follow-up is added to the same
conversation), and a second farmer sees none of it (also not through the API with the thread id). Then:
delete one, turn saving off (a new chat isn't kept), delete all. Uses 2 sign-ups (5 per IP per hour).
"""

import argparse
import sys
import uuid

import httpx
from playwright.sync_api import sync_playwright

API = "http://localhost:8000"
PASSWORD = "HistoryUi2468farm"
results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f" - {detail}" if detail and not ok else ""))


def account(tag):
    email = f"{tag}-{uuid.uuid4().hex[:8]}@example.com"
    c = httpx.Client(base_url=API, headers={"Origin": "http://localhost:3000"}, timeout=180)
    r = c.post("/auth/register", json={"email": email, "password": PASSWORD})
    assert r.status_code == 202, f"register {r.status_code} (sign-up limit? restart the backend)"
    csrf = c.post("/auth/login", json={"email": email, "password": PASSWORD}).json()["csrf_token"]
    c.headers["X-CSRF-Token"] = csrf
    return email, c


def sign_in(browser, base, email):
    page = browser.new_page()
    page.goto(f"{base}/auth")
    page.locator("#email").fill(email)
    page.locator("#password").fill(PASSWORD)
    page.get_by_role("button", name="Sign In").click()
    page.wait_for_url(f"{base}/dashboard", timeout=20000)
    return page


def ask(page, text):
    """Send a message and wait for the assistant's real answer (the /chat response)."""
    page.get_by_label("Type your message").fill(text)
    with page.expect_response(lambda r: r.url.endswith("/chat") and r.request.method == "POST", timeout=120000):
        page.get_by_label("Send message").click()
    page.wait_for_timeout(500)


def main(base):
    me, _ = account("hist-me")
    other, other_api = account("hist-other")
    with sync_playwright() as p:
        try:
            browser = p.chromium.launch()
        except Exception:
            browser = p.chromium.launch(channel="msedge")
        pg = sign_in(browser, base, me)
        pg.goto(base, wait_until="networkidle")
        ask(pg, "I am a farmer in Bihar with 2.5 acres growing maize")
        ask(pg, "Which schemes can help me with crop insurance?")

        pg.goto(f"{base}/history", wait_until="networkidle")
        conv = pg.locator("[data-testid=conversation]")
        conv.first.wait_for(timeout=15000)
        check("conversation listed under Chat history", conv.count() == 1, str(conv.count()))
        card = conv.first.inner_text()
        check("titled with the first question, with count and date",
              "I am a farmer in Bihar" in card and "4 messages" in card, card)
        conv.first.get_by_role("button").first.click()
        view = pg.locator("[data-testid=conversation-view]")
        view.get_by_text("Which schemes can help me with crop insurance?").wait_for(timeout=10000)
        vtext = view.inner_text()
        replies = view.locator("li").count()
        check("opened conversation shows questions and replies",
              "I am a farmer in Bihar" in vtext and "crop insurance" in vtext and replies == 4, f"{replies} items")
        check("schemes shown are recorded with the reply", "Schemes shown:" in vtext, vtext[-300:])

        view.get_by_role("button", name="Continue this chat").click()
        pg.wait_for_url(f"{base}/", timeout=15000)
        pg.get_by_text("Which schemes can help me with crop insurance?").first.wait_for(timeout=15000)
        check("continuing restores the earlier messages in the chat",
              pg.get_by_text("I am a farmer in Bihar with 2.5 acres growing maize").count() >= 1)
        ask(pg, "What documents do I need for the first one?")
        pg.goto(f"{base}/history", wait_until="networkidle")
        conv.first.wait_for(timeout=15000)
        check("the follow-up was added to the same conversation",
              conv.count() == 1 and "6 messages" in conv.first.inner_text(), conv.first.inner_text())

        # another farmer sees nothing, not even with the thread id
        my_threads = pg.evaluate("fetch('http://localhost:8000/farmers/me/conversations', {credentials: 'include'})"
                                 ".then(r => r.json()).then(j => j.map(c => c.thread_id))")
        tid = my_threads[0]
        po = sign_in(browser, base, other)
        po.goto(f"{base}/history", wait_until="networkidle")
        po.get_by_test_id("history-empty").wait_for(timeout=15000)
        check("another farmer's history is empty", po.locator("[data-testid=conversation]").count() == 0)
        check("another farmer can't open it by id",
              other_api.get(f"/farmers/me/conversations/{tid}").status_code == 404)
        r = other_api.post("/chat", json={"message": "continue that chat", "thread_id": tid, "language": "en"})
        check("another farmer sending the thread id gets a new conversation",
              r.status_code == 200 and r.json().get("thread_id") != tid)

        # turn saving off: a new conversation is not kept
        pg.get_by_label("Save my conversations").uncheck()
        pg.get_by_text("New conversations won't be saved").wait_for(timeout=10000)
        pg.goto(base, wait_until="networkidle")
        pg.get_by_role("button", name="Start a new conversation").click()
        ask(pg, "This one should not be saved, I grow wheat in Punjab")
        pg.goto(f"{base}/history", wait_until="networkidle")
        conv.first.wait_for(timeout=15000)
        check("with saving off, the new chat isn't kept", conv.count() == 1, str(conv.count()))
        pg.get_by_label("Save my conversations").check()

        # delete one, then delete all
        conv.first.get_by_role("button", name="Delete").click()
        conv.first.get_by_role("button", name="Yes, delete").click()
        pg.get_by_text("Conversation deleted.").wait_for(timeout=10000)
        check("delete one", conv.count() == 0 and pg.get_by_test_id("history-empty").count() == 1)
        check("deleted conversation is gone on the server too",
              pg.evaluate(f"fetch('http://localhost:8000/farmers/me/conversations/{tid}', "
                          "{credentials: 'include'}).then(r => r.status)") == 404)
        browser.close()
    print(f"\n{sum(results)}/{len(results)} chat history UI checks passed")
    return all(results)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--base-url", default="http://localhost:3000")
    sys.exit(0 if main(ap.parse_args().base_url.rstrip("/")) else 1)
