"use client";

/** The audit log: filters, pages of 25, and a tamper check of the hash chain. */

import React, { useCallback, useEffect, useState } from "react";
import { apiAdminAudit, apiAdminVerifyAudit } from "@/lib/api";
import type { AuditEventView, AuditIntegrity } from "@/lib/types";
import { Badge } from "./OverviewPanel";

const PAGE = 25;

export default function AuditPanel({ fail, refreshKey }: { fail: (err: unknown) => void; refreshKey: number }) {
  const [items, setItems] = useState<AuditEventView[]>([]);
  const [total, setTotal] = useState(0);
  const [offset, setOffset] = useState(0);
  const [action, setAction] = useState("");
  const [outcome, setOutcome] = useState("");
  const [corr, setCorr] = useState("");
  const [integrity, setIntegrity] = useState<AuditIntegrity | null>(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async (off: number) => {
    setBusy(true);
    try {
      const page = await apiAdminAudit({ limit: PAGE, offset: off, action: action.trim().toUpperCase() || undefined,
                                         outcome: outcome || undefined, correlation_id: corr.trim() || undefined });
      setItems(page.items);
      setTotal(page.total);
      setOffset(off);
    } catch (err) {
      fail(err);
    } finally {
      setBusy(false);
    }
  }, [action, outcome, corr, fail]);

  useEffect(() => { load(0); }, [refreshKey]); // eslint-disable-line react-hooks/exhaustive-deps

  const verify = async () => {
    setBusy(true);
    try { setIntegrity(await apiAdminVerifyAudit()); load(0); } catch (err) { fail(err); } finally { setBusy(false); }
  };

  return (
    <section className="adm-card adm-card--wide" aria-labelledby="audit-title">
      <h2 id="audit-title" className="adm-card-title">📜 Audit log</h2>
      <form className="adm-row" onSubmit={(e) => { e.preventDefault(); load(0); }}>
        <label className="sr-only" htmlFor="aud-action">Action</label>
        <input id="aud-action" value={action} onChange={(e) => setAction(e.target.value)} placeholder="Action, e.g. ROLE_CHANGED"
               className="adm-input" maxLength={40} />
        <label className="sr-only" htmlFor="aud-outcome">Outcome</label>
        <select id="aud-outcome" value={outcome} onChange={(e) => setOutcome(e.target.value)} className="adm-input">
          <option value="">Any outcome</option><option>SUCCESS</option><option>FAILURE</option><option>DENIED</option>
        </select>
        <label className="sr-only" htmlFor="aud-corr">Correlation id</label>
        <input id="aud-corr" value={corr} onChange={(e) => setCorr(e.target.value)} placeholder="Correlation id"
               className="adm-input" maxLength={64} />
        <button type="submit" disabled={busy} className="adm-btn adm-btn--ghost">Filter</button>
        <button type="button" onClick={verify} disabled={busy} className="adm-btn">Verify integrity</button>
      </form>

      {integrity && (
        <p role="status" className={integrity.valid ? "adm-ok" : "adm-unavailable"}>
          {integrity.valid ? `✓ Hash chain intact (${integrity.checked} events checked).`
            : `⚠️ Chain broken at event #${integrity.first_broken_id}: ${integrity.reason}`}
        </p>
      )}

      <table className="adm-table">
        <thead><tr><th>When</th><th>Actor</th><th>Action</th><th>Record</th><th>Outcome</th><th>Correlation id</th></tr></thead>
        <tbody>
          {items.map((e) => (
            <tr key={e.id}>
              <td>{new Date(e.occurred_at).toLocaleString("en-IN", { dateStyle: "short", timeStyle: "medium" })}</td>
              <td>{e.actor_label}{e.actor_role && <small> ({e.actor_role})</small>}</td>
              <td>{e.action}{e.details && <details><summary>details</summary><pre className="adm-pre">{JSON.stringify(e.details, null, 2)}</pre></details>}</td>
              <td>{e.target_type ? `${e.target_type}: ${e.target_id ?? "—"}` : "—"}</td>
              <td><Badge ok={e.outcome === "SUCCESS" ? true : e.outcome === "DENIED" ? false : null} label={e.outcome} /></td>
              <td><code>{e.correlation_id ?? "—"}</code></td>
            </tr>
          ))}
          {items.length === 0 && <tr><td colSpan={6}>No events.</td></tr>}
        </tbody>
      </table>
      <nav className="adm-row" aria-label="Audit log pages">
        <button onClick={() => load(Math.max(0, offset - PAGE))} disabled={busy || offset === 0} className="adm-btn adm-btn--ghost">← Newer</button>
        <span>{total === 0 ? "0" : `${offset + 1}–${Math.min(offset + PAGE, total)}`} of {total}</span>
        <button onClick={() => load(offset + PAGE)} disabled={busy || offset + PAGE >= total} className="adm-btn adm-btn--ghost">Older →</button>
      </nav>
    </section>
  );
}
