"""
Scheme-update pipeline and notifications (docs/SCHEME_UPDATES.md) through the HTTP API
with real sessions: change detection (and false positives it must NOT report), the
verification step, publishing only approved changes, notifications to savers /
followers once, preferences, retries that never resend, failed / skipped deliveries,
SMS with a configured provider, verified phone, consent and opt-out, delivery status,
and unsubscribe. In-memory stores stand in for PostgreSQL (test_scheme_updates_pg.py
runs the SQL); files live in a temporary data folder.
"""

from __future__ import annotations

import asyncio
import copy
import json
import os
import re
import shutil
from datetime import datetime, timedelta, timezone

import pytest

from app.core.config import settings
from app.services import notification_channels as channels
from app.services import notification_service, scheme_update_service
from app.services.change_detection import diff_corpora
from app.tests.fake_notifications import FakeChangeRepo, FakeNotificationRepo
from app.tests.test_rbac import env  # noqa: F401  (fixture)

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
REAL_SEND_EMAIL = channels.send_email          # the real SMTP sender (fixtures replace it)


class Outbox:
    """Records sends; can be told to fail the next N sends."""

    def __init__(self):
        self.emails, self.sms, self.fail_next, self.fail_retryable = [], [], 0, True

    async def send_email(self, to, subject, body, unsubscribe_url=None):
        if self.fail_next:
            self.fail_next -= 1
            raise channels.ChannelError("SMTP down", retryable=self.fail_retryable)
        self.emails.append({"to": to, "subject": subject, "body": body, "unsubscribe": unsubscribe_url})
        return f"<m{len(self.emails)}@test>"

    async def send_sms(self, to, text, key):
        if self.fail_next:
            self.fail_next -= 1
            raise channels.ChannelError("provider 503", retryable=self.fail_retryable)
        self.sms.append({"to": to, "text": text, "key": key})
        return f"sms-{len(self.sms)}"


@pytest.fixture
def upd(env, tmp_path, monkeypatch):  # noqa: F811
    root = tmp_path / "data"
    for rel in ("validated/schemes.json", "metadata/corpus_manifest.json"):
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(os.path.join(ROOT, "data", rel), root / rel)
    (root / "incoming").mkdir()
    changes, notif, out = FakeChangeRepo(), FakeNotificationRepo(env.auth, env.saved), Outbox()
    imports = []

    class Stats:
        def to_dict(self):
            return {"records_read": 40, "errors": 0}

    async def fake_import(**kw):
        imports.append(kw)
        return Stats()

    for target, value in {
        "app.services.scheme_update_service.data_root": lambda: str(root),
        "app.services.scheme_update_service.changes_repo": changes,
        "app.services.scheme_update_service.notif_repo": notif,
        "app.services.notification_service.repo": notif,
        "app.api.notifications.repo": notif,
        "app.api.scheme_updates.notif_repo": notif,
        "app.services.corpus_import_service.import_corpus": fake_import,
        "app.services.notification_channels.send_email": out.send_email,
        "app.services.notification_channels.send_sms": out.send_sms,
    }.items():
        monkeypatch.setattr(target, value)
    monkeypatch.setattr("app.ingestion.corpus_loader.get_corpus_loader", lambda: type("L", (), {"load": lambda s: 0})())
    from app.core.rate_limit import LIMITS
    monkeypatch.setitem(LIMITS, "register_ip", (100, 3600))   # tests sign up many accounts from one "IP"
    monkeypatch.setattr(settings, "SMTP_HOST", "smtp.test")
    monkeypatch.setattr(settings, "SMS_PROVIDER", None)
    env.saved.put_scheme("DEDS")
    admin = env.user("ADMIN")
    env.user("ADMIN")
    verified = json.loads((root / "validated" / "schemes.json").read_text(encoding="utf-8"))
    return type("U", (), dict(env=env, root=root, changes=changes, notif=notif, out=out, admin=admin,
                              verified=verified, imports=imports))


def write_candidate(upd, name="scrape.json", mutate=None):
    data = copy.deepcopy(upd.verified)
    if mutate:
        mutate({s["scheme_id"]: s for s in data})
    (upd.root / "incoming" / name).write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return name


