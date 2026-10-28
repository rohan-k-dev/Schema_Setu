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
import { AUTH_CSS } from "./authStyles";

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
    setSuccess(null);
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
        if (!/[0-9]/.test(formData.password) || !/[A-Za-z]/.test(formData.password)) {
          setError("Password must contain at least one letter and one number.");
          return;
        }
      }
      setSubmitting(true);
      try {
        if (mode === "login") {
          await login({ email: formData.email, password: formData.password });
          router.push("/dashboard");
        } else if (mode === "register") {
          const message = await register({
            email: formData.email,
            password: formData.password,
            full_name: formData.fullName || undefined,
            phone: formData.phone || undefined,
          });
          setMode("login");
          setFormData((prev) => ({ ...prev, password: "", confirmPassword: "" }));
          setSuccess(message);
        } else {
          // forgot password (generic answer: never reveals whether the e-mail is registered)
          setSuccess(await apiForgotPassword(formData.email));
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
          {mode === "register" && (
            <p className="auth-hint">
              We ask only for your e-mail and a password. See{" "}
              <a href="/privacy" target="_blank" rel="noopener noreferrer" style={{ textDecoration: "underline" }}>
                what we keep and who processes it<span className="sr-only"> (opens in a new tab)</span></a>.
            </p>
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
          {mode === "forgot" && success && (
            <p className="auth-hint">
              If this email belongs to an account and you are running locally without SMTP, check the
              backend terminal or <code>docker compose logs backend</code> for the reset link.
            </p>
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

      <style>{AUTH_CSS}</style>
    </div>
  );
}
