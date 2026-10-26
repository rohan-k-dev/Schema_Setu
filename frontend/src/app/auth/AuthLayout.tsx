"use client";

import React from "react";
import { AUTH_CSS } from "./authStyles";

/** Card layout shared by the account pages (same look as /auth). */
export default function AuthLayout({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="auth-page">
      {/* Links in account e-mails carry a secret token: never leak the URL in a Referer header. */}
      <meta name="referrer" content="no-referrer" />
      <div className="auth-bg-overlay" aria-hidden="true" />
      <div className="auth-card">
        <div className="auth-logo">
          <span className="auth-logo-icon">🌾</span>
          <div>
            <p className="auth-logo-title">SchemeSetu</p>
            <p className="auth-logo-sub">AI-Powered Scheme Discovery</p>
          </div>
        </div>
        <h1 className="auth-form-title">{title}</h1>
        {children}
      </div>
      <style>{AUTH_CSS}</style>
    </div>
  );
}

/** Reads ?token= once, then removes it from the address bar and history. */
export function takeTokenFromUrl(): string | null {
  if (typeof window === "undefined") return null;
  const url = new URL(window.location.href);
  const token = url.searchParams.get("token");
  if (token) {
    url.searchParams.delete("token");
    window.history.replaceState(null, "", url.pathname + url.search);
  }
  return token;
}
