"use client";

/**
 * Scheme updates (docs/SCHEME_UPDATES.md): detect changes in a candidate file from
 * data/incoming/, verify each one against the official source, then publish the
 * approved ones. Farmers are notified only after publishing. Consequential changes need
 * the "checked against the official source" confirmation and a note — the server
 * enforces it.
 */

import React, { useCallback, useEffect, useState } from "react";
import {
  apiChangeBatches, apiChangeSources, apiDeliveries, apiDetectChanges, apiDispatchNow, apiPublishChanges,
  apiReviewChange, apiSchemeChanges,
} from "@/lib/api";
import type { ChangeBatch, SchemeChange } from "@/lib/types";
import { Badge } from "./OverviewPanel";

function ChangeRow({ c, busy, onReview }: {
  c: SchemeChange; busy: boolean;
  onReview: (c: SchemeChange, decision: "APPROVED" | "REJECTED", note: string, confirm: boolean) => void;
}) {
  const [note, setNote] = useState("");
  const [confirm, setConfirm] = useState(false);
  const rec = c.provenance.records?.[0] as { url?: string; retrieved_at?: string } | undefined;
  return (
    <li className="adm-change">
      <p><strong>{c.scheme_name}</strong> · {c.category.replace(/_/g, " ").toLowerCase()}{" "}
        {c.consequential && <Badge ok={false} label="consequential" />}{" "}
        <Badge ok={c.status === "APPROVED" || c.status === "PUBLISHED" ? true : c.status === "REJECTED" ? false : null} label={c.status} /></p>
      <p className="adm-note">{c.summary} · source {c.provenance.source_file}{rec?.url && <> · <a href={rec.url} target="_blank" rel="noopener noreferrer">{rec.url}</a></>}
        {rec?.retrieved_at && <> (retrieved {rec.retrieved_at})</>}</p>
      <details><summary>Before / after</summary>
        <div className="adm-diff"><pre className="adm-pre">{JSON.stringify(c.before, null, 2)}</pre>
          <pre className="adm-pre">{JSON.stringify(c.after, null, 2)}</pre></div>
      </details>
      {c.status === "PENDING" ? (
        <div className="adm-row">
          <label className="sr-only" htmlFor={`note-${c.id}`}>Review note</label>
          <input id={`note-${c.id}`} className="adm-input" value={note} onChange={(e) => setNote(e.target.value)}
                 placeholder={c.consequential ? "What did you check? (required)" : "Note (optional)"} maxLength={1000} />
          {c.consequential && (
            <label className="adm-check"><input type="checkbox" checked={confirm} onChange={(e) => setConfirm(e.target.checked)} />
              I checked this against the official source</label>
          )}
          <button className="adm-btn" disabled={busy || (c.consequential && (!confirm || note.trim().length < 10))}
                  onClick={() => onReview(c, "APPROVED", note, confirm)}>Approve</button>
          <button className="adm-btn adm-btn--ghost" disabled={busy} onClick={() => onReview(c, "REJECTED", note, false)}>Reject</button>
        </div>
      ) : c.reviewed_by && <p className="adm-note">{c.status.toLowerCase()} by {c.reviewed_by}{c.review_note && ` — ${c.review_note}`}</p>}
    </li>
  );
}

