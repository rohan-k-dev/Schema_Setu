"""
In-memory stand-ins for change_repository and notification_repository with the same
rules as the SQL (fingerprint dedupe while pending / approved, one notification per
account + dedupe key, one delivery per channel, claim → SENDING, owner scoping).
test_scheme_updates_pg.py runs the real SQL.
"""

from __future__ import annotations

import itertools
from datetime import datetime, timezone
from typing import Optional

from app.database.repositories.notification_repository import DEFAULT_PREFS, PREF_COLUMNS, PhoneInUse


def _now():
    return datetime.now(timezone.utc)


class FakeChangeRepo:
    def __init__(self):
        self.batches: dict[str, dict] = {}
        self.changes: dict[int, dict] = {}
        self._ids = itertools.count(1)

    async def create_batch(self, batch, changes):
        self.batches[batch["id"]] = {**batch, "status": "OPEN", "detected_at": _now(), "published_at": None,
                                     "published_version": None}
        created = 0
        for c in changes:
            if any(x["fingerprint"] == c["fingerprint"] and x["status"] in ("PENDING", "APPROVED")
                   for x in self.changes.values()):
                continue
            cid = next(self._ids)
            self.changes[cid] = {**c, "id": cid, "batch_id": batch["id"], "status": "PENDING", "detected_at": _now(),
                                 "reviewed_by": None, "reviewed_at": None, "review_note": None}
            created += 1
        return self.batches[batch["id"]], created, len(changes) - created

    def _counts(self, b):
        mine = [c for c in self.changes.values() if c["batch_id"] == b["id"]]
        return {**b, **{s.lower(): sum(1 for c in mine if c["status"] == s)
                        for s in ("PENDING", "APPROVED", "REJECTED", "PUBLISHED")}, "total": len(mine)}

    async def list_batches(self, limit, offset):
        rows = sorted(self.batches.values(), key=lambda b: b["detected_at"], reverse=True)
        return [self._counts(b) for b in rows[offset:offset + limit]], len(rows)

    async def get_batch(self, batch_id):
        b = self.batches.get(batch_id)
        return self._counts(b) if b else None

    async def list_changes(self, batch_id, status, limit, offset):
        rows = [c for c in self.changes.values() if (not batch_id or c["batch_id"] == batch_id)
                and (not status or c["status"] == status)]
        rows.sort(key=lambda c: (not c["consequential"], c["scheme_id"], c["id"]))
        return rows[offset:offset + limit], len(rows)

    async def get_change(self, cid):
        return self.changes.get(cid)

    async def review(self, cid, decision, reviewer, note):
        c = self.changes.get(cid)
        if not c or c["status"] != "PENDING" or self.batches[c["batch_id"]]["status"] != "OPEN":
            return None
        c.update(status=decision, reviewed_by=reviewer, reviewed_at=_now(), review_note=note)
        return dict(c)

    async def discard_batch(self, batch_id):
        b = self.batches.get(batch_id)
        if not b or b["status"] != "OPEN":
            return False
        b["status"] = "DISCARDED"
        for c in self.changes.values():
            if c["batch_id"] == batch_id and c["status"] in ("PENDING", "APPROVED"):
                c["status"] = "DISCARDED"
        return True

    async def approved_changes(self, batch_id):
        return [dict(c) for c in self.changes.values() if c["batch_id"] == batch_id and c["status"] == "APPROVED"]

    async def mark_published(self, batch_id, version):
        b = self.batches[batch_id]
        if b["status"] != "OPEN":
            return []
        b.update(status="PUBLISHED", published_at=_now(), published_version=version)
        out = []
        for c in self.changes.values():
            if c["batch_id"] == batch_id and c["status"] == "APPROVED":
                c["status"] = "PUBLISHED"
                out.append(dict(c))
        return out