def detect(upd, name):
    r = upd.admin.call("POST", "/admin/scheme-changes/detect", {"source": name})
    assert r.status_code == 200, r.text
    return r.json()


def pending(upd, batch_id):
    return upd.admin.call("GET", f"/admin/scheme-changes?batch_id={batch_id}&status=PENDING").json()["items"]


def approve_all(upd, batch_id):
    for c in pending(upd, batch_id):
        r = upd.admin.call("POST", f"/admin/scheme-changes/{c['id']}/review",
                           {"decision": "APPROVED", "note": "Checked on the official portal today.",
                            "confirm_consequential": True})
        assert r.status_code == 200, r.text


def publish(upd, batch_id, dry_run=False):
    body = {"kind": "PUBLISH_CHANGES", "batch_id": batch_id, "reason": "publish verified scheme changes",
            "dry_run": dry_run, **({} if dry_run else {"confirm": "PUBLISH_CHANGES"})}
    r = upd.admin.call("POST", "/admin/ops/jobs", body)
    assert r.status_code == 202, r.text
    return upd.env.ops.jobs[r.json()["id"]]


def eligibility_change(by_id):
    rules = by_id["PM_KISAN"]["eligibility_rules"]
    rules.append({"field": "category", "operator": "NOT_IN", "value": ["income tax payer"], "required": True,
                  "logical_group": "AND"})


# ─── detection ────────────────────────────────────────────────────────────────

class TestDetection:
    def test_cosmetic_rescrape_reports_nothing(self, upd):
        def cosmetic(by_id):
            for s in by_id.values():
                s["name"] = s["name"].upper() + "  "
                s["eligibility_rules"] = list(reversed(s.get("eligibility_rules") or []))
                for d in s.get("required_documents") or []:
                    d["name"] = " " + d["name"].lower() + "."
                if s.get("official_url"):
                    s["official_url"] = s["official_url"].replace("https://www.", "http://") + "/#top"
                for r in s.get("source_records") or []:
                    r["retrieved_at"], r["content_hash"] = "2026-10-26", "new-hash"
                if not s.get("applicable_states"):
                    s["applicable_states"] = []
        out = detect(upd, write_candidate(upd, mutate=cosmetic))
        assert out["new_changes"] == 0 and out["warnings"] == [] and out["invalid_records"] == []

    @pytest.mark.parametrize("category,consequential,mutate", [
        ("ELIGIBILITY", True, eligibility_change),
        ("BENEFITS", True, lambda d: d["PM_KISAN"]["benefits"][0].update(amount="Rs. 8,000 per year")),
        ("STATES", True, lambda d: d["PM_KISAN"].update(applicable_states=["Karnataka"])),
        ("STATUS", True, lambda d: d["PM_KISAN"].update(status="INACTIVE")),
        ("DOCUMENTS", False, lambda d: d["PM_KISAN"]["required_documents"].append({"name": "Ration Card"})),
        ("STEPS", False, lambda d: d["PM_KISAN"]["application_steps"].append(
            {"step_number": 9, "description": "Complete e-KYC at the CSC"})),
        ("URLS", False, lambda d: d["PM_KISAN"].update(official_url="https://pmkisan.gov.in/new-portal")),
    ])
    def test_each_tracked_category_is_detected(self, upd, category, consequential, mutate):
        out = detect(upd, write_candidate(upd, mutate=mutate))
        items = pending(upd, out["batch_id"])
        assert [(c["scheme_id"], c["category"], c["consequential"]) for c in items] == [
            ("PM_KISAN", category, consequential)]
        prov = items[0]["provenance"]
        assert prov["source_file"] == "scrape.json" and len(prov["source_sha256"]) == 64
        assert prov["records"] and "url" in prov["records"][0] and items[0]["detected_at"]

    def test_running_detection_twice_creates_no_duplicates(self, upd):
        name = write_candidate(upd, mutate=eligibility_change)
        first, second = detect(upd, name), detect(upd, name)
        assert first["new_changes"] == 1 and second["new_changes"] == 0 and second["duplicates_skipped"] == 1
        assert len([c for c in upd.changes.changes.values() if c["status"] == "PENDING"]) == 1

    def test_broken_record_is_not_reported_as_a_missing_scheme(self, upd):
        def broken(by_id):
            del by_id["PMFBY"]["name"]                     # unparseable record
        out = detect(upd, write_candidate(upd, mutate=broken))
        assert out["invalid_records"][0]["scheme_id"] == "PMFBY"
        assert all(c["category"] != "MISSING_FROM_SOURCE" for c in pending(upd, out["batch_id"]))

    def test_a_scrape_missing_many_schemes_is_flagged_suspicious(self, upd):
        name = "partial.json"
        (upd.root / "incoming" / name).write_text(json.dumps(upd.verified[:10]), encoding="utf-8")
        out = detect(upd, name)
        assert out["warnings"] and "incomplete" in out["warnings"][0]
        cats = {c["category"] for c in pending(upd, out["batch_id"])}
        assert cats == {"MISSING_FROM_SOURCE"}

    @pytest.mark.parametrize("source,code", [("../validated/schemes.json", 422), ("scrape.csv", 422),
                                             ("nope.json", 404), ("..%2fx.json", 422)])
    def test_only_files_in_the_incoming_folder(self, upd, source, code):
        assert upd.admin.call("POST", "/admin/scheme-changes/detect", {"source": source}).status_code == code


