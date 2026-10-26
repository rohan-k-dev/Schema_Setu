"use client";

/**
 * E-mail verification — opened from the link in the verification e-mail.
 * Route: /verify-email?token=...
 */

import React, { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { apiVerifyEmail } from "@/lib/api";
import AuthLayout, { takeTokenFromUrl } from "../auth/AuthLayout";

export default function VerifyEmailPage() {
  const [state, setState] = useState<"working" | "done" | "failed">("working");
  const [message, setMessage] = useState("Verifying your e-mail…");
  const started = useRef(false);     // the token is single-use: never submit it twice

  useEffect(() => {
    if (started.current) return;
    started.current = true;
    const token = takeTokenFromUrl();
    if (!token) {
      setState("failed");
      setMessage("This verification link is incomplete. Open the link from your e-mail again.");
      return;
    }
    apiVerifyEmail(token)
      .then((msg) => { setState("done"); setMessage(msg); })
      .catch((err: unknown) => {
        setState("failed");
        setMessage(err instanceof Error ? err.message : "Verification failed.");
      });
  }, []);

  return (
    <AuthLayout title="Verify e-mail">
      <div className="auth-form">
        <div
          className={`auth-alert ${state === "failed" ? "auth-alert--error" : "auth-alert--success"}`}
          role={state === "failed" ? "alert" : "status"}
        >
          {state === "failed" ? "⚠️ " : state === "done" ? "✅ " : ""}{message}
        </div>
        {state !== "working" && (
          <Link href="/auth" className="auth-submit min-h-[44px]" style={{ textAlign: "center" }}>
            {state === "done" ? "Sign in" : "Back to sign in"}
          </Link>
        )}
        {state === "failed" && (
          <p className="auth-terms">
            Links expire after 24 hours and work only once. On the sign-in page you can ask for a new link.
          </p>
        )}
      </div>
    </AuthLayout>
  );
}
