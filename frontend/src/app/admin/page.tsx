"use client";

/**
 * Administrator operations dashboard (docs/ADMIN_OPERATIONS.md).
 *
 * Route: /admin. Signed out → /auth. The backend decides access: every request here
 * is checked for the ADMIN role on the server, and a 403 shows "Administrator access
 * required" without any data. Nothing on this page is protected by hiding it.
 */

import React, { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useAuth } from "@/lib/AuthContext";
import { apiAdminOverview, ApiError } from "@/lib/api";
import type { AdminOverview } from "@/lib/types";
import OverviewPanel from "@/components/admin/OverviewPanel";
import ToolsPanel from "@/components/admin/ToolsPanel";
import JobsPanel from "@/components/admin/JobsPanel";
import AuditPanel from "@/components/admin/AuditPanel";
import ErrorsPanel from "@/components/admin/ErrorsPanel";
import SchemeChangesPanel from "@/components/admin/SchemeChangesPanel";
import ReviewersPanel from "@/components/admin/ReviewersPanel";

export default function AdminPage() {
  const router = useRouter();
  const { isAuthenticated, isLoading, handleUnauthorized } = useAuth();
  const [data, setData] = useState<AdminOverview | null>(null);
  const [forbidden, setForbidden] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [refreshKey, setRefreshKey] = useState(0);

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
      setData(await apiAdminOverview());
    } catch (err) {
      fail(err);
    } finally {
      setLoading(false);
    }
  }, [fail]);

  useEffect(() => { if (isAuthenticated) load(); }, [isAuthenticated, load]);

  const refreshAll = useCallback(() => { load(); setRefreshKey((k) => k + 1); }, [load]);

  if (isLoading || (loading && !data && !forbidden)) {
    return <div className="adm-page"><p className="adm-center" role="status">Loading the operations dashboard…</p><Styles /></div>;
  }

  if (forbidden) {
    return (
      <div className="adm-page">
        <main className="adm-main">
          <section className="adm-card" role="alert">
            <h1 className="adm-title">Administrator access required</h1>
            <p>Your account doesn&apos;t have permission to see this page. If you think it should, ask an administrator.</p>
            <Link href="/dashboard" className="adm-btn adm-btn--ghost">← Back to your dashboard</Link>
          </section>
        </main>
        <Styles />
      </div>
    );
  }

  return (
    <div className="adm-page">
      <header className="adm-header">
        <span className="adm-brand">🌾 SchemeSetu · Operations</span>
        <nav className="adm-row">
          <button onClick={refreshAll} disabled={loading} className="adm-btn adm-btn--light">{loading ? "Refreshing…" : "Refresh"}</button>
          <Link href="/dashboard" className="adm-btn adm-btn--light">Dashboard</Link>
        </nav>
      </header>
      <main className="adm-main">
        {error && (
          <div className="adm-unavailable adm-banner" role="alert">
            ⚠️ {error} <button onClick={() => setError(null)} className="adm-btn adm-btn--ghost" aria-label="Dismiss">✕</button>
          </div>
        )}
        {data && (
          <>
            <p className="adm-note">Updated {new Date(data.generated_at).toLocaleString("en-IN", { dateStyle: "medium", timeStyle: "medium" })}.
              Every action on this page is checked on the server and recorded in the audit log.</p>
            <OverviewPanel data={data} />
          </>
        )}
        <ToolsPanel fail={fail} />
        <ReviewersPanel fail={fail} />
        <SchemeChangesPanel fail={fail} />
        <JobsPanel fail={fail} onFinished={refreshAll} />
        <AuditPanel fail={fail} refreshKey={refreshKey} />
        <ErrorsPanel fail={fail} refreshKey={refreshKey} />
      </main>
      <Styles />
    </div>
  );
}

