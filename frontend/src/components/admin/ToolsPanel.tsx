"use client";

/** Read-only tools: validate scheme data, inspect source / rule conflicts and flagged schemes. */

import React, { useState } from "react";
import { apiAdminConflicts, apiAdminValidate } from "@/lib/api";
import type { ConflictReport, ValidationReport } from "@/lib/types";
import { Badge } from "./OverviewPanel";

export default function ToolsPanel({ fail }: { fail: (err: unknown) => void }) {
  const [report, setReport] = useState<ValidationReport | null>(null);
  const [conflicts, setConflicts] = useState<ConflictReport | null>(null);
  const [busy, setBusy] = useState<"validate" | "conflicts" | null>(null);

  const run = async (which: "validate" | "conflicts") => {
    setBusy(which);
    try {
      if (which === "validate") setReport(await apiAdminValidate());
      else setConflicts(await apiAdminConflicts());
    } catch (err) {
      fail(err);
    } finally {
      setBusy(null);
    }
  };

  return (
    <section className="adm-card adm-card--wide" aria-labelledby="tools-title">
      <h2 id="tools-title" className="adm-card-title">🧪 Data checks (read-only)</h2>
      <div className="adm-row">
        <button onClick={() => run("validate")} disabled={busy !== null} className="adm-btn">
          {busy === "validate" ? "Validating…" : "Validate scheme data"}
        </button>
        <button onClick={() => run("conflicts")} disabled={busy !== null} className="adm-btn adm-btn--ghost">
          {busy === "conflicts" ? "Loading…" : "Inspect conflicts"}
        </button>
      </div>

      {report && (
        <div className="adm-block" aria-live="polite">
          <p>Overall: <Badge ok={report.overall === "PASS" ? true : report.overall === "WARN" ? null : false}
                             label={report.overall} /> · checked {new Date(report.checked_at).toLocaleTimeString("en-IN")}</p>
          <table className="adm-table">
            <thead><tr><th>Check</th><th>Result</th><th>Summary</th></tr></thead>
            <tbody>
              {report.checks.map((c) => (
                <tr key={c.name}>
                  <td>{c.name.replace(/_/g, " ")}</td>
                  <td><Badge ok={c.status === "PASS" ? true : c.status === "WARN" ? null : false} label={c.status} /></td>
                  <td>
                    {c.summary}
                    {c.items.length > 0 && (
                      <details><summary>Details ({c.items.length})</summary>
                        <pre className="adm-pre">{JSON.stringify(c.items, null, 2)}</pre>
                      </details>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {conflicts && (
        <div className="adm-block" aria-live="polite">
          <h3 className="adm-h3">Source conflicts (database vs live web) — {conflicts.source_conflicts_total}</h3>
          {conflicts.source_conflicts.length === 0 ? <p className="adm-note">None recorded.</p> : (
            <table className="adm-table">
              <thead><tr><th>Scheme</th><th>Field</th><th>Values</th><th>Review case</th></tr></thead>
              <tbody>{conflicts.source_conflicts.map((c, i) => (
                <tr key={`${c.case_id}-${i}`}>
                  <td>{c.scheme_id}</td><td>{c.field}</td>
                  <td>{typeof c.values === "string" ? c.values : Object.entries(c.values).map(([k, v]) => (
                    <div key={k}><strong>{k}:</strong> {v}</div>))}</td>
                  <td>{c.case_id} ({c.case_status})</td>
                </tr>
              ))}</tbody>
            </table>
          )}
          <p className="adm-note">The database value is canonical. If the web value is right, correct the corpus and re-import.</p>
          <h3 className="adm-h3">Contradictory rules</h3>
          {conflicts.rule_conflicts === null ? <p className="adm-unavailable">⚠️ Database unavailable.</p>
            : conflicts.rule_conflicts.length === 0 ? <p className="adm-note">None.</p> : (
              <ul className="adm-list">{conflicts.rule_conflicts.map((r, i) => <li key={i}><strong>{r.scheme_id}</strong>: {r.message}</li>)}</ul>
            )}
          <h3 className="adm-h3">Flagged schemes</h3>
          {conflicts.flagged_schemes === null ? <p className="adm-unavailable">⚠️ Database unavailable.</p>
            : conflicts.flagged_schemes.length === 0 ? <p className="adm-note">None.</p> : (
              <ul className="adm-list">{conflicts.flagged_schemes.map((s) => (
                <li key={s.scheme_id}><strong>{s.scheme_id}</strong> ({s.status}){s.needs_review && " · needs review"}
                  {s.possible_duplicate && " · possible duplicate"}{s.review_notes && ` — ${s.review_notes}`}</li>))}</ul>
            )}
        </div>
      )}
    </section>
  );
}
