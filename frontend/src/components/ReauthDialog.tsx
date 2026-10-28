"use client";

/**
 * Password confirmation for sensitive actions (docs/HUMAN_REVIEW.md, Access policy).
 * The server decides when it is needed (403 REAUTH_REQUIRED); this dialog only collects the
 * password, calls POST /auth/reauthenticate and lets the caller retry the action.
 *
 *   const reauth = useReauth();
 *   await reauth.guard(() => apiReviewDecide(...));     // asks for the password if required
 *   {reauth.dialog}
 */

import React, { useCallback, useEffect, useRef, useState } from "react";
import { apiReauthenticate, ApiError, isReauthRequired } from "@/lib/api";

type Pending = { action: () => Promise<unknown>; resolve: (v: unknown) => void; reject: (e: unknown) => void };

export function useReauth() {
  const [pending, setPending] = useState<Pending | null>(null);
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const input = useRef<HTMLInputElement>(null);

  useEffect(() => { if (pending) input.current?.focus(); }, [pending]);

  const guard = useCallback(<T,>(action: () => Promise<T>): Promise<T> => {
    return action().catch((err) => {
      if (!isReauthRequired(err)) throw err;
      return new Promise<T>((resolve, reject) => {
        setPassword("");
        setError(null);
        setPending({ action, resolve: resolve as (v: unknown) => void, reject });
      });
    });
  }, []);

  const cancel = () => {
    pending?.reject(new ApiError("Cancelled: your password wasn't confirmed.", 403, "REAUTH_CANCELLED"));
    setPending(null);
    setPassword("");
  };

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!pending) return;
    setBusy(true);
    setError(null);
    try {
      await apiReauthenticate(password);
      setPassword("");
      const p = pending;
      setPending(null);
      p.action().then(p.resolve, p.reject);
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) {
        pending.reject(err);                       // session ended (too many wrong passwords)
        setPending(null);
      } else {
        setError(err instanceof Error ? err.message : "That didn't work. Try again.");
        input.current?.focus();
      }
    } finally {
      setBusy(false);
    }
  };

  const dialog = pending ? (
    <div className="ra-backdrop" onKeyDown={(e) => { if (e.key === "Escape") cancel(); }}>
      <form role="dialog" aria-modal="true" aria-labelledby="ra-title" aria-describedby="ra-desc" className="ra-dialog" onSubmit={submit}>
        <h2 id="ra-title" className="ra-title">Confirm it&apos;s you</h2>
        <p id="ra-desc" className="ra-text">For your security, enter your password to complete this action.</p>
        <label htmlFor="ra-password" className="ra-label">Password</label>
        <input id="ra-password" ref={input} type="password" autoComplete="current-password" required
               className="ra-input" value={password} onChange={(e) => setPassword(e.target.value)} />
        {error && <p className="ra-error" role="alert">{error}</p>}
        <div className="ra-actions">
          <button type="submit" className="ra-btn" disabled={busy || !password}>{busy ? "Checking…" : "Confirm"}</button>
          <button type="button" className="ra-btn ra-btn--ghost" onClick={cancel} disabled={busy}>Cancel</button>
        </div>
      </form>
      <style>{`
        .ra-backdrop { position: fixed; inset: 0; background: rgba(15,23,42,0.55); display: flex; align-items: center;
          justify-content: center; padding: 1rem; z-index: 100; }
        .ra-dialog { background: white; color: #0f172a; border-radius: 0.9rem; padding: 1.25rem; width: 100%; max-width: 380px;
          display: flex; flex-direction: column; gap: 0.5rem; box-shadow: 0 20px 40px rgba(0,0,0,0.25); }
        .ra-title { font-size: 1.05rem; font-weight: 800; margin: 0; }
        .ra-text { font-size: 0.85rem; color: #475569; margin: 0; }
        .ra-label { font-size: 0.82rem; font-weight: 600; }
        .ra-input { border: 1px solid #cbd5e1; border-radius: 0.5rem; padding: 0.45rem 0.6rem; min-height: 44px; font-size: 0.95rem; }
        .ra-error { color: #b91c1c; font-size: 0.82rem; margin: 0; }
        .ra-actions { display: flex; gap: 0.5rem; margin-top: 0.25rem; }
        .ra-btn { min-height: 44px; border: none; border-radius: 0.5rem; padding: 0.4rem 1rem; background: #4338ca; color: white;
          font-weight: 600; cursor: pointer; }
        .ra-btn:disabled { opacity: 0.55; cursor: not-allowed; }
        .ra-btn--ghost { background: white; color: #3730a3; border: 1px solid #c7d2fe; }
        .ra-dialog :focus-visible { outline: 3px solid #f59e0b; outline-offset: 2px; }
      `}</style>
    </div>
  ) : null;

  return { guard, dialog };
}
