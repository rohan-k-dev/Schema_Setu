"use client";

/**
 * Start ingestion / graph-rebuild jobs. Dry run is the default; a real run asks the
 * administrator to type the job name (the backend requires the same confirmation,
 * runs one job at a time and audits everything).
 */

import React, { useCallback, useEffect, useRef, useState } from "react";
import { apiAdminJob, apiAdminJobs, apiAdminStartJob } from "@/lib/api";
import type { AdminJob, AdminJobKind } from "@/lib/types";
import { Badge } from "./OverviewPanel";

// PUBLISH_CHANGES is started from the Scheme updates panel (it needs a reviewed batch).
type FormKind = Exclude<AdminJobKind, "PUBLISH_CHANGES">;
const KINDS: Record<FormKind, { label: string; real: string }> = {
  IMPORT_CORPUS: { label: "Import the validated corpus into the database",
                   real: "Replaces scheme records with the corpus file (one transaction). Admin status / needs-review changes are reset." },
  REBUILD_GRAPH: { label: "Rebuild the Knowledge Graph",
                   real: "Builds and validates a new graph, then swaps it in; the previous graph is kept as a backup." },
};

export default function JobsPanel({ fail, onFinished }: { fail: (err: unknown) => void; onFinished: () => void }) {
  const [kind, setKind] = useState<FormKind>("IMPORT_CORPUS");
  const [dryRun, setDryRun] = useState(true);
  const [reason, setReason] = useState("");
  const [confirm, setConfirm] = useState("");
  const [current, setCurrent] = useState<AdminJob | null>(null);
  const [jobs, setJobs] = useState<AdminJob[]>([]);
  const [busy, setBusy] = useState(false);
  const timer = useRef<number | null>(null);

  const loadJobs = useCallback(async () => {
    try { setJobs((await apiAdminJobs(10, 0)).items); } catch (err) { fail(err); }
  }, [fail]);

  useEffect(() => { loadJobs(); return () => { if (timer.current) window.clearTimeout(timer.current); }; }, [loadJobs]);

  const poll = useCallback((id: string, tries = 0) => {
    timer.current = window.setTimeout(async () => {
      try {
        const j = await apiAdminJob(id);
        setCurrent(j);
        if (j.status === "QUEUED" || j.status === "RUNNING") { if (tries < 80) poll(id, tries + 1); }
        else { loadJobs(); onFinished(); }
      } catch (err) { fail(err); }
    }, 1500);
  }, [fail, loadJobs, onFinished]);

  const start = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true);
    try {
      const job = await apiAdminStartJob({ kind, dry_run: dryRun, reason: reason.trim(),
                                           ...(dryRun ? {} : { confirm: confirm.trim() }) });
      setCurrent(job);
      setConfirm("");
      poll(job.id);
    } catch (err) {
      fail(err);
    } finally {
      setBusy(false);
    }
  };

  const canStart = reason.trim().length >= 5 && (dryRun || confirm.trim() === kind) && !busy;

  return (
    <section className="adm-card adm-card--wide" aria-labelledby="jobs-title">
      <h2 id="jobs-title" className="adm-card-title">🛠️ Ingestion &amp; graph jobs</h2>
      <form onSubmit={start} className="adm-form">
        <label>Job
          <select value={kind} onChange={(e) => { setKind(e.target.value as FormKind); setConfirm(""); }} className="adm-input">
            {Object.entries(KINDS).map(([k, v]) => <option key={k} value={k}>{v.label}</option>)}
          </select>
        </label>
        <label className="adm-check">
          <input type="checkbox" checked={dryRun} onChange={(e) => setDryRun(e.target.checked)} />
          Dry run (check only, change nothing)
        </label>
        <label>Reason (kept in the audit log)
          <input value={reason} onChange={(e) => setReason(e.target.value)} maxLength={300} minLength={5}
                 className="adm-input" placeholder="e.g. corpus v1.1 reviewed by the data team" />
        </label>
        {!dryRun && (
          <div className="adm-danger" role="alert">
            <p><strong>This changes data.</strong> {KINDS[kind].real}</p>
            <label>Type <code>{kind}</code> to confirm
              <input value={confirm} onChange={(e) => setConfirm(e.target.value)} className="adm-input" autoComplete="off" />
            </label>
          </div>
        )}
        <button type="submit" disabled={!canStart} className={dryRun ? "adm-btn" : "adm-btn adm-btn--danger"}>
          {busy ? "Starting…" : dryRun ? "Start dry run" : "Run for real"}
        </button>
      </form>

      {current && (
        <div className="adm-block" aria-live="polite">
          <p>Job {current.kind}{current.dry_run ? " (dry run)" : ""}: <Badge ok={current.status === "SUCCEEDED" ? true
            : current.status === "FAILED" ? false : null} label={current.status} /> · correlation id <code>{current.correlation_id}</code></p>
          {current.error && <p className="adm-unavailable">{current.error}</p>}
          {current.result && <details open><summary>Result</summary><pre className="adm-pre">{JSON.stringify(current.result, null, 2)}</pre></details>}
        </div>
      )}

      <h3 className="adm-h3">Recent jobs</h3>
      <table className="adm-table">
        <thead><tr><th>When</th><th>Job</th><th>Status</th><th>By</th><th>Reason</th></tr></thead>
        <tbody>
          {jobs.map((j) => (
            <tr key={j.id}>
              <td>{new Date(j.created_at).toLocaleString("en-IN", { dateStyle: "short", timeStyle: "short" })}</td>
              <td>{j.kind}{j.dry_run ? " (dry)" : ""}</td>
              <td><Badge ok={j.status === "SUCCEEDED" ? true : j.status === "FAILED" ? false : null} label={j.status} /></td>
              <td>{j.requested_by}</td><td>{j.reason}</td>
            </tr>
          ))}
          {jobs.length === 0 && <tr><td colSpan={5}>No jobs yet.</td></tr>}
        </tbody>
      </table>
    </section>
  );
}
