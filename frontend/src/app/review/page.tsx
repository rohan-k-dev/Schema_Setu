"use client";

/**
 * Reviewer dashboard (docs/HUMAN_REVIEW.md).
 *
 * Route: /review. Signed out → /auth. APPROVED REVIEWER accounts see their own and granted cases
 * in full and the unassigned queue as summaries (take a case to see its details); ADMIN accounts
 * see everything, assign and grant, but don't decide. The server checks every request
 * (docs/HUMAN_REVIEW.md, Access policy); nothing here is protected by hiding it.
 */

import React, { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useAuth } from "@/lib/AuthContext";
import { apiReviewCases, apiReviewClaim, ApiError } from "@/lib/api";
import type { ReviewCaseStatus, ReviewCaseSummary, ReviewStats } from "@/lib/types";
import CaseDetail, { fmt, REASON_LABEL, STATUS_LABEL } from "@/components/review/CaseDetail";

const PAGE = 15;
const TABS: { key: ReviewCaseStatus | null; stat: keyof ReviewStats }[] = [
  { key: "PENDING", stat: "pending" }, { key: "IN_REVIEW", stat: "in_review" },
  { key: "RESOLVED", stat: "resolved" }, { key: "DISMISSED", stat: "dismissed" }, { key: null, stat: "total" },
];

