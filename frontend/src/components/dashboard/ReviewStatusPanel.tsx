"use client";

/**
 * "Checks by our team": review cases raised by this farmer's own searches (docs/HUMAN_REVIEW.md),
 * in plain language. Open cases are shown first and clearly marked unconfirmed. No reviewer
 * names, notes or evidence are ever shown here.
 */

import React, { useCallback, useEffect, useState } from "react";
import { apiMyReviewCases, ApiError } from "@/lib/api";
import type { FarmerReviewCase } from "@/lib/types";

const fmt = (iso: string) => new Date(iso).toLocaleDateString("en-IN", { day: "numeric", month: "short", year: "numeric" });

export default function ReviewStatusPanel({ onUnauthorized }: { onUnauthorized: () => void }) {
  const [items, setItems] = useState<FarmerReviewCase[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setError(null);
    try {
      setItems((await apiMyReviewCases()).items);
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) onUnauthorized();
      else setError(err instanceof Error ? err.message : "Could not load the checks on your results.");
    }
  }, [onUnauthorized]);

  useEffect(() => { load(); }, [load]);

  if (items !== null && items.length === 0 && !error) return null;
  const sorted = (items ?? []).slice().sort((a, b) => Number(b.open) - Number(a.open));
  const open = sorted.filter((i) => i.open).length;

  return (
    <section className={`dash-card dash-card--wide ${open ? "rs-open" : ""}`} aria-labelledby="rs-title" id="review-status">
      <div className="dash-card-header">
        <h2 id="rs-title" className="dash-card-title">🧑‍⚖️ Checks by our team</h2>
        {open > 0 && <span className="rs-badge rs-badge--open">{open} still open</span>}
      </div>
      {error ? (
        <div className="dash-error" role="alert">⚠️ {error}<button onClick={load} className="dash-retry min-h-[44px]">Retry</button></div>
      ) : items === null ? (
        <p className="dash-empty" role="status">Loading…</p>
      ) : (
        <>
          {open > 0 && (
            <p className="rs-lead">Some of your results couldn&apos;t be confirmed automatically. A person is checking them.
              Until a check is finished, treat that result as <strong>unconfirmed</strong> and check the official website before applying.</p>
          )}
          <ul className="rs-list">
            {sorted.map((c) => (
              <li key={c.case_id} className={`rs-item ${c.open ? "rs-item--open" : ""}`}>
                <div className="rs-head">
                  <strong>{c.schemes.map((s) => s.name).join(", ") || "Your search"}</strong>
                  <span className={`rs-badge ${c.open ? "rs-badge--open" : "rs-badge--done"}`}>
                    {c.open ? "Being checked" : c.status === "DISMISSED" ? "Closed" : "Checked"}
                  </span>
                </div>
                <p className="rs-text">{c.reason_text}</p>
                <p className="rs-text"><strong>{c.open ? "Status:" : "Outcome:"}</strong> {c.outcome_text}</p>
                <p className="rs-meta">Raised {fmt(c.opened_at)}{c.updated_at !== c.opened_at && ` · updated ${fmt(c.updated_at)}`} · reference {c.case_id}</p>
              </li>
            ))}
          </ul>
        </>
      )}
      <style>{`
        .rs-open { border-color: #fcd34d; }
        .rs-lead { font-size: 0.85rem; color: #92400e; background: #fffbeb; border: 1px solid #fde68a; border-radius: 0.6rem; padding: 0.5rem 0.75rem; margin: 0 0 0.75rem; }
        .rs-list { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 0.6rem; }
        .rs-item { border: 1px solid #e5e7eb; border-radius: 0.7rem; padding: 0.65rem 0.85rem; }
        .rs-item--open { border-color: #fcd34d; background: #fffdf5; }
        .rs-head { display: flex; justify-content: space-between; gap: 0.75rem; align-items: flex-start; }
        .rs-badge { flex-shrink: 0; border-radius: 99px; padding: 0.1rem 0.6rem; font-size: 0.72rem; font-weight: 700; }
        .rs-badge--open { background: #fef3c7; color: #92400e; }
        .rs-badge--done { background: #d1fae5; color: #065f46; }
        .rs-text { font-size: 0.83rem; color: #374151; margin: 0.35rem 0 0; line-height: 1.5; }
        .rs-meta { font-size: 0.75rem; color: #6b7280; margin: 0.35rem 0 0; }
      `}</style>
    </section>
  );
}
