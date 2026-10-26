"use client";

/**
 * Account security — change password (signs out every other session) and
 * sign out of all devices.
 * Route: /account/security (signed in)
 */

import React, { useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useAuth } from "@/lib/AuthContext";
import { ApiError } from "@/lib/api";
import AuthLayout from "../../auth/AuthLayout";

export default function AccountSecurityPage() {
  const router = useRouter();
  const { user, isAuthenticated, isLoading, changePassword, logoutAll, handleUnauthorized } = useAuth();
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [confirm, setConfirm] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    if (!isLoading && !isAuthenticated) router.replace("/auth");
  }, [isLoading, isAuthenticated, router]);

  const fail = (err: unknown) => {
    if (err instanceof ApiError && err.status === 401) handleUnauthorized();
    setError(err instanceof Error ? err.message : "Something went wrong. Please try again.");
  };

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    setSuccess(null);
    if (next !== confirm) return setError("New passwords do not match.");
    if (next.length < 8) return setError("Password must be at least 8 characters.");
    if (!/[0-9]/.test(next) || !/[A-Za-z]/.test(next))
      return setError("Password must contain at least one letter and one number.");
    setSubmitting(true);
    try {
      await changePassword(current, next);
      setCurrent(""); setNext(""); setConfirm("");
      setSuccess("Password changed. You were signed out on all other devices.");
    } catch (err) {
      fail(err);
    } finally {
      setSubmitting(false);
    }
  };

  const signOutEverywhere = async () => {
    setError(null);
    try {
      await logoutAll();
      router.push("/auth");
    } catch (err) {
      fail(err);
    }
  };

  return (
    <AuthLayout title="Account security">
      <p className="auth-terms">{user ? `Signed in as ${user.email}` : ""}</p>
      <form onSubmit={submit} className="auth-form" noValidate>
        <div className="auth-field">
          <label htmlFor="current-password" className="auth-label">Current password</label>
          <input id="current-password" type="password" autoComplete="current-password" required
                 value={current} onChange={(e) => setCurrent(e.target.value)} className="auth-input" />
        </div>
        <div className="auth-field">
          <label htmlFor="new-password" className="auth-label">New password</label>
          <input id="new-password" type="password" autoComplete="new-password" required
                 placeholder="Min 8 characters, a letter and a number" value={next}
                 onChange={(e) => setNext(e.target.value)} className="auth-input" />
        </div>
        <div className="auth-field">
          <label htmlFor="confirm-password" className="auth-label">Confirm new password</label>
          <input id="confirm-password" type="password" autoComplete="new-password" required
                 value={confirm} onChange={(e) => setConfirm(e.target.value)} className="auth-input" />
        </div>
        {error && <div className="auth-alert auth-alert--error" role="alert">⚠️ {error}</div>}
        {success && <div className="auth-alert auth-alert--success" role="status">✅ {success}</div>}
        <button type="submit" disabled={submitting} className="auth-submit min-h-[44px]">
          {submitting ? "Saving…" : "Change password"}
        </button>
        <button type="button" onClick={signOutEverywhere} className="auth-forgot-link min-h-[44px]">
          Sign out of all devices
        </button>
        <Link href="/dashboard" className="auth-forgot-link min-h-[44px]">← Back to dashboard</Link>
      </form>
    </AuthLayout>
  );
}