function Styles() {
  return (
    <style>{`
      .adm-page { min-height: 100vh; background: #f8fafc; font-family: var(--font-geist-sans, sans-serif); color: #0f172a; }
      .adm-header { display: flex; justify-content: space-between; align-items: center; gap: 1rem; flex-wrap: wrap;
        background: #0f172a; color: white; padding: 0.75rem 1.25rem; position: sticky; top: 0; z-index: 10; }
      .adm-brand { font-weight: 800; }
      .adm-main { max-width: 1200px; margin: 0 auto; padding: 1.25rem 1rem 3rem; display: flex; flex-direction: column; gap: 1.25rem; }
      .adm-center { text-align: center; padding: 4rem 1rem; color: #475569; }
      .adm-title { font-size: 1.25rem; font-weight: 800; margin: 0 0 0.5rem; }
      .adm-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(330px, 1fr)); gap: 1rem; }
      .adm-card { background: white; border: 1px solid #e2e8f0; border-radius: 0.9rem; padding: 1rem 1.25rem; }
      .adm-card-title { font-size: 0.95rem; font-weight: 700; margin: 0 0 0.75rem; }
      .adm-h3 { font-size: 0.85rem; font-weight: 700; margin: 1rem 0 0.4rem; }
      .adm-dl { display: grid; grid-template-columns: auto 1fr; gap: 0.35rem 0.9rem; margin: 0; font-size: 0.84rem; }
      .adm-dl dt { color: #64748b; font-weight: 600; }
      .adm-dl dd { margin: 0; display: flex; flex-wrap: wrap; gap: 0.3rem; word-break: break-word; }
      .adm-badge { display: inline-block; border-radius: 99px; padding: 0.05rem 0.55rem; font-size: 0.74rem; font-weight: 700; }
      .adm-badge--ok { background: #dcfce7; color: #166534; }
      .adm-badge--bad { background: #fee2e2; color: #991b1b; }
      .adm-badge--muted { background: #e2e8f0; color: #334155; }
      .adm-unavailable { color: #9a3412; background: #fff7ed; border: 1px solid #fed7aa; border-radius: 0.5rem; padding: 0.45rem 0.7rem; font-size: 0.84rem; margin: 0.3rem 0; }
      .adm-ok { color: #166534; background: #f0fdf4; border: 1px solid #bbf7d0; border-radius: 0.5rem; padding: 0.45rem 0.7rem; font-size: 0.84rem; }
      .adm-banner { display: flex; justify-content: space-between; align-items: center; gap: 1rem; }
      .adm-warn { margin: 0.6rem 0 0; padding-left: 1.1rem; font-size: 0.8rem; color: #9a3412; }
      .adm-note { font-size: 0.8rem; color: #475569; margin: 0 0 0.5rem; }
      .adm-list { margin: 0; padding-left: 1.1rem; font-size: 0.82rem; display: flex; flex-direction: column; gap: 0.25rem; word-break: break-word; }
      .adm-row { display: flex; flex-wrap: wrap; gap: 0.5rem; align-items: center; margin: 0.4rem 0; }
      .adm-btn { min-height: 44px; display: inline-flex; align-items: center; border: none; border-radius: 0.5rem; padding: 0.4rem 1rem;
        background: #0f766e; color: white; font-weight: 600; font-size: 0.85rem; cursor: pointer; text-decoration: none; }
      .adm-btn:disabled { opacity: 0.55; cursor: not-allowed; }
      .adm-btn--ghost { background: white; color: #0f172a; border: 1px solid #cbd5e1; }
      .adm-btn--light { background: rgba(255,255,255,0.12); color: white; border: 1px solid rgba(255,255,255,0.25); }
      .adm-btn--danger { background: #b91c1c; }
      .adm-btn:focus-visible, .adm-input:focus-visible { outline: 3px solid #2563eb; outline-offset: 2px; }
      .adm-input { min-height: 44px; border: 1px solid #cbd5e1; border-radius: 0.5rem; padding: 0.3rem 0.6rem; font-size: 0.85rem; background: white; color: #0f172a; }
      .adm-form { display: grid; gap: 0.65rem; max-width: 640px; font-size: 0.85rem; }
      .adm-form label { display: flex; flex-direction: column; gap: 0.25rem; font-weight: 600; }
      .adm-form .adm-check { flex-direction: row; align-items: center; gap: 0.5rem; }
      .adm-danger { border: 1px solid #fecaca; background: #fef2f2; border-radius: 0.6rem; padding: 0.6rem 0.8rem; }
      .adm-danger p { margin: 0 0 0.4rem; }
      .adm-block { margin-top: 0.9rem; font-size: 0.85rem; }
      .adm-table { width: 100%; border-collapse: collapse; font-size: 0.8rem; margin-top: 0.5rem; display: block; overflow-x: auto; }
      .adm-table th, .adm-table td { text-align: left; padding: 0.4rem 0.5rem; border-bottom: 1px solid #e2e8f0; vertical-align: top; }
      .adm-table th { color: #475569; font-weight: 700; white-space: nowrap; }
      .adm-pre { white-space: pre-wrap; word-break: break-word; background: #f1f5f9; border-radius: 0.4rem; padding: 0.5rem; font-size: 0.74rem; max-height: 320px; overflow: auto; }
      .adm-card--wide { grid-column: 1 / -1; }
      .adm-changes { list-style: none; padding: 0; gap: 0.6rem; }
      .adm-change { border: 1px solid #e2e8f0; border-radius: 0.6rem; padding: 0.6rem 0.8rem; }
      .adm-change p { margin: 0 0 0.3rem; }
      .adm-diff { display: grid; grid-template-columns: 1fr 1fr; gap: 0.5rem; }
      @media (max-width: 640px) { .adm-diff { grid-template-columns: 1fr; } }
      .adm-check { display: inline-flex; align-items: center; gap: 0.4rem; font-size: 0.82rem; min-height: 44px; }
      .sr-only { position: absolute; width: 1px; height: 1px; overflow: hidden; clip: rect(0,0,0,0); white-space: nowrap; }
    `}</style>
  );
}
