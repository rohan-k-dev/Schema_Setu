"use client";

/** Recent operational errors of this server process (redacted on the server), paged. */

import React, { useCallback, useEffect, useState } from "react";
import { apiAdminErrors } from "@/lib/api";
import type { OpsError } from "@/lib/types";

const PAGE = 20;

export default function ErrorsPanel({ fail, refreshKey }: { fail: (err: unknown) => void; refreshKey: number }) {
  const [items, setItems] = useState<OpsError[]>([]);
  const [total, setTotal] = useState(0);
  const [offset, setOffset] = useState(0);

  const load = useCallback(async (off: number) => {
    try {
      const page = await apiAdminErrors(PAGE, off);
      setItems(page.items);
      setTotal(page.total);
      setOffset(off);
    } catch (err) {
      fail(err);
    }
  }, [fail]);

  useEffect(() => { load(0); }, [load, refreshKey]);

  return (
    <section className="adm-card adm-card--wide" aria-labelledby="errors-title">
      <h2 id="errors-title" className="adm-card-title">🚨 Recent operational errors</h2>
      <p className="adm-note">Personal data and secrets are removed before errors are kept. Search the server log or the audit
        log with the correlation id for the full story.</p>
      <table className="adm-table">
        <thead><tr><th>When</th><th>Where</th><th>Message</th><th>Correlation id</th></tr></thead>
        <tbody>
          {items.map((e) => (
            <tr key={e.id}>
              <td>{new Date(e.at).toLocaleString("en-IN", { dateStyle: "short", timeStyle: "medium" })}</td>
              <td><code>{e.logger}</code></td>
              <td>{e.message}{e.exception_type && <small> ({e.exception_type})</small>}</td>
              <td><code>{e.correlation_id ?? "—"}</code></td>
            </tr>
          ))}
          {items.length === 0 && <tr><td colSpan={4}>No errors recorded since the server started.</td></tr>}
        </tbody>
      </table>
      {total > PAGE && (
        <nav className="adm-row" aria-label="Error pages">
          <button onClick={() => load(Math.max(0, offset - PAGE))} disabled={offset === 0} className="adm-btn adm-btn--ghost">← Newer</button>
          <span>{offset + 1}–{Math.min(offset + PAGE, total)} of {total}</span>
          <button onClick={() => load(offset + PAGE)} disabled={offset + PAGE >= total} className="adm-btn adm-btn--ghost">Older →</button>
        </nav>
      )}
    </section>
  );
}