# ─── verification ─────────────────────────────────────────────────────────────

class TestVerification:
    def test_consequential_change_needs_confirmation_and_note(self, upd):
        out = detect(upd, write_candidate(upd, mutate=eligibility_change))
        cid = pending(upd, out["batch_id"])[0]["id"]
        for body in ({"decision": "APPROVED"}, {"decision": "APPROVED", "note": "ok"},
                     {"decision": "APPROVED", "note": "Checked the official site.", "confirm_consequential": False}):
            r = upd.admin.call("POST", f"/admin/scheme-changes/{cid}/review", body)
            assert r.status_code == 422 and r.json()["detail"]["code"] == "CONFIRMATION_REQUIRED"
        assert upd.changes.changes[cid]["status"] == "PENDING"
        assert upd.env.audit.rows[-1].outcome == "FAILURE"
        r = upd.admin.call("POST", f"/admin/scheme-changes/{cid}/review",
                           {"decision": "APPROVED", "note": "Checked the official site.", "confirm_consequential": True})
        assert r.status_code == 200 and r.json()["reviewed_by"] == upd.admin.email
        again = upd.admin.call("POST", f"/admin/scheme-changes/{cid}/review", {"decision": "REJECTED"})
        assert again.status_code == 409

    def test_nothing_is_published_or_notified_while_changes_are_pending(self, upd):
        f = upd.env.user("FARMER")
        f.call("POST", "/farmers/me/saved-schemes", {"scheme_id": "PM_KISAN"})
        out = detect(upd, write_candidate(upd, mutate=eligibility_change))
        job = publish(upd, out["batch_id"])
        assert job["status"] == "FAILED" and "still pending" in job["error"]
        assert upd.notif.notifications == {} and upd.imports == []
        assert json.loads((upd.root / "validated" / "schemes.json").read_text(encoding="utf-8")) == upd.verified

    def test_rejected_changes_are_never_published_or_notified(self, upd):
        f = upd.env.user("FARMER")
        f.call("POST", "/farmers/me/saved-schemes", {"scheme_id": "PM_KISAN"})

        def both(by_id):
            eligibility_change(by_id)
            by_id["PM_KISAN"]["required_documents"].append({"name": "Ration Card"})
        out = detect(upd, write_candidate(upd, mutate=both))
        for c in pending(upd, out["batch_id"]):
            decision = "REJECTED" if c["category"] == "ELIGIBILITY" else "APPROVED"
            upd.admin.call("POST", f"/admin/scheme-changes/{c['id']}/review", {"decision": decision, "note": "checked"})
        job = publish(upd, out["batch_id"])
        assert job["status"] == "SUCCEEDED", job["error"]
        written = {s["scheme_id"]: s for s in json.loads((upd.root / "validated" / "schemes.json").read_text("utf-8"))}
        old = {s["scheme_id"]: s for s in upd.verified}
        assert written["PM_KISAN"]["eligibility_rules"] == old["PM_KISAN"]["eligibility_rules"]   # rejected: unchanged
        assert any(d["name"] == "Ration Card" for d in written["PM_KISAN"]["required_documents"])
        n = next(iter(upd.notif.notifications.values()))
        assert "Required documents changed" in n["body"] and "Eligibility" not in n["body"]
        assert n["consequential"] is False

    def test_only_rejections_means_nothing_to_publish(self, upd):
        out = detect(upd, write_candidate(upd, mutate=eligibility_change))
        cid = pending(upd, out["batch_id"])[0]["id"]
        upd.admin.call("POST", f"/admin/scheme-changes/{cid}/review", {"decision": "REJECTED", "note": "scraper bug"})
        job = publish(upd, out["batch_id"])
        assert job["status"] == "FAILED" and "Nothing to publish" in job["error"]

    def test_candidate_edited_after_detection_is_refused(self, upd):
        name = write_candidate(upd, mutate=eligibility_change)
        out = detect(upd, name)
        approve_all(upd, out["batch_id"])
        write_candidate(upd, name, mutate=lambda d: d["PMFBY"].update(status="INACTIVE"))
        job = publish(upd, out["batch_id"])
        assert job["status"] == "FAILED" and "changed after detection" in job["error"]

    def test_dry_run_publish_changes_nothing(self, upd):
        out = detect(upd, write_candidate(upd, mutate=eligibility_change))
        approve_all(upd, out["batch_id"])
        job = publish(upd, out["batch_id"], dry_run=True)
        assert job["status"] == "SUCCEEDED" and job["result"]["schemes_affected"] == ["PM_KISAN"]
        assert upd.imports == [] and upd.notif.notifications == {}
        assert upd.changes.batches[out["batch_id"]]["status"] == "OPEN"

    def test_publish_writes_a_new_version_and_imports(self, upd):
        out = detect(upd, write_candidate(upd, mutate=eligibility_change))
        approve_all(upd, out["batch_id"])
        job = publish(upd, out["batch_id"])
        assert job["status"] == "SUCCEEDED", job["error"]
        manifest = json.loads((upd.root / "metadata" / "corpus_manifest.json").read_text("utf-8"))
        assert manifest["corpus_version"] == "1.0.1" and upd.imports == [{"dry_run": False, "force": False}]
        assert (upd.root / job["result"]["backup"] / "schemes.json").exists()
        assert upd.changes.batches[out["batch_id"]]["status"] == "PUBLISHED"
        assert publish(upd, out["batch_id"])["status"] == "FAILED"             # can't publish twice

    def test_failed_import_restores_the_files_and_notifies_nobody(self, upd, monkeypatch):
        f = upd.env.user("FARMER")
        f.call("POST", "/farmers/me/saved-schemes", {"scheme_id": "PM_KISAN"})

        async def broken(**kw):
            raise RuntimeError("db down")
        monkeypatch.setattr("app.services.corpus_import_service.import_corpus", broken)
        out = detect(upd, write_candidate(upd, mutate=eligibility_change))
        approve_all(upd, out["batch_id"])
        job = publish(upd, out["batch_id"])
        assert job["status"] == "FAILED" and "restored" in job["error"]
        assert json.loads((upd.root / "validated" / "schemes.json").read_text("utf-8")) == upd.verified
        assert upd.notif.notifications == {} and upd.changes.batches[out["batch_id"]]["status"] == "OPEN"


