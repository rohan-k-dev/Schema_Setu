"use client";

/**
 * Personalized Farmer Dashboard.
 *
 * Route: /dashboard
 * Protected: redirects to /auth if not signed in.
 *
 * Shows:
 *  - Welcome + account info
 *  - Profile completeness + quick edit link
 *  - Missing eligibility fields (action items)
 *  - Saved / bookmarked schemes
 *  - Recent searches
 *  - Quick-link to the AI chat
 */

import React, { useCallback, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { useAuth } from "@/lib/AuthContext";
import {
  apiGetDashboard,
  apiDeleteSavedScheme,
} from "@/lib/api";
import type { DashboardData, SavedScheme, SearchHistoryEntry } from "@/lib/types";

// ─── Sub-components ────────────────────────────────────────────────────────────

function ProfileCard({
  completeness,
  missingFields,
  onEdit,
}: {
  completeness: number;
  missingFields: string[];
  onEdit: () => void;
}) {
  const color =
    completeness >= 80 ? "#059669" : completeness >= 50 ? "#d97706" : "#dc2626";
  const label =
    completeness >= 80 ? "Great!" : completeness >= 50 ? "Almost there" : "Getting started";

  return (
    <div className="dash-card">
      <div className="dash-card-header">
        <span className="dash-card-title">👤 Your Profile</span>
        <button onClick={onEdit} className="dash-edit-btn">Edit Profile</button>
      </div>
      <div className="dash-progress-row">
        <span className="dash-progress-label">Completeness</span>
        <span className="dash-progress-pct" style={{ color }}>{completeness}%</span>
      </div>
      <div className="dash-progress-bar-bg">
        <div
          className="dash-progress-bar-fill"
          style={{ width: `${completeness}%`, background: color }}
        />
      </div>
      <p className="dash-progress-caption">
        {label} — {completeness < 100 && `${100 - completeness}% to go.`}
        {completeness === 100 && "Your profile is complete!"}
      </p>

      {missingFields.length > 0 && (
        <div className="dash-missing">
          <p className="dash-missing-title">⚠️ Missing critical fields:</p>
          <div className="dash-missing-chips">
            {missingFields.map((f) => (
              <span key={f} className="dash-missing-chip">
                {f.replace(/_/g, " ")}
              </span>
            ))}
          </div>
          <button onClick={onEdit} className="dash-fill-btn">Fill in now →</button>
        </div>
      )}
    </div>
  );
}

function SavedSchemesCard({
  schemes,
  onRemove,
}: {
  schemes: SavedScheme[];
  onRemove: (id: string) => void;
}) {
  const statusColor: Record<string, string> = {
    ELIGIBLE: "#059669",
    NOT_ELIGIBLE: "#dc2626",
    NEEDS_MORE_INFORMATION: "#d97706",
    UNVERIFIABLE: "#6b7280",
  };

  return (
    <div className="dash-card">
      <div className="dash-card-header">
        <span className="dash-card-title">🔖 Saved Schemes</span>
        <span className="dash-card-count">{schemes.length}</span>
      </div>
      {schemes.length === 0 ? (
        <p className="dash-empty">
          No saved schemes yet. Use the AI chat to find schemes and bookmark them.
        </p>
      ) : (
        <div className="dash-scheme-list">
          {schemes.map((s) => (
            <div key={s.id} className="dash-scheme-item">
              <div className="dash-scheme-info">
                <span className="dash-scheme-name">{s.scheme_name}</span>
                {s.eligibility_status && (
                  <span
                    className="dash-scheme-status"
                    style={{ color: statusColor[s.eligibility_status] || "#6b7280" }}
                  >
                    {s.eligibility_status.replace(/_/g, " ")}
                  </span>
                )}
                {s.notes && <span className="dash-scheme-notes">{s.notes}</span>}
              </div>
              <button
                onClick={() => onRemove(s.scheme_id)}
                className="dash-scheme-remove"
                aria-label={`Remove ${s.scheme_name}`}
                title="Remove"
              >
                ✕
              </button>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function RecentSearchesCard({ searches }: { searches: SearchHistoryEntry[] }) {
  const router = useRouter();
  return (
    <div className="dash-card">
      <div className="dash-card-header">
        <span className="dash-card-title">🔍 Recent Searches</span>
      </div>
      {searches.length === 0 ? (
        <p className="dash-empty">No searches yet. Start chatting with the AI!</p>
      ) : (
        <div className="dash-search-list">
          {searches.map((s) => (
            <button
              key={s.id}
              onClick={() => router.push("/")}
              className="dash-search-item"
              title={`Search: ${s.query}`}
            >
              <span className="dash-search-icon">🔍</span>
              <span className="dash-search-query">{s.query}</span>
              <span className="dash-search-meta">
                {s.results_count} result{s.results_count !== 1 ? "s" : ""} ·{" "}
                {s.language.toUpperCase()}
              </span>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

// ─── Main Dashboard ─────────────────────────────────────────────────────────────

export default function DashboardPage() {
  const router = useRouter();
  const { isAuthenticated, isLoading, accessToken, user, logout } = useAuth();

  const [data, setData] = useState<DashboardData | null>(null);
  const [pageLoading, setPageLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!isLoading && !isAuthenticated) {
      router.replace("/auth");
    }
  }, [isAuthenticated, isLoading, router]);

  const loadDashboard = useCallback(async () => {
    if (!accessToken) return;
    setPageLoading(true);
    setError(null);
    try {
      const d = await apiGetDashboard(accessToken);
      setData(d);
    } catch {
      setError("Failed to load dashboard. Please try again.");
    } finally {
      setPageLoading(false);
    }
  }, [accessToken]);

  useEffect(() => {
    if (accessToken) loadDashboard();
  }, [accessToken, loadDashboard]);

  const handleRemoveScheme = useCallback(
    async (schemeId: string) => {
      if (!accessToken) return;
      try {
        await apiDeleteSavedScheme(accessToken, schemeId);
        setData((prev) =>
          prev
            ? { ...prev, saved_schemes: prev.saved_schemes.filter((s) => s.scheme_id !== schemeId) }
            : prev
        );
      } catch {
        /* best-effort */
      }
    },
    [accessToken]
  );

  const handleLogout = async () => {
    await logout();
    router.push("/auth");
  };

  if (isLoading || pageLoading) {
    return (
      <div className="dash-loading">
        <div className="dash-spinner-lg" />
        <p>Loading your dashboard…</p>
      </div>
    );
  }

  const displayName =
    data?.account.full_name || user?.full_name || user?.email?.split("@")[0] || "Farmer";

  return (
    <div className="dash-page">
      {/* Header */}
      <header className="dash-header">
        <div className="dash-header-inner">
          <div className="dash-header-brand">
            <span className="dash-header-icon">🌾</span>
            <span className="dash-header-name">SchemeSetu</span>
          </div>
          <nav className="dash-header-nav">
            <button onClick={() => router.push("/")} className="dash-nav-btn">
              💬 AI Chat
            </button>
            <button onClick={() => router.push("/profile")} className="dash-nav-btn">
              ✏️ Edit Profile
            </button>
            <button onClick={handleLogout} className="dash-nav-btn dash-nav-btn--logout">
              Sign Out
            </button>
          </nav>
        </div>
      </header>

      <main className="dash-main">
        {/* Welcome banner */}
        <div className="dash-welcome">
          <div className="dash-welcome-text">
            <h1 className="dash-welcome-title">
              Namaste, {displayName}! 🙏
            </h1>
            <p className="dash-welcome-sub">
              Here&apos;s your personalized government scheme dashboard.
            </p>
          </div>
          <div className="dash-welcome-stats">
            <div className="dash-stat">
              <span className="dash-stat-num">{data?.saved_schemes.length ?? 0}</span>
              <span className="dash-stat-label">Saved Schemes</span>
            </div>
            <div className="dash-stat">
              <span className="dash-stat-num">{data?.profile_completeness ?? 0}%</span>
              <span className="dash-stat-label">Profile Complete</span>
            </div>
            <div className="dash-stat">
              <span className="dash-stat-num">{data?.recent_searches.length ?? 0}</span>
              <span className="dash-stat-label">Recent Searches</span>
            </div>
          </div>
        </div>

        {error && (
          <div className="dash-error" role="alert">
            ⚠️ {error}
            <button onClick={loadDashboard} className="dash-retry">Retry</button>
          </div>
        )}

        {/* Quick action CTA */}
        <div className="dash-cta">
          <div className="dash-cta-text">
            <h2 className="dash-cta-title">Find New Schemes</h2>
            <p className="dash-cta-sub">
              Chat with our AI assistant in your language to discover eligible government schemes.
            </p>
          </div>
          <button onClick={() => router.push("/")} className="dash-cta-btn">
            Start Chatting →
          </button>
        </div>

        {/* Grid layout */}
        <div className="dash-grid">
          {/* Profile + missing fields */}
          <ProfileCard
            completeness={data?.profile_completeness ?? 0}
            missingFields={data?.missing_fields ?? []}
            onEdit={() => router.push("/profile")}
          />

          {/* Account info */}
          <div className="dash-card">
            <div className="dash-card-header">
              <span className="dash-card-title">🏦 Account</span>
              {data?.account.is_verified && (
                <span className="dash-verified-badge">✓ Verified</span>
              )}
            </div>
            <dl className="dash-account-list">
              <dt className="dash-account-dt">Email</dt>
              <dd className="dash-account-dd">{data?.account.email}</dd>
              {data?.account.phone && (
                <>
                  <dt className="dash-account-dt">Phone</dt>
                  <dd className="dash-account-dd">{data.account.phone}</dd>
                </>
              )}
              <dt className="dash-account-dt">Member since</dt>
              <dd className="dash-account-dd">
                {data?.account.created_at
                  ? new Date(data.account.created_at).toLocaleDateString("en-IN", {
                      year: "numeric", month: "long", day: "numeric",
                    })
                  : "—"}
              </dd>
              <dt className="dash-account-dt">Last login</dt>
              <dd className="dash-account-dd">
                {data?.account.last_login_at
                  ? new Date(data.account.last_login_at).toLocaleString("en-IN", {
                      dateStyle: "medium", timeStyle: "short",
                    })
                  : "—"}
              </dd>
            </dl>
          </div>

          {/* Profile summary (if set) */}
          {data?.profile && (
            <div className="dash-card">
              <div className="dash-card-header">
                <span className="dash-card-title">🌱 Profile Summary</span>
                <button onClick={() => router.push("/profile")} className="dash-edit-btn">
                  Edit
                </button>
              </div>
              <dl className="dash-account-list">
                {data.profile.state && (
                  <><dt className="dash-account-dt">State</dt><dd className="dash-account-dd">{data.profile.state}</dd></>
                )}
                {data.profile.district && (
                  <><dt className="dash-account-dt">District</dt><dd className="dash-account-dd">{data.profile.district}</dd></>
                )}
                {data.profile.primary_crop && (
                  <><dt className="dash-account-dt">Primary Crop</dt><dd className="dash-account-dd">{data.profile.primary_crop}</dd></>
                )}
                {data.profile.land_size_acres != null && (
                  <><dt className="dash-account-dt">Land Size</dt><dd className="dash-account-dd">{data.profile.land_size_acres} acres</dd></>
                )}
                {data.profile.category && (
                  <><dt className="dash-account-dt">Category</dt><dd className="dash-account-dd">{data.profile.category}</dd></>
                )}
                {data.profile.age != null && (
                  <><dt className="dash-account-dt">Age</dt><dd className="dash-account-dd">{data.profile.age} years</dd></>
                )}
              </dl>
            </div>
          )}

          {/* No profile yet */}
          {!data?.profile && (
            <div className="dash-card dash-card--highlight">
              <div className="dash-card-header">
                <span className="dash-card-title">🌱 Profile Not Set</span>
              </div>
              <p className="dash-empty">
                Set up your profile to get personalized scheme recommendations tailored
                to your state, crop, land size, and more.
              </p>
              <button onClick={() => router.push("/profile")} className="dash-fill-btn">
                Set Up Profile →
              </button>
            </div>
          )}

          {/* Saved schemes */}
          <SavedSchemesCard
            schemes={data?.saved_schemes ?? []}
            onRemove={handleRemoveScheme}
          />

          {/* Recent searches */}
          <RecentSearchesCard searches={data?.recent_searches ?? []} />
        </div>
      </main>

      <footer className="dash-footer">
        SchemeSetu v1.0.0 · Helping Indian farmers discover government schemes
      </footer>

      <style>{`
        .dash-page {
          min-height: 100vh;
          background: #f0fdf4;
          font-family: var(--font-geist-sans, sans-serif);
        }
        .dash-loading {
          min-height: 100vh;
          display: flex;
          flex-direction: column;
          align-items: center;
          justify-content: center;
          gap: 1rem;
          background: #f0fdf4;
          color: #6b7280;
          font-family: var(--font-geist-sans, sans-serif);
        }
        /* Header */
        .dash-header {
          background: linear-gradient(135deg, #064e3b 0%, #065f46 100%);
          color: white;
          padding: 0.85rem 1.5rem;
          position: sticky;
          top: 0;
          z-index: 20;
          box-shadow: 0 2px 16px rgba(0,0,0,0.25);
        }
        .dash-header-inner {
          max-width: 1200px;
          margin: 0 auto;
          display: flex;
          align-items: center;
          justify-content: space-between;
          gap: 1rem;
        }
        .dash-header-brand {
          display: flex;
          align-items: center;
          gap: 0.5rem;
          font-size: 1.15rem;
          font-weight: 800;
          letter-spacing: -0.01em;
        }
        .dash-header-icon { font-size: 1.4rem; }
        .dash-header-name { color: white; }
        .dash-header-nav {
          display: flex;
          align-items: center;
          gap: 0.5rem;
          flex-wrap: wrap;
        }
        .dash-nav-btn {
          padding: 0.45rem 0.9rem;
          background: rgba(255,255,255,0.12);
          border: 1px solid rgba(255,255,255,0.18);
          color: white;
          border-radius: 0.5rem;
          font-size: 0.82rem;
          font-weight: 600;
          cursor: pointer;
          transition: all 0.2s;
          white-space: nowrap;
        }
        .dash-nav-btn:hover { background: rgba(255,255,255,0.22); }
        .dash-nav-btn--logout {
          background: rgba(239,68,68,0.2);
          border-color: rgba(239,68,68,0.3);
        }
        .dash-nav-btn--logout:hover { background: rgba(239,68,68,0.35); }
        /* Main */
        .dash-main {
          max-width: 1200px;
          margin: 0 auto;
          padding: 1.5rem 1rem 3rem;
        }
        /* Welcome */
        .dash-welcome {
          background: linear-gradient(135deg, #059669 0%, #047857 100%);
          border-radius: 1.25rem;
          padding: 1.75rem 2rem;
          margin-bottom: 1.5rem;
          color: white;
          display: flex;
          align-items: center;
          justify-content: space-between;
          gap: 1.5rem;
          flex-wrap: wrap;
          box-shadow: 0 8px 24px rgba(5,150,105,0.35);
        }
        .dash-welcome-title {
          font-size: 1.5rem;
          font-weight: 800;
          margin: 0 0 0.25rem;
          letter-spacing: -0.02em;
        }
        .dash-welcome-sub {
          font-size: 0.9rem;
          opacity: 0.9;
          margin: 0;
        }
        .dash-welcome-stats {
          display: flex;
          gap: 1.5rem;
          flex-wrap: wrap;
        }
        .dash-stat {
          text-align: center;
        }
        .dash-stat-num {
          display: block;
          font-size: 1.75rem;
          font-weight: 900;
          line-height: 1;
        }
        .dash-stat-label {
          font-size: 0.72rem;
          opacity: 0.85;
          text-transform: uppercase;
          letter-spacing: 0.04em;
          font-weight: 600;
        }
        /* Error */
        .dash-error {
          background: #fef2f2;
          color: #991b1b;
          border: 1px solid #fecaca;
          border-radius: 0.75rem;
          padding: 0.85rem 1rem;
          font-size: 0.875rem;
          font-weight: 500;
          margin-bottom: 1.25rem;
          display: flex;
          align-items: center;
          justify-content: space-between;
          gap: 0.75rem;
        }
        .dash-retry {
          background: #dc2626;
          color: white;
          border: none;
          border-radius: 0.5rem;
          padding: 0.3rem 0.8rem;
          font-size: 0.8rem;
          font-weight: 700;
          cursor: pointer;
        }
        /* CTA */
        .dash-cta {
          background: linear-gradient(135deg, #1e40af 0%, #2563eb 100%);
          border-radius: 1.1rem;
          padding: 1.5rem 2rem;
          margin-bottom: 1.5rem;
          color: white;
          display: flex;
          align-items: center;
          justify-content: space-between;
          gap: 1rem;
          flex-wrap: wrap;
          box-shadow: 0 6px 20px rgba(37,99,235,0.3);
        }
        .dash-cta-title {
          font-size: 1.15rem;
          font-weight: 800;
          margin: 0 0 0.2rem;
        }
        .dash-cta-sub {
          font-size: 0.85rem;
          opacity: 0.9;
          margin: 0;
        }
        .dash-cta-btn {
          padding: 0.7rem 1.75rem;
          background: white;
          color: #1e40af;
          border: none;
          border-radius: 0.7rem;
          font-size: 0.9rem;
          font-weight: 800;
          cursor: pointer;
          transition: all 0.2s;
          white-space: nowrap;
          box-shadow: 0 2px 8px rgba(0,0,0,0.15);
        }
        .dash-cta-btn:hover {
          background: #f0f9ff;
          transform: translateY(-2px);
          box-shadow: 0 4px 12px rgba(0,0,0,0.2);
        }
        /* Grid */
        .dash-grid {
          display: grid;
          grid-template-columns: repeat(auto-fill, minmax(340px, 1fr));
          gap: 1.25rem;
        }
        @media (max-width: 560px) {
          .dash-grid { grid-template-columns: 1fr; }
          .dash-welcome { flex-direction: column; align-items: flex-start; }
        }
        /* Cards */
        .dash-card {
          background: white;
          border-radius: 1rem;
          padding: 1.25rem 1.5rem;
          box-shadow: 0 2px 12px rgba(0,0,0,0.06);
          border: 1px solid #e5e7eb;
          transition: box-shadow 0.2s;
        }
        .dash-card:hover { box-shadow: 0 4px 20px rgba(0,0,0,0.1); }
        .dash-card--highlight {
          border-color: #d1fae5;
          background: #f0fdf4;
        }
        .dash-card-header {
          display: flex;
          align-items: center;
          justify-content: space-between;
          margin-bottom: 1rem;
        }
        .dash-card-title {
          font-size: 0.95rem;
          font-weight: 700;
          color: #064e3b;
        }
        .dash-card-count {
          background: #d1fae5;
          color: #065f46;
          border-radius: 99px;
          font-size: 0.78rem;
          font-weight: 700;
          padding: 0.15rem 0.55rem;
        }
        .dash-edit-btn {
          background: #f0fdf4;
          border: 1px solid #d1fae5;
          color: #059669;
          padding: 0.3rem 0.75rem;
          border-radius: 0.5rem;
          font-size: 0.8rem;
          font-weight: 600;
          cursor: pointer;
          transition: all 0.2s;
        }
        .dash-edit-btn:hover { background: #d1fae5; }
        /* Verified badge */
        .dash-verified-badge {
          background: #d1fae5;
          color: #065f46;
          border-radius: 99px;
          font-size: 0.75rem;
          font-weight: 700;
          padding: 0.15rem 0.6rem;
        }
        /* Progress */
        .dash-progress-row {
          display: flex;
          justify-content: space-between;
          margin-bottom: 0.4rem;
        }
        .dash-progress-label {
          font-size: 0.82rem;
          color: #4b5563;
          font-weight: 600;
        }
        .dash-progress-pct {
          font-size: 0.9rem;
          font-weight: 800;
        }
        .dash-progress-bar-bg {
          height: 8px;
          background: #e5e7eb;
          border-radius: 99px;
          overflow: hidden;
          margin-bottom: 0.4rem;
        }
        .dash-progress-bar-fill {
          height: 100%;
          border-radius: 99px;
          transition: width 0.6s ease;
        }
        .dash-progress-caption {
          font-size: 0.78rem;
          color: #6b7280;
          margin: 0 0 0.75rem;
        }
        /* Missing fields */
        .dash-missing {
          background: #fffbeb;
          border: 1px solid #fde68a;
          border-radius: 0.65rem;
          padding: 0.75rem;
        }
        .dash-missing-title {
          font-size: 0.82rem;
          font-weight: 700;
          color: #92400e;
          margin: 0 0 0.4rem;
        }
        .dash-missing-chips {
          display: flex;
          flex-wrap: wrap;
          gap: 0.35rem;
          margin-bottom: 0.6rem;
        }
        .dash-missing-chip {
          background: #fef3c7;
          color: #92400e;
          border: 1px solid #fde68a;
          border-radius: 99px;
          font-size: 0.75rem;
          font-weight: 600;
          padding: 0.15rem 0.55rem;
          text-transform: capitalize;
        }
        .dash-fill-btn {
          background: none;
          border: none;
          color: #d97706;
          font-size: 0.82rem;
          font-weight: 700;
          cursor: pointer;
          padding: 0;
          text-decoration: underline;
        }
        /* Account list */
        .dash-account-list {
          display: grid;
          grid-template-columns: auto 1fr;
          gap: 0.4rem 1rem;
          margin: 0;
        }
        .dash-account-dt {
          font-size: 0.78rem;
          font-weight: 600;
          color: #6b7280;
          white-space: nowrap;
        }
        .dash-account-dd {
          font-size: 0.85rem;
          color: #111827;
          font-weight: 500;
          margin: 0;
          word-break: break-word;
        }
        /* Schemes */
        .dash-scheme-list {
          display: flex;
          flex-direction: column;
          gap: 0.6rem;
          max-height: 320px;
          overflow-y: auto;
        }
        .dash-scheme-item {
          display: flex;
          align-items: flex-start;
          justify-content: space-between;
          gap: 0.5rem;
          padding: 0.65rem 0.75rem;
          background: #f9fafb;
          border: 1px solid #e5e7eb;
          border-radius: 0.6rem;
          transition: background 0.15s;
        }
        .dash-scheme-item:hover { background: #f0fdf4; border-color: #d1fae5; }
        .dash-scheme-info {
          display: flex;
          flex-direction: column;
          gap: 0.15rem;
          min-width: 0;
        }
        .dash-scheme-name {
          font-size: 0.875rem;
          font-weight: 700;
          color: #111827;
          white-space: nowrap;
          overflow: hidden;
          text-overflow: ellipsis;
        }
        .dash-scheme-status {
          font-size: 0.72rem;
          font-weight: 700;
          text-transform: uppercase;
          letter-spacing: 0.04em;
        }
        .dash-scheme-notes {
          font-size: 0.75rem;
          color: #6b7280;
          font-style: italic;
        }
        .dash-scheme-remove {
          background: none;
          border: none;
          color: #9ca3af;
          cursor: pointer;
          font-size: 0.8rem;
          padding: 0.15rem 0.3rem;
          border-radius: 0.3rem;
          transition: all 0.15s;
          flex-shrink: 0;
        }
        .dash-scheme-remove:hover { color: #dc2626; background: #fef2f2; }
        /* Searches */
        .dash-search-list {
          display: flex;
          flex-direction: column;
          gap: 0.4rem;
        }
        .dash-search-item {
          display: flex;
          align-items: center;
          gap: 0.6rem;
          padding: 0.6rem 0.75rem;
          background: #f9fafb;
          border: 1px solid #e5e7eb;
          border-radius: 0.6rem;
          cursor: pointer;
          transition: all 0.15s;
          text-align: left;
          width: 100%;
        }
        .dash-search-item:hover { background: #f0fdf4; border-color: #d1fae5; }
        .dash-search-icon { font-size: 0.85rem; flex-shrink: 0; }
        .dash-search-query {
          font-size: 0.85rem;
          color: #111827;
          font-weight: 500;
          flex: 1;
          min-width: 0;
          white-space: nowrap;
          overflow: hidden;
          text-overflow: ellipsis;
        }
        .dash-search-meta {
          font-size: 0.72rem;
          color: #9ca3af;
          white-space: nowrap;
          flex-shrink: 0;
        }
        /* Empty */
        .dash-empty {
          font-size: 0.85rem;
          color: #6b7280;
          margin: 0;
          line-height: 1.6;
        }
        /* Footer */
        .dash-footer {
          text-align: center;
          font-size: 0.72rem;
          color: #9ca3af;
          padding: 1rem;
          border-top: 1px solid #e5e7eb;
          background: white;
        }
        /* Spinners */
        .dash-spinner-lg {
          width: 2.5rem;
          height: 2.5rem;
          border: 3px solid #d1fae5;
          border-top-color: #059669;
          border-radius: 50%;
          animation: spin 0.7s linear infinite;
        }
        @keyframes spin { to { transform: rotate(360deg); } }
      `}</style>
    </div>
  );
}