class FakeNotificationRepo:
    PhoneInUse = PhoneInUse

    def __init__(self, auth, saved, schemes=("PM_KISAN", "PMFBY", "DEDS")):
        self.auth, self.saved = auth, saved                    # FakeAuthRepo, FakeSavedRepo
        self.schemes = set(schemes)
        self.subs: set[tuple[int, str]] = set()
        self.prefs: dict[int, dict] = {}
        self.notifications: dict[int, dict] = {}
        self.deliveries: dict[int, dict] = {}
        self.phone_codes: list[dict] = []
        self._ids = itertools.count(1)

    async def list_subscriptions(self, pk):
        return [{"scheme_id": s, "scheme_name": s, "created_at": _now()} for (p, s) in sorted(self.subs) if p == pk]

    async def scheme_name(self, sid):
        return sid if sid in self.schemes else None

    async def subscribe(self, pk, sid):
        new = (pk, sid) not in self.subs
        self.subs.add((pk, sid))
        return new

    async def unsubscribe(self, pk, sid):
        if (pk, sid) in self.subs:
            self.subs.discard((pk, sid))
            return True
        return False

    async def get_prefs(self, pk):
        return {**DEFAULT_PREFS, **self.prefs.get(pk, {})}

    async def save_prefs(self, pk, changes):
        assert set(changes) <= set(PREF_COLUMNS)
        self.prefs[pk] = {**self.prefs.get(pk, {}), **changes}
        return await self.get_prefs(pk)

    async def audience(self, scheme_ids):
        interest = {(p, s) for (p, s) in self.subs if s in scheme_ids}
        interest |= {(r.farmer_id, r.scheme_id) for r in self.saved.saved.values() if r.scheme_id in scheme_ids}
        out = []
        for pk, sid in sorted(interest):
            f = self.auth.farmers.get(pk)
            if f and f.is_active:
                p = await self.get_prefs(pk)
                out.append({"scheme_id": sid, "farmer_pk": pk, **{k: p[k] for k in
                                                                 ("in_app", "email", "sms", "consequential_only")}})
        return out

    async def create_notification(self, n, channels):
        if any(x["farmer_id"] == n["farmer_pk"] and x["dedupe_key"] == n["dedupe_key"]
               for x in self.notifications.values()):
            return None
        nid = next(self._ids)
        self.notifications[nid] = {"id": nid, "farmer_id": n["farmer_pk"], "scheme_id": n["scheme_id"],
                                   "batch_id": n["batch_id"], "change_ids": n["change_ids"], "title": n["title"],
                                   "body": n["body"], "consequential": n["consequential"],
                                   "show_in_app": n["show_in_app"], "dedupe_key": n["dedupe_key"],
                                   "created_at": _now(), "read_at": None}
        for ch in channels:
            if not any(d["notification_id"] == nid and d["channel"] == ch for d in self.deliveries.values()):
                did = next(self._ids)
                self.deliveries[did] = {"id": did, "notification_id": nid, "farmer_id": n["farmer_pk"], "channel": ch,
                                        "status": "PENDING", "attempts": 0, "next_attempt_at": _now(),
                                        "last_attempt_at": None, "sent_at": None, "provider_message_id": None,
                                        "last_error": None}
        return nid

    async def inbox(self, pk, unread_only, limit, offset):
        mine = sorted((n for n in self.notifications.values() if n["farmer_id"] == pk and n["show_in_app"]),
                      key=lambda n: n["id"], reverse=True)
        rows = [n for n in mine if not unread_only or n["read_at"] is None]
        return rows[offset:offset + limit], len(rows), sum(1 for n in mine if n["read_at"] is None)

    async def mark_read(self, pk, nid):
        n = self.notifications.get(nid)
        if not n or n["farmer_id"] != pk:
            return False
        n["read_at"] = n["read_at"] or _now()
        return True

    async def mark_all_read(self, pk):
        hits = [n for n in self.notifications.values() if n["farmer_id"] == pk and n["read_at"] is None]
        for n in hits:
            n["read_at"] = _now()
        return len(hits)

    async def claim_due(self, limit):
        out = []
        for d in sorted(self.deliveries.values(), key=lambda d: (d["next_attempt_at"], d["id"])):
            if len(out) >= limit:
                break
            if d["status"] in ("PENDING", "FAILED") and d["next_attempt_at"] <= _now():
                d.update(status="SENDING", attempts=d["attempts"] + 1, last_attempt_at=_now())
                n = self.notifications[d["notification_id"]]
                f = self.auth.farmers[d["farmer_id"]]
                out.append({**d, "title": n["title"], "body": n["body"], "scheme_id": n["scheme_id"],
                            "consequential": n["consequential"], "email": f.email, "is_verified": f.is_verified,
                            "is_active": f.is_active, "phone": f.phone,
                            "phone_verified_at": getattr(f, "phone_verified_at", None)})
        return out

    async def finish(self, did, status, *, provider_message_id=None, error=None, next_attempt_at=None):
        d = self.deliveries[did]
        if d["status"] != "SENDING":
            return
        d.update(status=status, last_error=error,
                 provider_message_id=provider_message_id or d["provider_message_id"],
                 next_attempt_at=next_attempt_at or d["next_attempt_at"],
                 sent_at=_now() if status in ("SENT", "DELIVERED") else d["sent_at"])

    async def abandon_stuck(self, older_than_minutes=15):
        return 0

    async def provider_status(self, message_id, status, error):
        hits = [d for d in self.deliveries.values() if d["provider_message_id"] == message_id and d["channel"] == "SMS"
                and d["status"] in ("SENT", "DELIVERED", "UNDELIVERED")]
        for d in hits:
            d.update(status=status, last_error=error)
        return bool(hits)

    async def list_deliveries(self, status, channel, limit, offset):
        rows = [d for d in self.deliveries.values() if (not status or d["status"] == status)
                and (not channel or d["channel"] == channel)]
        return rows[offset:offset + limit], len(rows)

    async def delivery_counts(self):
        out: dict[str, int] = {}
        for d in self.deliveries.values():
            out[d["status"]] = out.get(d["status"], 0) + 1
        return out

    # phone
    async def create_phone_code(self, pk, code_hash, phone, expires_at):
        for c in self.phone_codes:
            if c["pk"] == pk:
                c["used"] = True
        self.phone_codes.append({"pk": pk, "hash": code_hash, "phone": phone, "expires_at": expires_at,
                                 "attempts": 0, "used": False})

    async def check_phone_code(self, pk, code_hash, max_attempts):
        live = [c for c in self.phone_codes if c["pk"] == pk and not c["used"] and c["expires_at"] > _now()]
        if not live:
            return "none", None
        c = live[-1]
        if c["attempts"] >= max_attempts:
            return "locked", None
        if c["hash"] != code_hash:
            c["attempts"] += 1
            return ("locked" if c["attempts"] >= max_attempts else "wrong"), None
        c["used"] = True
        if any(f.phone == c["phone"] and f.id != pk and getattr(f, "phone_verified_at", None)
               for f in self.auth.farmers.values()):
            raise PhoneInUse()
        self.auth._update(pk, phone=c["phone"], phone_verified_at=_now())
        if pk in self.prefs:
            self.prefs[pk].update(sms=False, sms_consent_at=None, sms_consent_version=None)
        return "ok", c["phone"]

    async def remove_phone(self, pk):
        self.auth._update(pk, phone=None, phone_verified_at=None)
        if pk in self.prefs:
            self.prefs[pk].update(sms=False, sms_consent_at=None, sms_opted_out_at=_now())

    async def account_pk_by_uuid(self, farmer_uuid):
        return next((f.id for f in self.auth.farmers.values() if f.farmer_id == farmer_uuid), None)

    async def account_contact(self, pk) -> Optional[dict]:
        f = self.auth.farmers.get(pk)
        return {"id": f.id, "farmer_id": f.farmer_id, "email": f.email, "is_verified": f.is_verified,
                "phone": f.phone, "phone_verified_at": getattr(f, "phone_verified_at", None)} if f else None
