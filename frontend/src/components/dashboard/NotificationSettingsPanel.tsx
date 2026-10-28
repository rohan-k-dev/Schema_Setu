"use client";

/**
 * Notification channels (docs/SCHEME_UPDATES.md): in-app, e-mail, SMS. Every rule is
 * enforced by the server — this only shows what is possible:
 *  - e-mail needs e-mail set up on the server;
 *  - SMS needs an SMS provider on the server, a phone number verified with a code,
 *    and the farmer's explicit agreement to the consent text (recorded); it can be
 *    turned off at any time (opt-out).
 */

import React, { useCallback, useEffect, useState } from "react";
import {
  apiConfirmPhone, apiGetNotificationPrefs, apiRemovePhone, apiStartPhoneVerification, apiUpdateNotificationPrefs,
  ApiError,
} from "@/lib/api";
import type { PreferencesResponse } from "@/lib/types";

export default function NotificationSettingsPanel({ onUnauthorized }: { onUnauthorized: () => void }) {
  const [data, setData] = useState<PreferencesResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [phone, setPhone] = useState("");
  const [code, setCode] = useState("");
  const [codeSent, setCodeSent] = useState<string | null>(null);
  const [consent, setConsent] = useState(false);

  const run = useCallback(async (fn: () => Promise<unknown>, done?: string) => {
    setBusy(true);
    setError(null);
    try {
      const out = await fn();
      if (out && typeof out === "object" && "preferences" in (out as object)) setData(out as PreferencesResponse);
      else setData(await apiGetNotificationPrefs());
      if (done) setNotice(done);
      return true;
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) onUnauthorized();
      else setError(err instanceof Error ? err.message : "Something went wrong.");
      return false;
    } finally {
      setBusy(false);
    }
  }, [onUnauthorized]);

  useEffect(() => { run(() => apiGetNotificationPrefs()); }, [run]);

  if (!data) {
    return <section className="dash-card" aria-label="Notification settings"><p className="dash-empty">{error ?? "Loading…"}</p></section>;
  }
  const { preferences: p, channels: c } = data;

  const toggle = (key: "in_app" | "email" | "consequential_only", value: boolean) =>
    run(() => apiUpdateNotificationPrefs({ [key]: value }), "Saved.");

  return (
    <section className="dash-card" aria-labelledby="nset-title">
      <div className="dash-card-header"><h2 id="nset-title" className="dash-card-title">⚙️ Notification settings</h2></div>
      <p className="sr-only" aria-live="polite">{notice}</p>
      {error && <div className="dash-error" role="alert">⚠️ {error}</div>}

      <fieldset className="nset-group" disabled={busy}>
        <legend className="fix-heading">How to tell you</legend>
        <label className="nset-row"><input type="checkbox" checked={p.in_app} onChange={(e) => toggle("in_app", e.target.checked)} /> In the app</label>
        <label className="nset-row">
          <input type="checkbox" checked={p.email} disabled={!p.email && !c.email_configured}
                 onChange={(e) => toggle("email", e.target.checked)} /> By e-mail
          {!c.email_configured && <span className="fix-why"> — not available on this server</span>}
        </label>
        <label className="nset-row">
          <input type="checkbox" checked={p.consequential_only} onChange={(e) => toggle("consequential_only", e.target.checked)} />
          Only important changes (eligibility, benefits, states, status)
        </label>
      </fieldset>

      <fieldset className="nset-group" disabled={busy}>
        <legend className="fix-heading">SMS</legend>
        {!c.sms_available ? (
          <p className="fix-why">SMS isn&apos;t available on this server.</p>
        ) : !c.phone_verified ? (
          <>
            <p className="fix-why">Verify your mobile number to get SMS alerts.</p>
            {!codeSent ? (
              <form className="fix-row" onSubmit={async (e) => { e.preventDefault();
                try { setBusy(true); const r = await apiStartPhoneVerification(phone); setCodeSent(r.sent_to); setError(null); }
                catch (err) { setError(err instanceof Error ? err.message : "Could not send the code."); } finally { setBusy(false); } }}>
                <label htmlFor="nset-phone" className="sr-only">Mobile number</label>
                <input id="nset-phone" value={phone} onChange={(e) => setPhone(e.target.value)} inputMode="tel"
                       placeholder="10-digit mobile number" className="fix-input" maxLength={16} autoComplete="tel" />
                <button type="submit" className="dash-edit-btn min-h-[44px]" disabled={phone.replace(/\D/g, "").length < 10}>Send code</button>
              </form>
            ) : (
              <form className="fix-row" onSubmit={async (e) => { e.preventDefault();
                if (await run(() => apiConfirmPhone(code), "Phone number verified.")) { setCodeSent(null); setCode(""); } }}>
                <label htmlFor="nset-code" className="fix-label">Code sent to {codeSent}</label>
                <input id="nset-code" value={code} onChange={(e) => setCode(e.target.value.replace(/\D/g, ""))} inputMode="numeric"
                       maxLength={6} className="fix-input fix-input--num" autoComplete="one-time-code" />
                <button type="submit" className="dash-primary-btn min-h-[44px]" disabled={code.length !== 6}>Verify</button>
              </form>
            )}
          </>
        ) : (
          <>
            <p className="fix-why">Verified number: {c.phone} · <button type="button" className="sv-link min-h-[44px]"
              onClick={() => run(() => apiRemovePhone(), "Number removed; SMS is off.")}>Remove number</button></p>
            {p.sms ? (
              <p className="nset-row">✓ SMS alerts are on (you agreed on {p.sms_consent_at ? new Date(p.sms_consent_at).toLocaleDateString("en-IN") : "—"}).
                <button type="button" className="dash-edit-btn min-h-[44px]" onClick={() => run(() => apiUpdateNotificationPrefs({ sms: false }), "SMS turned off.")}>
                  Turn off SMS</button></p>
            ) : (
              <>
                <label className="nset-row nset-consent">
                  <input type="checkbox" checked={consent} onChange={(e) => setConsent(e.target.checked)} />
                  <span>{c.sms_consent_text}</span>
                </label>
                <button type="button" className="dash-primary-btn min-h-[44px]" disabled={!consent}
                        onClick={() => run(() => apiUpdateNotificationPrefs({ sms: true, sms_consent: true }), "SMS turned on.")}>
                  Turn on SMS
                </button>
              </>
            )}
          </>
        )}
      </fieldset>
    </section>
  );
}
