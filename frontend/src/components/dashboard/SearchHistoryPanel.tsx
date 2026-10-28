"use client";

/**
 * Recent searches with per-item delete, "clear all", and "load more".
 * Kept only per the retention policy (signed in + agreed to keep details;
 * last 50, at most 90 days) — see docs/DASHBOARD.md.
 */

import React, { useCallback, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { apiClearSearchHistory, apiDeleteSearch, apiGetSearchHistoryPage, ApiError } from "@/lib/api";
import type { SearchHistoryEntry } from "@/lib/types";

const PAGE = 10;

export default function SearchHistoryPanel({
  onTotalChange,
  onUnauthorized,
}: {
  onTotalChange: (total: number) => void;
  onUnauthorized: () => void;
}) {
  const router = useRouter();
  const [items, setItems] = useState<SearchHistoryEntry[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [confirmClear, setConfirmClear] = useState(false);
  const [busy, setBusy] = useState(false);

  const fail = useCallback((err: unknown, fallback: string) => {
    if (err instanceof ApiError && err.status === 401) onUnauthorized();
    else setError(err instanceof Error ? err.message : fallback);
  }, [onUnauthorized]);

  const load = useCallback(async (offset: number) => {
    setLoading(true);
    setError(null);
    try {
      const page = await apiGetSearchHistoryPage(PAGE, offset);
      setItems((prev) => (offset === 0 ? page.items : [...prev, ...page.items]));
      setTotal(page.total);
    } catch (err) {
      fail(err, "Failed to load search history.");
    } finally {
      setLoading(false);
    }
  }, [fail]);

  useEffect(() => { load(0); }, [load]);
  useEffect(() => { onTotalChange(total); }, [total, onTotalChange]);

  const remove = async (entry: SearchHistoryEntry) => {
    setBusy(true);
    setError(null);
    try {
      await apiDeleteSearch(entry.id);
      setItems((prev) => prev.filter((s) => s.id !== entry.id));
      setTotal((t) => Math.max(0, t - 1));
      setNotice(`Deleted “${entry.query}”.`);
    } catch (err) {
      fail(err, "Failed to delete search.");
    } finally {
      setBusy(false);
    }
  };

  const clearAll = async () => {
    setBusy(true);
    setError(null);
    try {
      const n = await apiClearSearchHistory();
      setItems([]);
      setTotal(0);
      setNotice(`Search history cleared (${n} deleted).`);
    } catch (err) {
      fail(err, "Failed to clear search history.");
    } finally {
      setBusy(false);
      setConfirmClear(false);
    }
  };

  return (
    <section className="dash-card" aria-labelledby="history-title">
      <div className="dash-card-header">
        <h2 id="history-title" className="dash-card-title">🔍 Recent Searches</h2>
        {total > 0 && !confirmClear && (
          <button onClick={() => setConfirmClear(true)} disabled={busy} className="dash-edit-btn min-h-[44px]">
            Clear all
          </button>
        )}
      </div>

      {confirmClear && (
        <div className="hist-confirm" role="alertdialog" aria-labelledby="hist-confirm-text">
          <p id="hist-confirm-text">Delete all {total} saved searches? This can&apos;t be undone.</p>
          <div className="hist-confirm-actions">
            <button onClick={clearAll} disabled={busy} className="hist-danger min-h-[44px]" autoFocus>
              {busy ? "Deleting…" : "Yes, delete all"}
            </button>
            <button onClick={() => setConfirmClear(false)} disabled={busy} className="dash-edit-btn min-h-[44px]">
              Cancel
            </button>
          </div>
        </div>
      )}

      <p className="sr-only" aria-live="polite">{notice}</p>
      {error && (
        <div className="dash-error" role="alert">
          ⚠️ {error}
          <button onClick={() => load(0)} className="dash-retry min-h-[44px]">Retry</button>
        </div>
      )}

      {loading && items.length === 0 ? (
        <p className="dash-empty" role="status">Loading searches…</p>
      ) : items.length === 0 && !error ? (
        <p className="dash-empty">
          No saved searches. Searches you make in the AI chat appear here when you&apos;ve agreed to keep
          your details (the last 50, for up to 90 days).
        </p>
      ) : (
        <ul className="dash-search-list" aria-busy={loading}>
          {items.map((s) => (
            <li key={s.id} className="hist-row">
              <button
                onClick={() => router.push("/")}
                className="dash-search-item min-h-[44px]"
                title={`Search: ${s.query}`}
              >
                <span className="dash-search-icon" aria-hidden="true">🔍</span>
                <span className="dash-search-query">{s.query}</span>
                <span className="dash-search-meta">
                  {s.results_count} result{s.results_count !== 1 ? "s" : ""} · {s.language.toUpperCase()}
                  {s.searched_at && ` · ${new Date(s.searched_at).toLocaleDateString("en-IN", { day: "numeric", month: "short" })}`}
                </span>
              </button>
              <button
                onClick={() => remove(s)}
                disabled={busy}
                className="dash-scheme-remove min-h-[44px]"
                aria-label={`Delete search “${s.query}”`}
                title="Delete"
              >
                ✕
              </button>
            </li>
          ))}
        </ul>
      )}

      {items.length > 0 && items.length < total && (
        <button onClick={() => load(items.length)} disabled={loading} className="dash-edit-btn hist-more min-h-[44px]">
          {loading ? "Loading…" : `Show more (${total - items.length} left)`}
        </button>
      )}
    </section>
  );
}
