"use client";

/**
 * Auth page — combined Sign In / Sign Up / Forgot Password flow.
 *
 * Route: /auth
 */

import React, { useCallback, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { useAuth } from "@/lib/AuthContext";
import { apiForgotPassword } from "@/lib/api";

type AuthMode = "login" | "register" | "forgot";

export default function AuthPage() {
  const router = useRouter();
  const { login, register, isAuthenticated, isLoading } = useAuth();

  const [mode, setMode] = useState<AuthMode>("login");
  const [formData, setFormData] = useState({
    email: "",
    password: "",
    confirmPassword: "",
    fullName: "",
    phone: "",
  });
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [showPassword, setShowPassword] = useState(false);

  // If already authenticated, redirect to dashboard
  useEffect(() => {
    if (!isLoading && isAuthenticated) {
      router.replace("/dashboard");
    }
  }, [isAuthenticated, isLoading, router]);

  const handleChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    setFormData((prev) => ({ ...prev, [e.target.name]: e.target.value }));
    setError(null);
  };

  const handleSubmit = useCallback(
    async (e: React.FormEvent) => {
      e.preventDefault();
      setError(null);
      setSuccess(null);

      if (mode === "register") {
        if (formData.password !== formData.confirmPassword) {
          setError("Passwords do not match.");
          return;
        }
        if (formData.password.length < 8) {
          setError("Password must be at least 8 characters.");
          return;
        }
      }

      setSubmitting(true);
      try {
        if (mode === "login") {
          await login({ email: formData.email, password: formData.password });
          router.push("/dashboard");
        } else if (mode === "register") {
          await register({
            email: formData.email,
            password: formData.password,
            full_name: formData.fullName || undefined,
            phone: formData.phone || undefined,
          });
          router.push("/dashboard");
        } else {
          // forgot password
          await apiForgotPassword(formData.email);
          setSuccess(
            "If that email is registered, a reset link has been sent. Check your inbox."
          );
        }
      } catch (err: unknown) {
        setError(err instanceof Error ? err.message : "Something went wrong. Please try again.");
      } finally {
        setSubmitting(false);
      }
    },
    [mode, formData, login, register, router]
  );

  if (isLoading) {
    return (
      <div className="auth-page-loading">
        <div className="auth-spinner" />
      </div>
    );
  }

  return (
    <div className="auth-page">
      {/* Decorative background */}
      <div className="auth-bg-overlay" aria-hidden="true" />

      <div className="auth-card">
        {/* Logo */}
        <div className="auth-logo">
          <span className="auth-logo-icon">🌾</span>
          <div>
            <h1 className="auth-logo-title">SchemeSetu</h1>
            <p className="auth-logo-sub">AI-Powered Scheme Discovery</p>
          </div>
        </div>

        {/* Tab switcher */}
        {mode !== "forgot" && (
          <div className="auth-tabs" role="tablist">
            <button
              role="tab"
              aria-selected={mode === "login"}
              className={`auth-tab min-h-[44px] ${mode === "login" ? "auth-tab--active" : ""}`}
              onClick={() => { setMode("login"); setError(null); setSuccess(null); }}
            >
              Sign In
            </button>
            <button
              role="tab"
              aria-selected={mode === "register"}
              className={`auth-tab min-h-[44px] ${mode === "register" ? "auth-tab--active" : ""}`}
              onClick={() => { setMode("register"); setError(null); setSuccess(null); }}
            >
              Create Account
            </button>
          </div>
        )}

        {mode === "forgot" && (
          <div className="auth-back-row">
            <button
              onClick={() => { setMode("login"); setError(null); setSuccess(null); }}
              className="auth-back-btn min-h-[44px]"
            >
              ← Back to Sign In
            </button>
            <h2 className="auth-form-title">Reset Password</h2>
          </div>
        )}

        {/* Form */}
        <form onSubmit={handleSubmit} className="auth-form" noValidate>
          {/* Full name (register only) */}
          {mode === "register" && (
            <div className="auth-field">
              <label htmlFor="fullName" className="auth-label">Full Name</label>
              <input
                id="fullName"
                name="fullName"
                type="text"
                autoComplete="name"
                placeholder="Ramesh Kumar"
                value={formData.fullName}
                onChange={handleChange}
                className="auth-input"
              />
            </div>
          )}

          {/* Email */}
          <div className="auth-field">
            <label htmlFor="email" className="auth-label">
              Email Address <span className="auth-required">*</span>
            </label>
            <input
              id="email"
              name="email"
              type="email"
              autoComplete="email"
              required
              placeholder="farmer@example.com"
              value={formData.email}
              onChange={handleChange}
              className="auth-input"
            />
          </div>

          {/* Phone (register only) */}
          {mode === "register" && (
            <div className="auth-field">
              <label htmlFor="phone" className="auth-label">Phone (optional)</label>
              <input
                id="phone"
                name="phone"
                type="tel"
                autoComplete="tel"
                placeholder="+91 9876543210"
                value={formData.phone}
                onChange={handleChange}
                className="auth-input"
              />
            </div>
          )}

          {/* Password */}
          {mode !== "forgot" && (
            <div className="auth-field">
              <label htmlFor="password" className="auth-label">
                Password <span className="auth-required">*</span>
              </label>
              <div className="auth-password-wrap">
                <input
                  id="password"
                  name="password"
                  type={showPassword ? "text" : "password"}
                  autoComplete={mode === "login" ? "current-password" : "new-password"}
                  required
                  placeholder="Min 8 characters"
                  value={formData.password}
                  onChange={handleChange}
                  className="auth-input auth-input--password"
                />
                <button
                  type="button"
                  className="auth-show-password min-h-[44px]"
                  onClick={() => setShowPassword((p) => !p)}
                  aria-label={showPassword ? "Hide password" : "Show password"}
                >
                  {showPassword ? "🙈" : "👁️"}
                </button>
              </div>
              {mode === "login" && (
                <button
                  type="button"
                  className="auth-forgot-link min-h-[44px]"
                  onClick={() => { setMode("forgot"); setError(null); setSuccess(null); }}
                >
                  Forgot password?
                </button>
              )}
            </div>
          )}

          {/* Confirm password (register only) */}
          {mode === "register" && (
            <div className="auth-field">
              <label htmlFor="confirmPassword" className="auth-label">
                Confirm Password <span className="auth-required">*</span>
              </label>
              <input
                id="confirmPassword"
                name="confirmPassword"
                type={showPassword ? "text" : "password"}
                autoComplete="new-password"
                required
                placeholder="Repeat password"
                value={formData.confirmPassword}
                onChange={handleChange}
                className="auth-input"
              />
            </div>
          )}

          {/* Error / Success */}
          {error && (
            <div className="auth-alert auth-alert--error" role="alert">
              ⚠️ {error}
            </div>
          )}
          {success && (
            <div className="auth-alert auth-alert--success" role="status">
              ✅ {success}
            </div>
          )}

          {/* Submit */}
          <button
            type="submit"
            disabled={submitting}
            className="auth-submit min-h-[44px]"
          >
            {submitting ? (
              <span className="auth-btn-loading">
                <span className="auth-spinner-sm" />
                {mode === "login" ? "Signing in…" : mode === "register" ? "Creating account…" : "Sending…"}
              </span>
            ) : (
              mode === "login" ? "Sign In" : mode === "register" ? "Create Account" : "Send Reset Link"
            )}
          </button>

          {/* Footer note for register */}
          {mode === "register" && (
            <p className="auth-terms">
              By creating an account you agree that your data will be used to
              personalise scheme recommendations. You can delete your data at any time.
            </p>
          )}
        </form>
      </div>

      <style>{`
        .auth-page {
          min-height: 100vh;
          display: flex;
          align-items: center;
          justify-content: center;
          background: linear-gradient(135deg, #064e3b 0%, #065f46 40%, #047857 70%, #059669 100%);
          padding: 1rem;
          position: relative;
          overflow: hidden;
          font-family: var(--font-geist-sans, sans-serif);
        }
        .auth-page-loading {
          min-height: 100vh;
          display: flex;
          align-items: center;
          justify-content: center;
          background: #064e3b;
        }
        .auth-bg-overlay {
          position: absolute;
          inset: 0;
          background:
            radial-gradient(ellipse 80% 60% at 20% 20%, rgba(16,185,129,0.25) 0%, transparent 60%),
            radial-gradient(ellipse 60% 80% at 80% 80%, rgba(5,150,105,0.3) 0%, transparent 60%);
          pointer-events: none;
        }
        .auth-card {
          position: relative;
          z-index: 1;
          background: rgba(255,255,255,0.97);
          backdrop-filter: blur(20px);
          border-radius: 1.5rem;
          box-shadow: 0 25px 60px rgba(0,0,0,0.35), 0 0 0 1px rgba(255,255,255,0.2);
          padding: 2.5rem 2rem;
          width: 100%;
          max-width: 440px;
          animation: authCardIn 0.4s cubic-bezier(.22,1,.36,1);
        }
        @keyframes authCardIn {
          from { opacity:0; transform:translateY(24px) scale(0.97); }
          to   { opacity:1; transform:translateY(0) scale(1); }
        }
        .auth-logo {
          display: flex;
          align-items: center;
          gap: 0.75rem;
          margin-bottom: 1.75rem;
        }
        .auth-logo-icon {
          font-size: 2.5rem;
          line-height: 1;
          filter: drop-shadow(0 2px 4px rgba(0,0,0,0.2));
        }
        .auth-logo-title {
          font-size: 1.5rem;
          font-weight: 800;
          color: #064e3b;
          margin: 0;
          letter-spacing: -0.02em;
        }
        .auth-logo-sub {
          font-size: 0.72rem;
          color: #6b7280;
          margin: 0;
          font-weight: 500;
        }
        .auth-tabs {
          display: flex;
          background: #f3f4f6;
          border-radius: 0.75rem;
          padding: 0.25rem;
          margin-bottom: 1.5rem;
          gap: 0.25rem;
        }
        .auth-tab {
          flex: 1;
          padding: 0.6rem 1rem;
          border: none;
          background: transparent;
          border-radius: 0.5rem;
          font-size: 0.875rem;
          font-weight: 600;
          color: #6b7280;
          cursor: pointer;
          transition: all 0.2s;
        }
        .auth-tab--active {
          background: white;
          color: #064e3b;
          box-shadow: 0 1px 4px rgba(0,0,0,0.12);
        }
        .auth-back-row {
          margin-bottom: 1.25rem;
        }
        .auth-back-btn {
          background: none;
          border: none;
          color: #059669;
          font-size: 0.85rem;
          font-weight: 600;
          cursor: pointer;
          padding: 0;
          margin-bottom: 0.5rem;
        }
        .auth-back-btn:hover { text-decoration: underline; }
        .auth-form-title {
          font-size: 1.25rem;
          font-weight: 700;
          color: #111827;
          margin: 0;
        }
        .auth-form {
          display: flex;
          flex-direction: column;
          gap: 1rem;
        }
        .auth-field {
          display: flex;
          flex-direction: column;
          gap: 0.35rem;
        }
        .auth-label {
          font-size: 0.82rem;
          font-weight: 600;
          color: #374151;
        }
        .auth-required { color: #ef4444; }
        .auth-input {
          padding: 0.65rem 0.85rem;
          border: 1.5px solid #d1d5db;
          border-radius: 0.65rem;
          font-size: 0.9rem;
          color: #111827;
          background: #f9fafb;
          transition: border-color 0.2s, box-shadow 0.2s;
          outline: none;
          width: 100%;
          box-sizing: border-box;
        }
        .auth-input:focus {
          border-color: #059669;
          box-shadow: 0 0 0 3px rgba(5,150,105,0.15);
          background: white;
        }
        .auth-input--password { padding-right: 2.75rem; }
        .auth-password-wrap {
          position: relative;
        }
        .auth-show-password {
          position: absolute;
          right: 0.6rem;
          top: 50%;
          transform: translateY(-50%);
          background: none;
          border: none;
          cursor: pointer;
          font-size: 1rem;
          line-height: 1;
          padding: 0.25rem;
          color: #6b7280;
        }
        .auth-forgot-link {
          align-self: flex-end;
          background: none;
          border: none;
          color: #059669;
          font-size: 0.8rem;
          font-weight: 600;
          cursor: pointer;
          padding: 0;
          margin-top: 0.2rem;
        }
        .auth-forgot-link:hover { text-decoration: underline; }
        .auth-alert {
          padding: 0.7rem 0.9rem;
          border-radius: 0.65rem;
          font-size: 0.85rem;
          font-weight: 500;
        }
        .auth-alert--error {
          background: #fef2f2;
          color: #991b1b;
          border: 1px solid #fecaca;
        }
        .auth-alert--success {
          background: #f0fdf4;
          color: #166534;
          border: 1px solid #bbf7d0;
        }
        .auth-submit {
          margin-top: 0.5rem;
          padding: 0.8rem 1rem;
          background: linear-gradient(135deg, #059669 0%, #047857 100%);
          color: white;
          border: none;
          border-radius: 0.75rem;
          font-size: 0.95rem;
          font-weight: 700;
          cursor: pointer;
          transition: all 0.2s;
          box-shadow: 0 4px 12px rgba(5,150,105,0.35);
          min-height: 48px;
        }
        .auth-submit:hover:not(:disabled) {
          background: linear-gradient(135deg, #047857 0%, #065f46 100%);
          box-shadow: 0 6px 16px rgba(5,150,105,0.45);
          transform: translateY(-1px);
        }
        .auth-submit:active:not(:disabled) { transform: translateY(0); }
        .auth-submit:disabled { opacity: 0.65; cursor: not-allowed; transform: none; }
        .auth-btn-loading {
          display: flex;
          align-items: center;
          justify-content: center;
          gap: 0.5rem;
        }
        .auth-terms {
          font-size: 0.75rem;
          color: #9ca3af;
          text-align: center;
          margin: 0;
          line-height: 1.5;
        }
        .auth-spinner {
          width: 2.5rem;
          height: 2.5rem;
          border: 3px solid rgba(255,255,255,0.3);
          border-top-color: white;
          border-radius: 50%;
          animation: spin 0.7s linear infinite;
        }
        .auth-spinner-sm {
          width: 1rem;
          height: 1rem;
          border: 2px solid rgba(255,255,255,0.4);
          border-top-color: white;
          border-radius: 50%;
          animation: spin 0.7s linear infinite;
          display: inline-block;
        }
        @keyframes spin { to { transform: rotate(360deg); } }
      `}</style>
    </div>
  );
}
