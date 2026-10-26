"""
Capture real screenshots of the running application (Phase 8 Step 30).

Prerequisites (from Scheme_Setu/):
    python scripts/demo_server.py               # backend on :8000 (demo mode)
    cd frontend && npm run build && npx next start -p 3000
    pip install playwright==1.47.0              # uses the installed Google Chrome

Usage:
    python scripts/capture_screenshots.py [--base-url http://localhost:3000]

Writes PNGs to docs/assets/screenshots/. The voice step uses Chrome's fake
microphone (--use-fake-device-for-media-stream); in demo mode the backend's
simulated ASR returns the demo script transcript.
"""

import argparse
import os

from playwright.sync_api import sync_playwright

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "docs", "assets", "screenshots")


def send(page, text, wait_ms=600):
    page.get_by_label("Type your message").fill(text)
    page.get_by_label("Send message").click()
    page.wait_for_function("() => !document.body.innerText.includes('Checking schemes and eligibility')",
                           timeout=60000)
    page.wait_for_timeout(wait_ms)


def shot(page, name, full=False):
    path = os.path.join(OUT, name)
    page.screenshot(path=path, full_page=full)
    print("saved", os.path.relpath(path, ROOT))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base-url", default="http://localhost:3000")
    args = ap.parse_args()
    os.makedirs(OUT, exist_ok=True)

    with sync_playwright() as p:
        browser = p.chromium.launch(channel="chrome", args=[
            "--use-fake-device-for-media-stream", "--use-fake-ui-for-media-stream"])

        # ── desktop journey ──────────────────────────────────────
        ctx = browser.new_context(viewport={"width": 1440, "height": 900}, permissions=["microphone"])
        page = ctx.new_page()
        page.goto(args.base_url)
        page.wait_for_timeout(1500)
        shot(page, "01-landing.png")

        send(page, "Hello, I need help finding schemes")
        send(page, "I live in Karnataka")
        shot(page, "02-onboarding-questions.png")
        send(page, "I have 2 acres")
        send(page, "I grow ragi and I am a farmer", wait_ms=1200)
        shot(page, "03-profile-and-results.png")

        card = page.get_by_role("article", name="Scheme: Pradhan Mantri Kisan Samman Nidhi", exact=False).first
        card.get_by_label("Expand details").click()
        page.wait_for_timeout(500)
        card.scroll_into_view_if_needed()
        shot(page, "04-eligibility-documents-steps-source.png")

        send(page, "What documents do I need for the first one?", wait_ms=1000)
        shot(page, "05-follow-up-documents.png")

        page.get_by_label("Select language").click()
        page.get_by_role("option", name="हिन्दी").click()
        page.wait_for_timeout(500)
        send(page, "पहली योजना के लिए कौन से दस्तावेज़ चाहिए?", wait_ms=1000)
        shot(page, "06-language-switch-hindi.png")

        page.get_by_label("Start a new conversation").click()
        page.get_by_label("Select language").click()
        page.get_by_role("option", name="ಕನ್ನಡ").click()
        voice = page.locator("button[aria-label='Press to speak'], button[aria-label^='Recording']").first
        voice.click()
        page.wait_for_timeout(2500)
        voice.click()
        page.wait_for_function("() => document.body.innerText.includes('🎙️ \"')", timeout=60000)
        page.wait_for_timeout(1500)
        page.get_by_text("🎙️", exact=False).last.scroll_into_view_if_needed()
        page.evaluate("() => { const b=[...document.querySelectorAll('[role=log] > div')]"
                      ".find(d => d.innerText.includes('🎙️')); if (b) b.scrollIntoView({block:'start'}); }")
        page.wait_for_timeout(600)
        shot(page, "07-voice-kannada.png")
        ctx.close()

        # ── mobile ───────────────────────────────────────────────
        ctx = browser.new_context(viewport={"width": 390, "height": 844}, device_scale_factor=2,
                                  is_mobile=True, has_touch=True)
        page = ctx.new_page()
        page.goto(args.base_url)
        page.wait_for_timeout(1200)
        send(page, "I am a farmer from Karnataka with 2 acres growing ragi", wait_ms=1200)
        shot(page, "08-mobile-chat.png")
        page.get_by_role("region", name="Personalized scheme recommendations").scroll_into_view_if_needed()
        page.wait_for_timeout(400)
        shot(page, "09-mobile-scheme-cards.png")
        ctx.close()

        # ── API documentation incl. human-review endpoints ───────
        ctx = browser.new_context(viewport={"width": 1440, "height": 1000})
        page = ctx.new_page()
        page.goto("http://localhost:8000/docs")
        page.wait_for_timeout(2500)
        shot(page, "10-api-docs-review-endpoints.png", full=True)
        ctx.close()
        browser.close()


if __name__ == "__main__":
    main()