export default function ReviewPage() {
  const router = useRouter();
  const { isAuthenticated, isLoading, user, handleUnauthorized } = useAuth();
  const [status, setStatus] = useState<ReviewCaseStatus | null>("PENDING");
  const [reason, setReason] = useState("");
  const [assigned, setAssigned] = useState<"" | "me" | "unassigned">("");
  const [offset, setOffset] = useState(0);
  const [cases, setCases] = useState<ReviewCaseSummary[]>([]);
  const [total, setTotal] = useState(0);
  const [stats, setStats] = useState<ReviewStats | null>(null);
  const [selected, setSelected] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [forbidden, setForbidden] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [taking, setTaking] = useState(false);
  const [takeMsg, setTakeMsg] = useState<string | null>(null);

  useEffect(() => {
    if (!isLoading && !isAuthenticated) router.replace("/auth");
  }, [isAuthenticated, isLoading, router]);

  const fail = useCallback((err: unknown) => {
    if (err instanceof ApiError && err.status === 401) handleUnauthorized();
    else if (err instanceof ApiError && err.status === 403 && err.code === "FORBIDDEN") setForbidden(true);
    else setError(err instanceof Error ? err.message : "Something went wrong.");
  }, [handleUnauthorized]);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const d = await apiReviewCases({ status, reason: reason || null, assigned: assigned || null, limit: PAGE, offset });
      setCases(d.cases);
      setTotal(d.total);
      setStats(d.stats);
    } catch (err) {
      fail(err);
    } finally {
      setLoading(false);
    }
  }, [status, reason, assigned, offset, fail]);

  useEffect(() => { if (isAuthenticated) load(); }, [isAuthenticated, load]);

  const me = user?.email ?? "";
  const picked = cases.find((x) => x.case_id === selected) ?? null;

  const take = async (c: ReviewCaseSummary) => {
    setTaking(true);
    setTakeMsg(null);
    try {
      await apiReviewClaim(c.case_id, c.version);
      await load();
      setSelected(c.case_id);
    } catch (err) {
      if (err instanceof ApiError && (err.status === 409 || err.status === 404)) {
        setTakeMsg("Someone else has just taken this case.");
        setSelected(null);
        load();
      } else fail(err);
    } finally {
      setTaking(false);
    }
  };
  const canDecide = user?.role === "REVIEWER";
  const canAssign = user?.role === "ADMIN";

  if (forbidden) {
    return (
      <div className="rv-page"><main className="rv-main">
        <section className="rv-card" role="alert">
          <h1 className="rv-h1">Reviewer access required</h1>
          <p>Your account doesn&apos;t have permission to see the review queue.</p>
          <Link href="/dashboard" className="rv-btn rv-btn--ghost">← Back to your dashboard</Link>
        </section>
      </main><Styles /></div>
    );
  }

  const page = Math.floor(offset / PAGE) + 1;
  const pages = Math.max(1, Math.ceil(total / PAGE));

  return (
    <div className="rv-page">
      <header className="rv-header">
        <span className="rv-brand">🌾 SchemeSetu · Review queue</span>
        <nav className="rv-row">
          <button onClick={load} disabled={loading} className="rv-btn rv-btn--light">{loading ? "Refreshing…" : "Refresh"}</button>
          <Link href="/dashboard" className="rv-btn rv-btn--light">Dashboard</Link>
        </nav>
      </header>
      <main className="rv-main">
        <h1 className="rv-h1">Cases for human review</h1>
        <p className="rv-muted">
          Raised automatically when eligibility can&apos;t be verified, rules or sources conflict, or retrieval channels fail.
          Your decision is recorded next to the automated result and never changes it; scheme rules change only through
          the verified Scheme updates process. {canAssign && "Administrators can assign cases but not decide them."}
        </p>
        {error && <div className="rv-warn" role="alert">⚠️ {error} <button className="rv-btn rv-btn--ghost" onClick={load}>Retry</button></div>}

        <div role="tablist" aria-label="Case status" className="rv-tabs">
          {TABS.map((t) => (
            <button key={t.key ?? "ALL"} role="tab" aria-selected={status === t.key} aria-controls="rv-queue"
                    className={`rv-tab ${status === t.key ? "rv-tab--active" : ""}`}
                    onClick={() => { setStatus(t.key); setOffset(0); setSelected(null); }}>
              {t.key ? STATUS_LABEL[t.key] : "All"} <span className="rv-count">{stats ? stats[t.stat] : "–"}</span>
            </button>
          ))}
        </div>
        <div className="rv-row">
          <label htmlFor="rv-reason" className="rv-label">Reason</label>
          <select id="rv-reason" className="rv-input rv-input--inline" value={reason} onChange={(e) => { setReason(e.target.value); setOffset(0); }}>
            <option value="">All reasons</option>
            {Object.entries(REASON_LABEL).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
          </select>
          <label htmlFor="rv-assigned" className="rv-label">Assignment</label>
          <select id="rv-assigned" className="rv-input rv-input--inline" value={assigned}
                  onChange={(e) => { setAssigned(e.target.value as "" | "me" | "unassigned"); setOffset(0); }}>
            <option value="">Anyone</option>
            <option value="me">Assigned to me</option>
            <option value="unassigned">Unassigned</option>
          </select>
          {stats && stats.awaiting_verification > 0 && <span className="rv-muted">{stats.awaiting_verification} awaiting additional verification</span>}
        </div>

        <div className="rv-layout">
          <section id="rv-queue" role="tabpanel" aria-busy={loading} className="rv-card rv-queue" aria-label="Cases">
            {loading && cases.length === 0 ? <p role="status">Loading cases…</p> : cases.length === 0 ? (
              <p className="rv-muted">No {status ? STATUS_LABEL[status].toLowerCase() : ""} cases{reason || assigned ? " match these filters" : ""}.</p>
            ) : (
              <ul className="rv-cases">
                {cases.map((c) => (
                  <li key={c.case_id}>
                    <button className={`rv-case ${selected === c.case_id ? "rv-case--active" : ""}`}
                            aria-current={selected === c.case_id ? "true" : undefined} onClick={() => setSelected(c.case_id)}>
                      <span className="rv-row rv-between">
                        <strong>{c.schemes.map((s) => s.name).join(", ") || "Retrieval issue"}</strong>
                        <span className={`rv-badge rv-badge--${c.status}`}>{STATUS_LABEL[c.status]}</span>
                      </span>
                      <span className="rv-muted">{REASON_LABEL[c.reason] ?? c.reason}</span>
                      <span className="rv-muted">Ref. {c.case_id} · opened {fmt(c.created_at)} · {c.assignee ? `assigned to ${c.assignee === me ? "you" : c.assignee}` : "unassigned"}
                        {c.awaiting_verification && " · awaiting verification"}{c.access === "granted" && " · read access"}</span>
                    </button>
                  </li>
                ))}
              </ul>
            )}
            {total > PAGE && (
              <nav className="rv-row rv-between" aria-label="Queue pages">
                <button className="rv-btn rv-btn--ghost" disabled={offset === 0 || loading} onClick={() => setOffset(offset - PAGE)}>← Previous</button>
                <span>Page {page} of {pages}</span>
                <button className="rv-btn rv-btn--ghost" disabled={page >= pages || loading} onClick={() => setOffset(offset + PAGE)}>Next →</button>
              </nav>
            )}
          </section>
          {picked && picked.access === "queue" ? (
            <section className="rv-card" aria-labelledby="queue-title">
              <h2 id="queue-title" className="rv-h2">{picked.schemes.map((x) => x.name).join(", ") || "Retrieval issue"}</h2>
              <p className="rv-muted">{REASON_LABEL[picked.reason] ?? picked.reason} · ref. {picked.case_id} · opened {fmt(picked.created_at)}</p>
              <p>The evidence, the farmer&apos;s question and the profile details are shown only to the reviewer
                working the case. Take it to see them; nobody else can act on it while it&apos;s yours.</p>
              <button className="rv-btn" disabled={taking || !canDecide} onClick={() => take(picked)}>
                {taking ? "Taking…" : "Take this case"}
              </button>
            </section>
          ) : selected ? (
            <CaseDetail key={selected} caseId={selected} me={me} canDecide={canDecide} canAssign={canAssign}
                        onChanged={load} fail={fail} />
          ) : (
            <section className="rv-card">
              {takeMsg && <p className="rv-warn" role="alert">{takeMsg}</p>}
              <p className="rv-muted">Select a case. Cases assigned to you open in full; unassigned ones can be taken.</p>
            </section>
          )}
        </div>
      </main>
      <Styles />
    </div>
  );
}

