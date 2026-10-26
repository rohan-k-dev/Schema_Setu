"use client";

/**
 * Password reset — opened from the link in the reset e-mail.
 * Route: /reset-password?token=...
 * A successful reset signs the account out on every device.
 */

import React, { useEffect, useState } from "react";
import Link from "next/link";
import { apiResetPassword } from "@/lib/api";
import { useAuth } from "@/lib/AuthContext";
import AuthLayout, { takeTokenFromUrl } from "../auth/AuthLayout";

export default function ResetPasswordPage() {
  const { handleUnauthorized } = useAuth();
  const [token, setToken] = useState<string | null>(null);
  const [loaded, setLoaded] = useState(false);
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    setToken(takeTokenFromUrl());
    setLoaded(true);
  }, []);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    if (password !== confirm) return setError("Passwords do not match.");
    if (password.length < 8) return setError("Password must be at least 8 characters.");
    if (!/[0-9]/.test(password) || !/[A-Za-z]/.test(password))
      return setError("Password must contain at least one letter and one number.");
    if (!token) return;
    setSubmitting(true);
    try {
      setDone(await apiResetPassword(token, password));
      handleUnauthorized();              // every session was revoked by the server
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Password reset failed.");
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <AuthLayout title="Choose a new password">
      {loaded && !token && !done ? (
        <div className="auth-form">
          <div className="auth-alert auth-alert--error" role="alert">
            ⚠️ This reset link is incomplete. Open the link from your e-mail again, or request a new one.
          </div>
          <Link href="/auth" className="auth-submit min-h-[44px]" style={{ textAlign: "center" }}>
            Back to sign in
          </Link>
        </div>
      ) : done ? (
        <div className="auth-form">
          <div className="auth-alert auth-alert--success" role="status">✅ {done}</div>
          <Link href="/auth" className="auth-submit min-h-[44px]" style={{ textAlign: "center" }}>
            Sign in
          </Link>
        </div>
      ) : (
        <form onSubmit={submit} className="auth-form" noValidate>
          <div className="auth-field">
            <label htmlFor="new-password" className="auth-label">New password</label>
            <input id="new-password" type="password" autoComplete="new-password" required
                   placeholder="Min 8 characters, a letter and a number" value={password}
                   onChange={(e) => setPassword(e.target.value)} className="auth-input" />
          </div>
          <div className="auth-field">
            <label htmlFor="confirm-password" className="auth-label">Confirm new password</label>
            <input id="confirm-password" type="password" autoComplete="new-password" required
                   value={confirm} onChange={(e) => setConfirm(e.target.value)} className="auth-input" />
          </div>
          {error && <div className="auth-alert auth-alert--error" role="alert">⚠️ {error}</div>}
          <button type="submit" disabled={submitting || !token} className="auth-submit min-h-[44px]">
            {submitting ? "Saving…" : "Set new password"}
          </button>
          <p className="auth-terms">For your security you will be signed out on all devices.</p>
        </form>
      )}
    </AuthLayout>
  );
}