export default function SchemeChangesPanel({ fail }: { fail: (err: unknown) => void }) {
  const [sources, setSources] = useState<{ name: string }[]>([]);
  const [source, setSource] = useState("");
  const [batches, setBatches] = useState<ChangeBatch[]>([]);
  const [open, setOpen] = useState<string | null>(null);
  const [changes, setChanges] = useState<SchemeChange[]>([]);
  const [deliveries, setDeliveries] = useState<Record<string, number>>({});
  const [msg, setMsg] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    try {
      const [s, b, d] = await Promise.all([apiChangeSources(), apiChangeBatches(), apiDeliveries()]);
      setSources(s.items);
      setBatches(b.items);
      setDeliveries(d.counts);
      if (open) setChanges((await apiSchemeChanges(open)).items);
    } catch (err) { fail(err); }
  }, [fail, open]);

  useEffect(() => { load(); }, [load]);

  /** Runs an action; its own message (if it returns a string) wins over the generic one. */
  const act = async (fn: () => Promise<unknown>, done: string) => {
    setBusy(true);
    try {
      const result = await fn();
      setMsg(typeof result === "string" ? result : done);
      await load();
    } catch (err) { fail(err); } finally { setBusy(false); }
  };

  const batch = batches.find((b) => b.id === open);

  return (
    <section className="adm-card adm-card--wide" aria-labelledby="updates-title">
      <h2 id="updates-title" className="adm-card-title">📰 Scheme updates &amp; notifications</h2>
      <p className="adm-note">Nothing found by a scraper is trusted automatically: verify every change, then publish.
        Farmers who saved or follow a scheme are notified only after publishing.</p>
      <p className="sr-only" aria-live="polite">{msg}</p>
      <form className="adm-row" onSubmit={(e) => { e.preventDefault();
        act(async () => {
          const r = await apiDetectChanges(source);
          setOpen(r.batch_id);
          return `${r.new_changes} new change(s) (${r.consequential} consequential), ${r.duplicates_skipped} already known`
            + (r.invalid_records.length ? `, ${r.invalid_records.length} invalid record(s) ignored` : "") + ".";
        }, "Detected."); }}>
        <label className="sr-only" htmlFor="upd-source">Candidate file</label>
        <select id="upd-source" className="adm-input" value={source} onChange={(e) => setSource(e.target.value)}>
          <option value="">Choose a file in data/incoming/</option>
          {sources.map((s) => <option key={s.name}>{s.name}</option>)}
        </select>
        <button type="submit" className="adm-btn" disabled={busy || !source}>Detect changes</button>
      </form>
      {msg && <p className="adm-ok" role="status">{msg}</p>}

      <table className="adm-table">
        <thead><tr><th>Detected</th><th>Source</th><th>Status</th><th>Pending</th><th>Approved</th><th>Rejected</th><th /></tr></thead>
        <tbody>{batches.map((b) => (
          <tr key={b.id}>
            <td>{new Date(b.detected_at).toLocaleString("en-IN", { dateStyle: "short", timeStyle: "short" })}</td>
            <td>{b.source_name}</td><td>{b.status}{b.published_version && ` (v${b.published_version})`}</td>
            <td>{b.pending}</td><td>{b.approved}</td><td>{b.rejected}</td>
            <td><button className="adm-btn adm-btn--ghost" onClick={() => setOpen(b.id)}>Review</button></td>
          </tr>))}
          {batches.length === 0 && <tr><td colSpan={7}>No detections yet.</td></tr>}
        </tbody>
      </table>

      {batch && (
        <div className="adm-block">
          {batch.warnings?.map((w) => <p key={w} className="adm-unavailable">⚠️ {w}</p>)}
          {batch.invalid_records?.length > 0 && <p className="adm-unavailable">{batch.invalid_records.length} record(s) in the file were invalid and ignored.</p>}
          <ul className="adm-list adm-changes">
            {changes.map((c) => <ChangeRow key={c.id} c={c} busy={busy} onReview={(ch, d, n, conf) =>
              act(() => apiReviewChange(ch.id, d, n, conf), `Change ${d.toLowerCase()}.`)} />)}
          </ul>
          {batch.status === "OPEN" && (
            <div className="adm-row">
              <button className="adm-btn adm-btn--ghost" disabled={busy || batch.pending > 0 || batch.approved === 0}
                      onClick={() => act(() => apiPublishChanges(batch.id, true, "Preview publishing verified changes"), "Dry run started — see Recent jobs.")}>
                Publish: dry run</button>
              <button className="adm-btn adm-btn--danger" disabled={busy || batch.pending > 0 || batch.approved === 0}
                      onClick={() => act(() => apiPublishChanges(batch.id, false, "Publish verified scheme changes"), "Publishing started — see Recent jobs.")}>
                Publish approved changes &amp; notify</button>
              {batch.pending > 0 && <span className="adm-note">Decide every change first ({batch.pending} pending).</span>}
            </div>
          )}
        </div>
      )}

      <h3 className="adm-h3">Deliveries</h3>
      <p className="adm-note">{Object.entries(deliveries).map(([k, n]) => `${k} ${n}`).join(" · ") || "None yet."}</p>
      <button className="adm-btn adm-btn--ghost" disabled={busy}
              onClick={() => act(() => apiDispatchNow(), "Due deliveries sent.")}>Send due deliveries now</button>
    </section>
  );
}
