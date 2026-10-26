"use client";

/**
 * In-app notifications about verified changes to schemes the farmer saved or follows
 * (docs/SCHEME_UPDATES.md). Every change was checked by the SchemeSetu team before it
 * was sent; the text says so.
 */

import React, { useCallback, useEffect, useState } from "react";
import { apiMarkAllRead, apiMarkNotificationRead, apiNotifications, ApiError } from "@/lib/api";
import type { AppNotification } from "@/lib/types";

export default function NotificationsPanel({ onUnauthorized }: { onUnauthorized: () => void }) {
  const [items, setItems] = useState<AppNotification[]>([]);
  const [unread, setUnread] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const page = await apiNotifications(false, 20, 0);
      setItems(page.items);
      setUnread(page.unread);
      setError(null);
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) onUnauthorized();
      else setError(err instanceof Error ? err.message : "Could not load notifications.");
    } finally {
      setLoading(false);
    }
  }, [onUnauthorized]);

  useEffect(() => { load(); }, [load]);

  const read = async (n: AppNotification) => {
    if (n.read) return;
    try {
      await apiMarkNotificationRead(n.id);
      setItems((prev) => prev.map((x) => (x.id === n.id ? { ...x, read: true } : x)));
      setUnread((u) => Math.max(0, u - 1));
    } catch { /* the next refresh shows the real state */ }
  };

  return (
    <section className="dash-card dash-card--wide" aria-labelledby="notif-title" id="notifications">
      <div className="dash-card-header">
        <h2 id="notif-title" className="dash-card-title">🔔 Notifications {unread > 0 && <span className="dash-card-count">{unread} new</span>}</h2>
        {unread > 0 && (
          <button className="dash-edit-btn min-h-[44px]"
                  onClick={async () => { try { await apiMarkAllRead(); load(); } catch { /* ignore */ } }}>
            Mark all read
          </button>
        )}
      </div>
      <p className="elig-sub">Changes to schemes you saved or follow, after the SchemeSetu team checked them against the official source.</p>
      {error && <div className="dash-error" role="alert">⚠️ {error}</div>}
      {loading && items.length === 0 ? <p className="dash-empty" role="status">Loading…</p>
        : items.length === 0 ? <p className="dash-empty">No notifications yet.</p> : (
          <ul className="sv-list">
            {items.map((n) => (
              <li key={n.id} className={`sv-scheme ${n.read ? "" : "notif-unread"}`}>
                <details onToggle={(e) => { if ((e.target as HTMLDetailsElement).open) read(n); }}>
                  <summary className="notif-summary">
                    {!n.read && <span className="sr-only">Unread: </span>}
                    {n.consequential && <span className="sv-stage sv-stage--PREPARING">Important</span>} {n.title}
                    <span className="dash-search-meta"> · {new Date(n.created_at).toLocaleDateString("en-IN", { day: "numeric", month: "short" })}</span>
                  </summary>
                  <p className="sv-note">{n.body}</p>
                </details>
              </li>
            ))}
          </ul>
        )}
    </section>
  );
}
