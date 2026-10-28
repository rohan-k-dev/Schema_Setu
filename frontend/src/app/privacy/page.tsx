"use client";

/**
 * Privacy and Data Settings (docs/PRIVACY.md).
 *
 * Route: /privacy. Public part: every field we collect (required or optional, why, whether it is
 * stored, which external service receives it), other records and their retention, external
 * processors, and the exceptions to deletion — all served by GET /privacy/policy so the page and
 * the backend never disagree. Signed in: what is stored about you, export, and deletion (by
 * category or the whole account). Every action is checked on the server.
 */

import React, { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useAuth } from "@/lib/AuthContext";
import {
  apiClearConversations, apiClearSearchHistory, apiDeleteAccount, apiDeleteAllSavedSchemes, apiDeleteMyProfile, apiDeleteNotificationData,
  apiExportMyData, apiMyData, apiPrivacyPolicy, ApiError,
} from "@/lib/api";
import type { MyDataSummary, PrivacyField, PrivacyPolicy } from "@/lib/types";
import { useReauth } from "@/components/ReauthDialog";

const PROCESSOR_NAME: Record<string, string> = {
  groq: "AI model (Groq)", tavily: "Web search (Tavily)", sarvam: "Translation & speech (Sarvam AI)",
  email_provider: "E-mail service", sms_provider: "SMS provider",
};
const COUNT_LABEL: Record<string, string> = {
  search_history: "Recent searches", saved_schemes: "Saved schemes", followed_schemes: "Followed schemes",
  notifications: "Notifications", review_cases: "Checks by our team", open_review_cases: "…of which still open",
  sessions: "Sign-in sessions", chat_history: "Saved conversations",
};