# ─── notifications ────────────────────────────────────────────────────────────

def publish_change(upd, mutate=eligibility_change, name="scrape.json"):
    out = detect(upd, write_candidate(upd, name, mutate=mutate))
    approve_all(upd, out["batch_id"])
    job = publish(upd, out["batch_id"])
    assert job["status"] == "SUCCEEDED", job["error"]
    return out["batch_id"]


class TestNotifications:
    def test_savers_and_followers_are_notified_once(self, upd):
        saver, follower, both, other = (upd.env.user("FARMER") for _ in range(4))
        saver.call("POST", "/farmers/me/saved-schemes", {"scheme_id": "PM_KISAN"})
        assert follower.call("PUT", "/farmers/me/subscriptions/PM_KISAN").status_code == 201
        both.call("POST", "/farmers/me/saved-schemes", {"scheme_id": "PM_KISAN"})
        both.call("PUT", "/farmers/me/subscriptions/PM_KISAN")
        other.call("POST", "/farmers/me/saved-schemes", {"scheme_id": "PMFBY"})
        batch = publish_change(upd)
        counts = {u.email: u.call("GET", "/farmers/me/notifications").json()["total"]
                  for u in (saver, follower, both, other)}
        assert counts == {saver.email: 1, follower.email: 1, both.email: 1, other.email: 0}
        n = saver.call("GET", "/farmers/me/notifications").json()["items"][0]
        assert n["consequential"] and "still qualify" in n["body"] and "checked by the SchemeSetu team" in n["body"]
        # running the fan-out again (job retry) creates nothing new
        published = [c for c in upd.changes.changes.values() if c["status"] == "PUBLISHED"]
        again = asyncio.run(scheme_update_service.notify(batch, published))
        assert again["created"] == 0 and len(upd.notif.notifications) == 3

    def test_in_app_off_and_no_other_channel_means_no_notification(self, upd):
        f = upd.env.user("FARMER")
        f.call("POST", "/farmers/me/saved-schemes", {"scheme_id": "PM_KISAN"})
        assert f.call("PUT", "/farmers/me/notification-preferences", {"in_app": False}).status_code == 200
        publish_change(upd)
        assert upd.notif.notifications == {}

    def test_consequential_only_skips_minor_updates(self, upd):
        f = upd.env.user("FARMER")
        f.call("POST", "/farmers/me/saved-schemes", {"scheme_id": "PM_KISAN"})
        f.call("PUT", "/farmers/me/notification-preferences", {"consequential_only": True})
        publish_change(upd, mutate=lambda d: d["PM_KISAN"]["required_documents"].append({"name": "Ration Card"}))
        assert upd.notif.notifications == {}
        publish_change(upd, name="scrape2.json", mutate=lambda d: (
            d["PM_KISAN"]["required_documents"].append({"name": "Ration Card"}), eligibility_change(d)))
        assert f.call("GET", "/farmers/me/notifications").json()["total"] == 1

    def test_email_sent_once_with_unsubscribe_link(self, upd):
        f = upd.env.user("FARMER")
        f.call("POST", "/farmers/me/saved-schemes", {"scheme_id": "PM_KISAN"})
        assert f.call("PUT", "/farmers/me/notification-preferences", {"email": True}).status_code == 200
        publish_change(upd)
        assert len(upd.out.emails) == 1 and upd.out.emails[0]["to"] == f.email
        assert "/unsubscribe?token=" in upd.out.emails[0]["body"]
        asyncio.run(notification_service.dispatch_due())
        asyncio.run(notification_service.dispatch_due())
        assert len(upd.out.emails) == 1                                     # never resent
        d = next(iter(upd.notif.deliveries.values()))
        assert d["status"] == "SENT" and d["attempts"] == 1 and d["provider_message_id"]

    def test_inbox_read_and_ownership(self, upd):
        a, b = upd.env.user("FARMER"), upd.env.user("FARMER")
        a.call("POST", "/farmers/me/saved-schemes", {"scheme_id": "PM_KISAN"})
        publish_change(upd)
        nid = a.call("GET", "/farmers/me/notifications").json()["items"][0]["id"]
        assert b.call("POST", f"/farmers/me/notifications/{nid}/read").status_code == 404
        assert a.call("GET", "/farmers/me/notifications?unread_only=true").json()["unread"] == 1
        assert a.call("POST", f"/farmers/me/notifications/{nid}/read").status_code == 204
        assert a.call("GET", "/farmers/me/notifications").json()["unread"] == 0

    def test_follow_validation(self, upd):
        f = upd.env.user("FARMER")
        assert f.call("PUT", "/farmers/me/subscriptions/NOT_A_SCHEME").status_code == 404
        assert f.call("PUT", "/farmers/me/subscriptions/PM_KISAN").status_code == 201
        assert f.call("PUT", "/farmers/me/subscriptions/PM_KISAN").status_code == 200      # idempotent
        assert f.call("DELETE", "/farmers/me/subscriptions/PM_KISAN").status_code == 204
        assert f.call("DELETE", "/farmers/me/subscriptions/PM_KISAN").status_code == 404


