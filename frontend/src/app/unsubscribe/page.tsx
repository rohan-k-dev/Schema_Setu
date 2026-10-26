"use client";

/**
 * One-click unsubscribe from notification e-mails (docs/SCHEME_UPDATES.md).
 * Route: /unsubscribe?token=... (the link in every notification e-mail).
 * The token is checked by the server; the farmer confirms with a button, so a mail
 * scanner that opens the link doesn't unsubscribe anyone by accident.
 */

import React, { useEffect, useState } from "react";
import Link from "next/link";
import { apiUnsubscribe } from "@/lib/api";
import AuthLayout, { takeTokenFromUrl } from "../auth/AuthLayout";

export default function UnsubscribePage() {
  const [token, setToken] = useState<string | null>(null);
  const [state, setState] = useState<"ask" | "done" | "failed">("ask");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    const t = takeTokenFromUrl();
    setToken(t);
    if (!t) setState("failed");
  }, []);

  const confirm = async () => {
    if (!token) return;
    setBusy(true);
    try { await apiUnsubscribe(token); setState("done"); } catch { setState("failed"); } finally { setBusy(false); }
  };

  return (
    <AuthLayout title="E-mail notifications">
      <div className="auth-form">
        {state === "ask" && (
          <>
            <p className="auth-terms">Stop SchemeSetu e-mails about scheme updates? In-app notifications stay on.</p>
            <button onClick={confirm} disabled={busy || !token} className="auth-submit min-h-[44px]">
              {busy ? "Saving…" : "Yes, stop these e-mails"}
            </button>
          </>
        )}
        {state === "done" && (
          <div className="auth-alert auth-alert--success" role="status">
            ✅ You won&apos;t get these e-mails any more. You can turn them on again in your notification settings.
          </div>
        )}
        {state === "failed" && (
          <div className="auth-alert auth-alert--error" role="alert">
            ⚠️ This link is not valid. Sign in and change e-mail notifications in your settings.
          </div>
        )}
        <Link href="/dashboard" className="auth-terms">Go to your dashboard</Link>
      </div>
    </AuthLayout>
  );
}