function FieldTable({ rows, caption, profile }: { rows: PrivacyField[]; caption: string; profile: boolean }) {
  return (
    <div className="pv-tablewrap">
      <table className="pv-table">
        <caption className="sr-only">{caption}</caption>
        <thead>
          <tr>
            <th scope="col">Detail</th><th scope="col">Required?</th><th scope="col">Why we ask</th>
            {profile && <th scope="col">Used for eligibility</th>}
            {!profile && <th scope="col">Stored</th>}
            <th scope="col">Sent to an external service</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((f) => (
            <tr key={f.field}>
              <th scope="row">{f.label}</th>
              <td><span className={`pv-pill ${f.required ? "pv-pill--req" : ""}`}>{f.required ? "Required" : "Optional"}</span></td>
              <td>{f.why}</td>
              {profile && <td>{f.used_for_eligibility ? "Yes" : "No"}</td>}
              {!profile && <td>{f.stored}</td>}
              <td>
                {f.shared_with.length === 0 ? <strong>No.</strong> : <strong>{f.shared_with.map((s) => PROCESSOR_NAME[s] ?? s).join(", ")}.</strong>}{" "}
                {f.shared_note}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function YourData({ onSignedOut }: { onSignedOut: () => void }) {
  const [data, setData] = useState<MyDataSummary | null>(null);
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [confirming, setConfirming] = useState<string | null>(null);
  const [password, setPassword] = useState("");
  const [confirmText, setConfirmText] = useState("");
  const reauth = useReauth();

  const load = useCallback(async () => {
    try {
      setData(await apiMyData());
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) onSignedOut();
      else setMsg({ ok: false, text: err instanceof Error ? err.message : "Could not load your data." });
    }
  }, [onSignedOut]);

  useEffect(() => { load(); }, [load]);

  const run = async (key: string, fn: () => Promise<unknown>, done: string) => {
    setBusy(key);
    setMsg(null);
    try {
      await reauth.guard(fn);
      setMsg({ ok: true, text: done });
      setConfirming(null);
      load();
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) onSignedOut();
      else if (err instanceof ApiError && err.code === "REAUTH_CANCELLED") setMsg({ ok: false, text: "Cancelled." });
      else setMsg({ ok: false, text: err instanceof Error ? err.message : "That didn't work." });
    } finally {
      setBusy(null);
    }
  };

  const deleteAccount = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy("account");
    setMsg(null);
    try {
      await apiDeleteAccount(password, confirmText);
      setPassword("");
      window.location.href = "/privacy?deleted=1";
    } catch (err) {
      setMsg({ ok: false, text: err instanceof Error ? err.message : "Could not delete your account." });
    } finally {
      setBusy(null);
    }
  };

  const confirmButtons = (key: string, label: string, fn: () => Promise<unknown>, done: string) => (
    confirming === key ? (
      <span className="pv-row">
        <button className="pv-btn pv-btn--danger" disabled={busy !== null} onClick={() => run(key, fn, done)}>
          {busy === key ? "Deleting…" : `Yes, ${label.toLowerCase()}`}
        </button>
        <button className="pv-btn pv-btn--ghost" onClick={() => setConfirming(null)}>Cancel</button>
      </span>
    ) : (
      <button className="pv-btn pv-btn--ghost" disabled={busy !== null} onClick={() => setConfirming(key)}>{label}</button>
    )
  );

  return (
    <section className="pv-card" aria-labelledby="yours-title" id="your-data">
      <h2 id="yours-title" className="pv-h2">Your data</h2>
      {msg && <p className={msg.ok ? "pv-ok" : "pv-warn"} role={msg.ok ? "status" : "alert"}>{msg.text}</p>}
      {!data ? <p role="status">Loading…</p> : (
        <>
          <dl className="pv-dl">
            <dt>Saved profile</dt>
            <dd>{data.has_profile
              ? `Yes — ${data.profile_fields_filled.length} detail(s) filled; consent given ${data.consent_given_at ? new Date(data.consent_given_at).toLocaleDateString("en-IN") : ""}`
              : "No profile saved (the chat neither loads nor saves your details)."}</dd>
            {Object.entries(data.counts).map(([k, v]) => <React.Fragment key={k}><dt>{COUNT_LABEL[k] ?? k}</dt><dd>{v}</dd></React.Fragment>)}
            <dt>Mobile number</dt><dd>{data.has_phone ? "Saved" : "None"}</dd>
          </dl>
          {Object.keys(data.errors).length > 0 && <p className="pv-warn" role="alert">Some parts couldn&apos;t be loaded: {Object.keys(data.errors).join(", ")}.</p>}

          <h3 className="pv-h3">View, edit and download</h3>
          <div className="pv-row">
            <Link className="pv-btn pv-btn--ghost" href="/profile">View or edit your profile</Link>
            <Link className="pv-btn pv-btn--ghost" href="/dashboard">Saved schemes, searches and notifications</Link>
            <button className="pv-btn" disabled={busy !== null}
                    onClick={() => run("export", apiExportMyData, "Your data was downloaded as schemesetu-my-data.json.")}>
              {busy === "export" ? "Preparing…" : "Download all my data (JSON)"}
            </button>
          </div>

          <h3 className="pv-h3">Delete</h3>
          <ul className="pv-deletes">
            <li>
              <div><strong>Profile and consent.</strong> Deletes your saved details and the searches kept with them. The chat
                stops using or saving your details, and searches are no longer recorded.</div>
              {confirmButtons("profile", "Delete profile", apiDeleteMyProfile, "Your profile and search history were deleted.")}
            </li>
            <li>
              <div><strong>Search history</strong> only.</div>
              {confirmButtons("history", "Delete search history", apiClearSearchHistory, "Your search history was deleted.")}
            </li>
            <li>
              <div><strong>Chat history</strong>: all your saved conversations (<Link href="/history">view them</Link>).</div>
              {confirmButtons("chats", "Delete chat history", apiClearConversations, "Your chat history was deleted.")}
            </li>
            <li>
              <div><strong>Saved schemes</strong> with their checklists, notes and references.</div>
              {confirmButtons("saved", "Delete saved schemes", apiDeleteAllSavedSchemes, "Your saved schemes were deleted.")}
            </li>
            <li>
              <div><strong>Notification data:</strong> settings and SMS consent, followed schemes, messages (queued ones are
                not sent) and your mobile number.</div>
              {confirmButtons("notifications", "Delete notification data", apiDeleteNotificationData, "Your notification data was deleted.")}
            </li>
          </ul>

          <div className="pv-danger" aria-labelledby="danger-title">
            <h3 id="danger-title" className="pv-h3">Delete your account</h3>
            <p>This deletes your account and everything above, signs you out everywhere, and removes your question and
              details from any check by our team (the anonymous check is kept). It can&apos;t be undone. What we still
              keep is listed under &ldquo;When deletion is delayed or limited&rdquo; below.</p>
            <form onSubmit={deleteAccount} className="pv-form">
              <label htmlFor="pv-password" className="pv-label">Your password</label>
              <input id="pv-password" type="password" autoComplete="current-password" required className="pv-input"
                     value={password} onChange={(e) => setPassword(e.target.value)} />
              <label htmlFor="pv-confirm" className="pv-label">Type <strong>DELETE MY ACCOUNT</strong> to confirm</label>
              <input id="pv-confirm" required className="pv-input" value={confirmText} autoComplete="off"
                     onChange={(e) => setConfirmText(e.target.value)} />
              <button type="submit" className="pv-btn pv-btn--danger"
                      disabled={busy !== null || !password || confirmText.trim().toUpperCase() !== "DELETE MY ACCOUNT"}>
                {busy === "account" ? "Deleting…" : "Delete my account"}
              </button>
            </form>
          </div>
        </>
      )}
      {reauth.dialog}
    </section>
  );
}

export default function PrivacyPage() {
  const router = useRouter();
  const { isAuthenticated, isLoading, handleUnauthorized } = useAuth();
  const [policy, setPolicy] = useState<PrivacyPolicy | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [deleted, setDeleted] = useState(false);

  useEffect(() => {
    setDeleted(new URLSearchParams(window.location.search).get("deleted") === "1");
    apiPrivacyPolicy().then(setPolicy).catch((e) => setError(e instanceof Error ? e.message : "Could not load."));
  }, []);

  const signedOut = useCallback(() => { handleUnauthorized(); }, [handleUnauthorized]);

  return (
    <div className="pv-page">
      <header className="pv-header">
        <span className="pv-brand">🌾 SchemeSetu · Privacy and data</span>
        <nav className="pv-row">
          <button className="pv-btn pv-btn--light" onClick={() => router.push(isAuthenticated ? "/dashboard" : "/")}>
            {isAuthenticated ? "Dashboard" : "Home"}
          </button>
        </nav>
      </header>
      <main className="pv-main">
        <h1 className="pv-h1">Privacy and data settings</h1>
        {deleted && <p className="pv-ok" role="status">Your account and its data were deleted. Thank you for using SchemeSetu.</p>}
        <p className="pv-lead">What SchemeSetu collects, why, where it goes, how long we keep it — and how you can see,
          download or delete it.</p>

        {!isLoading && isAuthenticated && <YourData onSignedOut={signedOut} />}
        {!isLoading && !isAuthenticated && !deleted && (
          <p className="pv-card"><Link href="/auth" className="pv-a">Sign in</Link> to see, download or delete your own data.</p>
        )}

        {error && <p className="pv-warn" role="alert">{error}</p>}
        {!policy ? (!error && <p role="status">Loading…</p>) : (
          <>
            <section className="pv-card" aria-labelledby="matching-title">
              <h2 id="matching-title" className="pv-h2">How your details are used</h2>
              <p>{policy.required_note}</p>
              <p>Eligibility is decided by fixed rules from each scheme&apos;s official guidelines, checked on our server —
                the AI model never decides it. Each rule compares one detail (for example &ldquo;age between 18 and 40&rdquo;
                or &ldquo;state is Karnataka&rdquo;) with your profile. The more relevant details you give, the more schemes
                can be answered with eligible / not eligible instead of &ldquo;needs more information&rdquo;. Your state and
                crop also narrow the scheme search.</p>
            </section>

            <section className="pv-card" aria-labelledby="profile-title">
              <h2 id="profile-title" className="pv-h2">Farmer profile details</h2>
              <p className="pv-muted">All stored in your saved profile, only after you consent, until you delete it.</p>
              <FieldTable rows={policy.profile_fields} caption="Farmer profile details" profile />
              <p className="pv-note">⚠️ {policy.chat_note}</p>
              <h3 className="pv-h3">What we never collect</h3>
              <ul className="pv-list">{policy.not_collected.map((x) => <li key={x}>{x}</li>)}</ul>
            </section>

            <section className="pv-card" aria-labelledby="account-title">
              <h2 id="account-title" className="pv-h2">Account details</h2>
              <FieldTable rows={policy.account_fields} caption="Account details" profile={false} />
            </section>

            <section className="pv-card" aria-labelledby="records-title">
              <h2 id="records-title" className="pv-h2">Other records and how long we keep them</h2>
              <div className="pv-tablewrap">
                <table className="pv-table">
                  <caption className="sr-only">Other records and retention</caption>
                  <thead><tr><th scope="col">Record</th><th scope="col">What</th><th scope="col">When</th><th scope="col">Kept</th><th scope="col">You can</th></tr></thead>
                  <tbody>{policy.records.map((r) => (
                    <tr key={r.record}><th scope="row">{r.label}</th><td>{r.what}</td><td>{r.when}</td><td>{r.retention}</td><td>{r.you_can}</td></tr>
                  ))}</tbody>
                </table>
              </div>
            </section>

            <section className="pv-card" aria-labelledby="proc-title">
              <h2 id="proc-title" className="pv-h2">External services that process your data</h2>
              <p>{policy.processor_note}</p>
              <div className="pv-tablewrap">
                <table className="pv-table">
                  <caption className="sr-only">External services</caption>
                  <thead><tr><th scope="col">Service</th><th scope="col">What it&apos;s for</th><th scope="col">What it receives</th><th scope="col">When</th><th scope="col">On this server</th></tr></thead>
                  <tbody>{policy.processors.map((p) => (
                    <tr key={p.id}><th scope="row">{p.name}</th><td>{p.purpose}</td><td>{p.receives}</td><td>{p.when}</td>
                      <td>{p.configured ? "In use" : "Not configured"}</td></tr>
                  ))}</tbody>
                </table>
              </div>
            </section>

            <section className="pv-card" aria-labelledby="exc-title">
              <h2 id="exc-title" className="pv-h2">When deletion is delayed or limited</h2>
              <div className="pv-tablewrap">
                <table className="pv-table">
                  <caption className="sr-only">Deletion exceptions</caption>
                  <thead><tr><th scope="col">What</th><th scope="col">Why</th><th scope="col">How long</th></tr></thead>
                  <tbody>{policy.exceptions.map((x) => (
                    <tr key={x.what}><th scope="row">{x.what}</th><td>{x.why}</td><td>{x.how_long}</td></tr>
                  ))}</tbody>
                </table>
              </div>
            </section>
          </>
        )}
      </main>
      <style>{`
        .pv-page { min-height: 100vh; background: #f0fdf4; color: #0f172a; font-family: var(--font-geist-sans, sans-serif); }
        .pv-header { display: flex; justify-content: space-between; align-items: center; gap: 1rem; flex-wrap: wrap;
          background: #064e3b; color: white; padding: 0.75rem 1.25rem; }
        .pv-brand { font-weight: 800; }
        .pv-main { max-width: 1100px; margin: 0 auto; padding: 1.25rem 1rem 3rem; display: flex; flex-direction: column; gap: 1rem; }
        .pv-h1 { font-size: 1.4rem; font-weight: 800; margin: 0; }
        .pv-h2 { font-size: 1.1rem; font-weight: 800; margin: 0 0 0.6rem; }
        .pv-h3 { font-size: 0.92rem; font-weight: 700; margin: 1rem 0 0.4rem; }
        .pv-lead { margin: 0; color: #334155; }
        .pv-card { background: white; border: 1px solid #d1fae5; border-radius: 0.9rem; padding: 1rem 1.25rem; min-width: 0; margin: 0; }
        .pv-card p { font-size: 0.9rem; line-height: 1.55; }
        .pv-muted { color: #475569; font-size: 0.85rem; }
        .pv-note { background: #fffbeb; border: 1px solid #fde68a; color: #78350f; border-radius: 0.6rem; padding: 0.5rem 0.75rem; }
        .pv-tablewrap { overflow-x: auto; }
        .pv-table { width: 100%; border-collapse: collapse; font-size: 0.84rem; min-width: 640px; }
        .pv-table th, .pv-table td { text-align: left; vertical-align: top; padding: 0.45rem 0.55rem; border-bottom: 1px solid #e2e8f0; }
        .pv-table thead th { background: #f8fafc; color: #334155; }
        .pv-pill { display: inline-block; border-radius: 99px; padding: 0.05rem 0.5rem; font-size: 0.74rem; font-weight: 700; background: #e2e8f0; color: #334155; white-space: nowrap; }
        .pv-pill--req { background: #fee2e2; color: #991b1b; }
        .pv-list { margin: 0; padding-left: 1.1rem; font-size: 0.88rem; }
        .pv-dl { display: grid; grid-template-columns: auto 1fr; gap: 0.3rem 1rem; font-size: 0.88rem; margin: 0; }
        .pv-dl dt { color: #475569; font-weight: 600; }
        .pv-dl dd { margin: 0; }
        .pv-row { display: flex; flex-wrap: wrap; gap: 0.5rem; align-items: center; }
        .pv-deletes { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 0.6rem; }
        .pv-deletes li { display: flex; flex-wrap: wrap; justify-content: space-between; align-items: center; gap: 0.6rem;
          border: 1px solid #e2e8f0; border-radius: 0.6rem; padding: 0.6rem 0.75rem; font-size: 0.88rem; }
        .pv-deletes li > div { flex: 1; min-width: 220px; }
        .pv-danger { margin-top: 1.25rem; border: 2px solid #fecaca; background: #fef2f2; border-radius: 0.8rem; padding: 0.75rem 1rem; }
        .pv-danger p { color: #7f1d1d; }
        .pv-form { display: flex; flex-direction: column; gap: 0.4rem; max-width: 360px; }
        .pv-label { font-size: 0.84rem; font-weight: 600; }
        .pv-input { border: 1px solid #cbd5e1; border-radius: 0.5rem; padding: 0.45rem 0.6rem; min-height: 44px; font-size: 0.95rem; background: white; }
        .pv-btn { min-height: 44px; display: inline-flex; align-items: center; border: none; border-radius: 0.5rem; padding: 0.4rem 1rem;
          background: #047857; color: white; font-weight: 600; font-size: 0.86rem; cursor: pointer; text-decoration: none; }
        .pv-btn:disabled { opacity: 0.55; cursor: not-allowed; }
        .pv-btn--ghost { background: white; color: #065f46; border: 1px solid #a7f3d0; }
        .pv-btn--light { background: rgba(255,255,255,0.12); color: white; border: 1px solid rgba(255,255,255,0.35); }
        .pv-btn--danger { background: #b91c1c; color: white; }
        .pv-ok { color: #166534; background: #f0fdf4; border: 1px solid #bbf7d0; border-radius: 0.5rem; padding: 0.45rem 0.7rem; }
        .pv-warn { color: #9a3412; background: #fff7ed; border: 1px solid #fed7aa; border-radius: 0.5rem; padding: 0.45rem 0.7rem; }
        .pv-a { color: #1d4ed8; text-decoration: underline; }
        .pv-page :focus-visible { outline: 3px solid #f59e0b; outline-offset: 2px; }
      `}</style>
    </div>
  );
}