# ─── delivery: retries, failures, preferences at send time ────────────────────

def _due_now(upd):
    for d in upd.notif.deliveries.values():
        d["next_attempt_at"] = datetime.now(timezone.utc) - timedelta(seconds=1)


class TestDelivery:
    def _setup(self, upd):
        f = upd.env.user("FARMER")
        f.call("POST", "/farmers/me/saved-schemes", {"scheme_id": "PM_KISAN"})
        f.call("PUT", "/farmers/me/notification-preferences", {"email": True})
        return f

    def test_failed_delivery_is_retried_with_backoff_then_sent_once(self, upd):
        self._setup(upd)
        upd.out.fail_next = 2
        publish_change(upd)
        d = next(iter(upd.notif.deliveries.values()))
        assert d["status"] == "FAILED" and d["attempts"] == 1 and d["next_attempt_at"] > datetime.now(timezone.utc)
        asyncio.run(notification_service.dispatch_due())
        assert d["attempts"] == 1                                   # not due yet: backoff respected
        _due_now(upd)
        asyncio.run(notification_service.dispatch_due())
        assert d["status"] == "FAILED" and d["attempts"] == 2
        _due_now(upd)
        asyncio.run(notification_service.dispatch_due())
        assert d["status"] == "SENT" and d["attempts"] == 3 and len(upd.out.emails) == 1
        _due_now(upd)
        asyncio.run(notification_service.dispatch_due())
        assert len(upd.out.emails) == 1

    def test_gives_up_after_max_attempts(self, upd, monkeypatch):
        monkeypatch.setattr(settings, "NOTIFY_MAX_ATTEMPTS", 3)
        self._setup(upd)
        upd.out.fail_next = 99
        publish_change(upd)
        for _ in range(5):
            _due_now(upd)
            asyncio.run(notification_service.dispatch_due())
        d = next(iter(upd.notif.deliveries.values()))
        assert d["status"] == "GAVE_UP" and d["attempts"] == 3 and upd.out.emails == []

    def test_permanent_failure_is_skipped_not_retried(self, upd):
        self._setup(upd)
        upd.out.fail_next, upd.out.fail_retryable = 1, False
        publish_change(upd)
        d = next(iter(upd.notif.deliveries.values()))
        assert d["status"] == "SKIPPED" and d["attempts"] == 1
        _due_now(upd)
        asyncio.run(notification_service.dispatch_due())
        assert d["attempts"] == 1

    def test_email_not_configured_is_skipped_not_faked(self, upd, monkeypatch):
        self._setup(upd)
        monkeypatch.setattr(settings, "SMTP_HOST", None)
        monkeypatch.setattr("app.services.notification_channels.send_email", REAL_SEND_EMAIL)
        publish_change(upd)
        d = next(iter(upd.notif.deliveries.values()))
        assert d["status"] == "SKIPPED" and "not configured" in d["last_error"]

    def test_opt_out_after_queueing_stops_the_send(self, upd):
        f = self._setup(upd)
        upd.out.fail_next = 1
        publish_change(upd)
        f.call("PUT", "/farmers/me/notification-preferences", {"email": False})
        _due_now(upd)
        asyncio.run(notification_service.dispatch_due())
        d = next(iter(upd.notif.deliveries.values()))
        assert d["status"] == "SKIPPED" and "Opted out" in d["last_error"] and upd.out.emails == []

    def test_concurrent_dispatchers_send_each_delivery_once(self, upd):
        for _ in range(3):
            self._setup(upd)
        upd.out.fail_next = 3
        publish_change(upd)
        _due_now(upd)

        async def both():
            await asyncio.gather(notification_service.dispatch_due(), notification_service.dispatch_due())
        asyncio.run(both())
        assert len(upd.out.emails) == 3 and len({e["to"] for e in upd.out.emails}) == 3

    def test_admin_sees_delivery_status(self, upd):
        self._setup(upd)
        publish_change(upd)
        body = upd.admin.call("GET", "/admin/notifications/deliveries?channel=EMAIL").json()
        assert body["counts"] == {"SENT": 1} and body["items"][0]["status"] == "SENT"
        assert "email" not in json.dumps(body["items"]).lower().replace("\"channel\": \"email\"", "")