function Styles() {
  return (
    <style>{`
      .rv-page { min-height: 100vh; background: #f8fafc; color: #0f172a; font-family: var(--font-geist-sans, sans-serif); }
      .rv-header { display: flex; justify-content: space-between; align-items: center; gap: 1rem; flex-wrap: wrap;
        background: #1e1b4b; color: white; padding: 0.75rem 1.25rem; position: sticky; top: 0; z-index: 10; }
      .rv-brand { font-weight: 800; }
      .rv-main { max-width: 1280px; margin: 0 auto; padding: 1.25rem 1rem 3rem; display: flex; flex-direction: column; gap: 1rem; }
      .rv-h1 { font-size: 1.3rem; font-weight: 800; margin: 0; }
      .rv-h2 { font-size: 1.05rem; font-weight: 800; margin: 0; }
      .rv-h3 { font-size: 0.88rem; font-weight: 700; margin: 1.1rem 0 0.4rem; }
      .rv-card { background: white; border: 1px solid #e2e8f0; border-radius: 0.9rem; padding: 1rem 1.25rem; min-width: 0; }
      .rv-layout { display: grid; grid-template-columns: minmax(280px, 380px) 1fr; gap: 1rem; align-items: start; }
      @media (max-width: 860px) { .rv-layout { grid-template-columns: 1fr; } }
      .rv-row { display: flex; flex-wrap: wrap; gap: 0.5rem; align-items: center; }
      .rv-between { justify-content: space-between; }
      .rv-muted { color: #475569; font-size: 0.82rem; }
      .rv-info { color: #1e3a8a; background: #eff6ff; border: 1px solid #bfdbfe; border-radius: 0.5rem; padding: 0.45rem 0.7rem; font-size: 0.85rem; }
      .rv-link { background: none; border: none; color: #b91c1c; text-decoration: underline; cursor: pointer; font-size: 0.82rem; min-height: 32px; }
      .rv-input--num { width: 5.5rem; }
      .rv-grants { margin-top: 1rem; border-top: 1px solid #e2e8f0; }
      .rv-ok { color: #166534; background: #f0fdf4; border: 1px solid #bbf7d0; border-radius: 0.5rem; padding: 0.45rem 0.7rem; font-size: 0.85rem; }
      .rv-warn { color: #9a3412; background: #fff7ed; border: 1px solid #fed7aa; border-radius: 0.5rem; padding: 0.45rem 0.7rem; font-size: 0.85rem; }
      .rv-tabs { display: flex; flex-wrap: wrap; gap: 0.4rem; }
      .rv-tab { min-height: 44px; border: 1px solid #cbd5e1; background: white; border-radius: 99px; padding: 0.3rem 0.9rem; font-weight: 600; cursor: pointer; color: #1e293b; }
      .rv-tab--active { background: #1e1b4b; border-color: #1e1b4b; color: white; }
      .rv-count { display: inline-block; margin-left: 0.3rem; padding: 0 0.4rem; border-radius: 99px; background: rgba(0,0,0,0.08); font-size: 0.78rem; }
      .rv-tab--active .rv-count { background: rgba(255,255,255,0.2); }
      .rv-cases { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 0.5rem; }
      .rv-case { width: 100%; text-align: left; display: flex; flex-direction: column; gap: 0.2rem; border: 1px solid #e2e8f0;
        border-radius: 0.6rem; padding: 0.6rem 0.75rem; background: #f8fafc; cursor: pointer; color: inherit; font-size: 0.88rem; }
      .rv-case:hover { border-color: #a5b4fc; }
      .rv-case--active { border-color: #4338ca; background: #eef2ff; }
      .rv-badge { display: inline-block; border-radius: 99px; padding: 0.05rem 0.55rem; font-size: 0.74rem; font-weight: 700; white-space: nowrap; }
      .rv-badge--PENDING { background: #fef3c7; color: #92400e; }
      .rv-badge--IN_REVIEW { background: #dbeafe; color: #1e40af; }
      .rv-badge--RESOLVED { background: #dcfce7; color: #166534; }
      .rv-badge--DISMISSED { background: #e2e8f0; color: #334155; }
      .rv-dl { display: grid; grid-template-columns: auto 1fr; gap: 0.3rem 0.9rem; margin: 0.6rem 0 0; font-size: 0.85rem; }
      .rv-dl dt { color: #64748b; font-weight: 600; }
      .rv-dl dd { margin: 0; word-break: break-word; }
      .rv-list { margin: 0; padding-left: 1.1rem; font-size: 0.85rem; display: flex; flex-direction: column; gap: 0.3rem; word-break: break-word; }
      .rv-list a, .rv-history a { color: #1d4ed8; text-decoration: underline; }
      .rv-table { width: 100%; border-collapse: collapse; font-size: 0.82rem; display: block; overflow-x: auto; }
      .rv-table th, .rv-table td { text-align: left; padding: 0.35rem 0.5rem; border-bottom: 1px solid #e2e8f0; vertical-align: top; }
      .rv-quote { background: #f1f5f9; border-left: 3px solid #94a3b8; padding: 0.35rem 0.6rem; margin: 0.25rem 0; font-size: 0.85rem; white-space: pre-wrap; word-break: break-word; }
      .rv-history { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 0.45rem; font-size: 0.83rem; }
      .rv-comment { border-left: 3px solid #6366f1; padding-left: 0.5rem; }
      .rv-actions { margin-top: 1rem; border-top: 1px solid #e2e8f0; padding-top: 0.25rem; }
      .rv-form { display: flex; flex-direction: column; gap: 0.5rem; margin-top: 0.6rem; }
      .rv-fieldset { border: 1px solid #e2e8f0; border-radius: 0.6rem; padding: 0.5rem 0.75rem; margin: 0; display: flex; flex-direction: column; gap: 0.35rem; }
      .rv-legend { font-weight: 700; font-size: 0.85rem; padding: 0 0.25rem; }
      .rv-radio { display: flex; gap: 0.5rem; align-items: flex-start; font-size: 0.85rem; min-height: 32px; }
      .rv-radio input { margin-top: 0.25rem; }
      .rv-label { font-size: 0.82rem; font-weight: 600; }
      .rv-input { border: 1px solid #cbd5e1; border-radius: 0.5rem; padding: 0.45rem 0.6rem; font-size: 0.88rem; min-height: 44px; font-family: inherit; }
      .rv-input--inline { width: auto; min-width: 12rem; }
      .rv-btn { min-height: 44px; display: inline-flex; align-items: center; justify-content: center; border: none; border-radius: 0.5rem;
        padding: 0.4rem 1rem; background: #4338ca; color: white; font-weight: 600; font-size: 0.85rem; cursor: pointer; text-decoration: none; align-self: flex-start; }
      .rv-btn:disabled { opacity: 0.55; cursor: not-allowed; }
      .rv-btn--ghost { background: white; color: #3730a3; border: 1px solid #c7d2fe; }
      .rv-btn--light { background: rgba(255,255,255,0.12); color: white; border: 1px solid rgba(255,255,255,0.3); }
      .rv-page button:focus-visible, .rv-page a:focus-visible, .rv-page input:focus-visible,
      .rv-page select:focus-visible, .rv-page textarea:focus-visible { outline: 3px solid #f59e0b; outline-offset: 2px; }
      code { font-size: 0.8rem; background: #f1f5f9; padding: 0 0.25rem; border-radius: 0.25rem; }
    `}</style>
  );
}