# ─── SMS: provider, verified phone, consent, opt-out, status ──────────────────

def _code(upd) -> str:
    return re.search(r"\b(\d{6})\b", upd.out.sms[-1]["text"]).group(1)


class TestSms:
    def test_sms_needs_a_configured_provider(self, upd):
        f = upd.env.user("FARMER")
        r = f.call("PUT", "/farmers/me/notification-preferences", {"sms": True, "sms_consent": True})
        assert r.status_code == 409 and r.json()["detail"]["code"] == "SMS_UNAVAILABLE"
        assert f.call("POST", "/farmers/me/phone", {"phone": "9876543210"}).status_code == 503

    def test_log_provider_is_refused_in_production(self, upd, monkeypatch):
        monkeypatch.setattr(settings, "SMS_PROVIDER", "log")
        assert channels.sms_available()
        monkeypatch.setattr(settings, "ENVIRONMENT", "production")
        assert not channels.sms_available()

    def test_verified_phone_and_consent_are_required(self, upd, monkeypatch):
        monkeypatch.setattr(settings, "SMS_PROVIDER", "log")
        f = upd.env.user("FARMER")
        r = f.call("PUT", "/farmers/me/notification-preferences", {"sms": True, "sms_consent": True})
        assert r.json()["detail"]["code"] == "PHONE_NOT_VERIFIED"
        assert f.call("POST", "/farmers/me/phone", {"phone": "+91 98765 43210"}).json()["sent_to"] == "***210"
        assert "98765" not in json.dumps(f.call("GET", "/farmers/me/notification-preferences").json())
        assert f.call("POST", "/farmers/me/phone/verify", {"code": _code(upd)}).status_code == 200
        r = f.call("PUT", "/farmers/me/notification-preferences", {"sms": True})
        assert r.status_code == 422 and r.json()["detail"]["code"] == "CONSENT_REQUIRED"
        r = f.call("PUT", "/farmers/me/notification-preferences", {"sms": True, "sms_consent": True})
        prefs = r.json()["preferences"]
        assert prefs["sms"] and prefs["sms_consent_at"] and prefs["sms_consent_version"] == settings.SMS_CONSENT_VERSION
        assert upd.env.audit.rows[-1].action == "NOTIFICATION_CONSENT"

    def test_wrong_codes_lock_the_code(self, upd, monkeypatch):
        monkeypatch.setattr(settings, "SMS_PROVIDER", "log")
        f = upd.env.user("FARMER")
        f.call("POST", "/farmers/me/phone", {"phone": "9876543210"})
        right = _code(upd)
        wrong = "000000" if right != "000000" else "111111"
        codes = [f.call("POST", "/farmers/me/phone/verify", {"code": wrong}).json()["detail"]["code"] for _ in range(5)]
        assert codes == ["CODE_WRONG"] * 4 + ["CODE_LOCKED"]
        assert f.call("POST", "/farmers/me/phone/verify", {"code": right}).json()["detail"]["code"] == "CODE_LOCKED"
        for bad in ("12345", "abcdef", "1234567"):
            assert f.call("POST", "/farmers/me/phone/verify", {"code": bad}).status_code == 422
        assert f.call("POST", "/farmers/me/phone", {"phone": "12345"}).status_code == 422

    def test_a_number_verified_elsewhere_cant_be_taken(self, upd, monkeypatch):
        monkeypatch.setattr(settings, "SMS_PROVIDER", "log")
        a, b = upd.env.user("FARMER"), upd.env.user("FARMER")
        a.call("POST", "/farmers/me/phone", {"phone": "9876543210"})
        a.call("POST", "/farmers/me/phone/verify", {"code": _code(upd)})
        b.call("POST", "/farmers/me/phone", {"phone": "9876543210"})
        r = b.call("POST", "/farmers/me/phone/verify", {"code": _code(upd)})
        assert r.status_code == 409 and r.json()["detail"]["code"] == "PHONE_UNAVAILABLE"

    def _sms_user(self, upd, monkeypatch):
        monkeypatch.setattr(settings, "SMS_PROVIDER", "log")
        f = upd.env.user("FARMER")
        f.call("POST", "/farmers/me/saved-schemes", {"scheme_id": "PM_KISAN"})
        f.call("POST", "/farmers/me/phone", {"phone": "9876543210"})
        f.call("POST", "/farmers/me/phone/verify", {"code": _code(upd)})
        assert f.call("PUT", "/farmers/me/notification-preferences", {"sms": True, "sms_consent": True}).status_code == 200
        return f

    def test_sms_sent_once_and_delivery_status_tracked(self, upd, monkeypatch):
        self._sms_user(upd, monkeypatch)
        monkeypatch.setattr(settings, "SMS_STATUS_SECRET", "status-secret-123")
        before = len(upd.out.sms)
        publish_change(upd)
        assert len(upd.out.sms) == before + 1 and len(upd.out.sms[-1]["text"]) <= 160
        d = next(d for d in upd.notif.deliveries.values() if d["channel"] == "SMS")
        assert d["status"] == "SENT"
        from fastapi.testclient import TestClient
        from app.main import app
        c = TestClient(app)
        body = json.dumps({"message_id": d["provider_message_id"], "status": "delivered"}).encode()
        assert c.post("/notifications/sms-status", content=body, headers={"X-Signature": "forged"}).status_code == 403
        assert d["status"] == "SENT"
        ok = c.post("/notifications/sms-status", content=body, headers={"X-Signature": channels.status_signature(body)})
        assert ok.status_code == 204 and d["status"] == "DELIVERED"

    def test_sms_opt_out_takes_effect_for_queued_messages(self, upd, monkeypatch):
        f = self._sms_user(upd, monkeypatch)
        upd.out.fail_next = 1                              # first attempt fails → queued for retry
        before = len(upd.out.sms)
        publish_change(upd)
        f.call("PUT", "/farmers/me/notification-preferences", {"sms": False})
        assert f.call("GET", "/farmers/me/notification-preferences").json()["preferences"]["sms_opted_out_at"]
        _due_now(upd)
        asyncio.run(notification_service.dispatch_due())
        d = next(d for d in upd.notif.deliveries.values() if d["channel"] == "SMS")
        assert d["status"] == "SKIPPED" and len(upd.out.sms) == before

    def test_removing_the_phone_turns_sms_off(self, upd, monkeypatch):
        f = self._sms_user(upd, monkeypatch)
        assert f.call("DELETE", "/farmers/me/phone").status_code == 204
        prefs = f.call("GET", "/farmers/me/notification-preferences").json()
        assert prefs["preferences"]["sms"] is False and prefs["channels"]["phone_verified"] is False


class TestUnsubscribe:
    def test_link_turns_email_off_and_tampering_is_refused(self, upd):
        from fastapi.testclient import TestClient
        from app.main import app
        f = upd.env.user("FARMER")
        f.call("PUT", "/farmers/me/notification-preferences", {"email": True})
        token = notification_service.unsubscribe_token(f.farmer_id, "email")
        c = TestClient(app)
        tampered = token[:-1] + ("1" if token[-1] == "0" else "0")      # always differs from the real token
        assert c.post("/notifications/unsubscribe", json={"token": tampered}).status_code == 400
        assert c.post("/notifications/unsubscribe", json={"token": token}).json() == {"unsubscribed": "email"}
        assert f.call("GET", "/farmers/me/notification-preferences").json()["preferences"]["email"] is False
        assert c.post("/notifications/unsubscribe", json={"token": token}).status_code == 200      # idempotent


def test_detector_ignores_provenance_only_differences():
    a = [{"scheme_id": "X", "name": "X", "status": "ACTIVE", "source_records": [{"source_id": "s", "retrieved_at": "1"}]}]
    b = copy.deepcopy(a)
    b[0]["source_records"][0]["retrieved_at"] = "2"
    assert diff_corpora(a, b, "f", "h")[0] == []
