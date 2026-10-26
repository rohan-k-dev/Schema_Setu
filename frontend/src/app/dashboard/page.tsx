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
 *  - Eligibility for every active scheme (deterministic engine, saved profile),
 *    with status tabs, pagination, recalculate and a stale-result notice
 *  - Missing / conflicting profile details, editable in place
 *  - Saved schemes, each with a user-reported application checklist (docs/SAVED_SCHEMES.md);
 *    flagged when their status or the scheme's information has changed
 *  - Recent searches (delete one / clear all)
 *  - Quick-link to the AI chat
 */

import React, { useCallback, useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { useAuth } from "@/lib/AuthContext";
import {
  apiGetDashboard,
  apiGetEligibility,
  apiGetEligibilityBasis,
  apiSaveScheme,
  apiFollowedSchemes,
  apiFollowScheme,
  apiUnfollowScheme,
  ApiError,
} from "@/lib/api";
import NotificationsPanel from "@/components/dashboard/NotificationsPanel";
import ReviewStatusPanel from "@/components/dashboard/ReviewStatusPanel";
import NotificationSettingsPanel from "@/components/dashboard/NotificationSettingsPanel";
import type {
  DashboardData, DashboardSchemeResult, EligibilityDashboard, EligibilityStatusValue,
} from "@/lib/types";
import EligibilityPanel, { type StaleReason } from "@/components/dashboard/EligibilityPanel";
import ProfileFixesPanel from "@/components/dashboard/ProfileFixesPanel";
import SavedSchemesPanel from "@/components/dashboard/SavedSchemesPanel";
import SearchHistoryPanel from "@/components/dashboard/SearchHistoryPanel";

const BASIS_POLL_MS = 60_000;

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
        <button onClick={onEdit} className="dash-edit-btn min-h-[44px]">Edit Profile</button>
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
          <button onClick={onEdit} className="dash-fill-btn min-h-[44px]">Fill in now →</button>
        </div>
      )}
    </div>
  );
}

// ─── Main Dashboard ─────────────────────────────────────────────────────────────

export default function DashboardPage() {
  const router = useRouter();
  const { isAuthenticated, isLoading, user, logout, handleUnauthorized } = useAuth();
  const signedInId = user?.farmer_id ?? null;

  const [data, setData] = useState<DashboardData | null>(null);
  const [pageLoading, setPageLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!isLoading && !isAuthenticated) {
      router.replace("/auth");
    }
  }, [isAuthenticated, isLoading, router]);

  const loadDashboard = useCallback(async (silent = false) => {
    if (!signedInId) return;
    if (!silent) setPageLoading(true);
    setError(null);
    try {
      const d = await apiGetDashboard();
      setData(d);
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) handleUnauthorized();
      else setError("Failed to load dashboard. Please try again.");
    } finally {
      setPageLoading(false);
    }
  }, [signedInId, handleUnauthorized]);

  useEffect(() => {
    if (signedInId) loadDashboard();
  }, [signedInId, loadDashboard]);

  // ── Eligibility (computed on the server by the deterministic engine) ──
  const [elig, setElig] = useState<EligibilityDashboard | null>(null);
  const [eligLoading, setEligLoading] = useState(true);
  const [eligError, setEligError] = useState<string | null>(null);
  const [filter, setFilter] = useState<EligibilityStatusValue | null>(null);
  const [page, setPage] = useState(1);
  const [staleReasons, setStaleReasons] = useState<StaleReason[]>([]);
  const [fixNotice, setFixNotice] = useState<string | null>(null);
  const [historyTotal, setHistoryTotal] = useState<number | null>(null);
  const eligRef = useRef<EligibilityDashboard | null>(null);

  const loadEligibility = useCallback(async (f: EligibilityStatusValue | null, p: number) => {
    setEligLoading(true);
    setEligError(null);
    try {
      const d = await apiGetEligibility({ status: f, page: p });
      eligRef.current = d;
      setElig(d);
      setStaleReasons([]);
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) handleUnauthorized();
      else setEligError(err instanceof Error ? err.message : "Failed to check eligibility.");
    } finally {
      setEligLoading(false);
    }
  }, [handleUnauthorized]);

  useEffect(() => {
    if (signedInId) loadEligibility(filter, page);
  }, [signedInId, filter, page, loadEligibility]);

  // Stale check: compare the shown result's basis with the current one on focus and every minute.
  useEffect(() => {
    if (!signedInId) return;
    const check = async () => {
      const shown = eligRef.current;
      if (!shown || document.visibilityState !== "visible") return;
      try {
        const now = await apiGetEligibilityBasis();
        const reasons: StaleReason[] = [];
        if (now.profile_version !== shown.basis.profile_version) reasons.push("profile");
        if (now.data_fingerprint !== shown.basis.data_fingerprint) reasons.push("schemes");
        if (now.engine_version !== shown.basis.engine_version) reasons.push("engine");
        setStaleReasons(reasons);
      } catch {
        /* a failed check leaves the result as it is */
      }
    };
    const timer = window.setInterval(check, BASIS_POLL_MS);
    window.addEventListener("focus", check);
    document.addEventListener("visibilitychange", check);
    return () => {
      window.clearInterval(timer);
      window.removeEventListener("focus", check);
      document.removeEventListener("visibilitychange", check);
    };
  }, [signedInId]);

  const recalculate = useCallback(() => {
    loadDashboard(true);
    loadEligibility(filter, page);
  }, [loadDashboard, loadEligibility, filter, page]);

  const handleProfileFixed = useCallback((message: string) => {
    setFixNotice(message);
    recalculate();
  }, [recalculate]);

  const changeFilter = useCallback((f: EligibilityStatusValue | null) => {
    setFilter(f);
    setPage(1);
  }, []);

  // ── Saved schemes (checklists live in SavedSchemesPanel) ──
  const [savedCount, setSavedCount] = useState<number | null>(null);
  const [savedRefresh, setSavedRefresh] = useState(0);
  const [savingId, setSavingId] = useState<string | null>(null);
  const [saveError, setSaveError] = useState<string | null>(null);

  const handleSaveScheme = useCallback(async (item: DashboardSchemeResult) => {
    setSavingId(item.scheme_id);
    setSaveError(null);
    try {
      await apiSaveScheme({ scheme_id: item.scheme_id, eligibility_status: item.status });
      setElig((prev) => prev && {
        ...prev,
        items: prev.items.map((i) => (i.scheme_id === item.scheme_id
          ? { ...i, saved: true, saved_status: item.status } : i)),
      });
      setSavedRefresh((k) => k + 1);
      setFixNotice(`Saved “${item.scheme_name}”. Its checklist is under Saved Schemes & Applications.`);
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) handleUnauthorized();
      else setSaveError(err instanceof Error ? err.message : "Failed to save scheme.");
    } finally {
      setSavingId(null);
    }
  }, [handleUnauthorized]);

  // ── Following schemes for update notifications (docs/SCHEME_UPDATES.md) ──
  const [followed, setFollowed] = useState<Set<string>>(new Set());
  useEffect(() => {
    if (!signedInId) return;
    apiFollowedSchemes().then((rows) => setFollowed(new Set(rows.map((r) => r.scheme_id)))).catch(() => {});
  }, [signedInId]);
  const handleFollow = useCallback(async (item: DashboardSchemeResult, follow: boolean) => {
    try {
      if (follow) await apiFollowScheme(item.scheme_id);
      else await apiUnfollowScheme(item.scheme_id);
      setFollowed((prev) => { const s = new Set(prev); if (follow) s.add(item.scheme_id); else s.delete(item.scheme_id); return s; });
      setFixNotice(follow ? `You'll be told about verified changes to “${item.scheme_name}”.`
                          : `You won't get updates about “${item.scheme_name}” any more.`);
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) handleUnauthorized();
      else setSaveError(err instanceof Error ? err.message : "Could not change following.");
    }
  }, [handleUnauthorized]);

  const handleSavedChanged = useCallback(() => {
    loadEligibility(filter, page);
  }, [loadEligibility, filter, page]);

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
            <button onClick={() => router.push("/")} className="dash-nav-btn min-h-[44px]">
              💬 AI Chat
            </button>
            <button onClick={() => router.push("/profile")} className="dash-nav-btn min-h-[44px]">
              ✏️ Edit Profile
            </button>
            <button onClick={() => router.push("/account/security")} className="dash-nav-btn min-h-[44px]">
              🔒 Security
            </button>
            <button onClick={() => router.push("/privacy")} className="dash-nav-btn min-h-[44px]">
              🛡️ Privacy &amp; data
            </button>
            {/* display only: /admin and every admin API call are checked for ADMIN on the server */}
            {user?.role === "ADMIN" && (
              <button onClick={() => router.push("/admin")} className="dash-nav-btn min-h-[44px]">
                🛠️ Operations
              </button>
            )}
            {(user?.role === "REVIEWER" || user?.role === "ADMIN") && (
              <button onClick={() => router.push("/review")} className="dash-nav-btn min-h-[44px]">
                🧑‍⚖️ Review queue
              </button>
            )}
            <button onClick={handleLogout} className="dash-nav-btn dash-nav-btn--logout min-h-[44px]">
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
              <span className="dash-stat-num">{elig?.counts.ELIGIBLE ?? "–"}</span>
              <span className="dash-stat-label">Eligible Schemes</span>
            </div>
            <div className="dash-stat">
              <span className="dash-stat-num">{savedCount ?? data?.saved_schemes.length ?? 0}</span>
              <span className="dash-stat-label">Saved Schemes</span>
            </div>
            <div className="dash-stat">
              <span className="dash-stat-num">{data?.profile_completeness ?? 0}%</span>
              <span className="dash-stat-label">Profile Complete</span>
            </div>
            <div className="dash-stat">
              <span className="dash-stat-num">{historyTotal ?? data?.recent_searches.length ?? 0}</span>
              <span className="dash-stat-label">Recent Searches</span>
            </div>
          </div>
        </div>

        {error && (
          <div className="dash-error" role="alert">
            ⚠️ {error}
            <button onClick={() => loadDashboard()} className="dash-retry min-h-[44px]">Retry</button>
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
          <button onClick={() => router.push("/")} className="dash-cta-btn min-h-[44px]">
            Start Chatting →
          </button>
        </div>

        {fixNotice && (
          <p className="fix-notice" role="status">
            {fixNotice}
            <button onClick={() => setFixNotice(null)} className="dash-retry min-h-[44px]" aria-label="Dismiss message">✕</button>
          </p>
        )}

        {/* Grid layout */}
        <div className="dash-grid">
          <ProfileFixesPanel
            profile={data?.profile ?? null}
            missing={elig?.missing_details ?? []}
            conflicts={elig?.conflicts ?? []}
            onSaved={handleProfileFixed}
            onSetUp={() => router.push("/profile")}
          />

          <ReviewStatusPanel onUnauthorized={handleUnauthorized} />

          <EligibilityPanel
            data={elig}
            loading={eligLoading}
            error={eligError}
            filter={filter}
            page={page}
            staleReasons={staleReasons}
            onFilter={changeFilter}
            onPage={setPage}
            onRecalculate={recalculate}
            onSave={handleSaveScheme}
            savingId={savingId}
            saveError={saveError}
            followed={followed}
            onFollow={handleFollow}
          />

          <NotificationsPanel onUnauthorized={handleUnauthorized} />
          <NotificationSettingsPanel onUnauthorized={handleUnauthorized} />

          <SavedSchemesPanel
            changes={elig?.saved_status_changes ?? []}
            refreshKey={savedRefresh}
            onCountChange={setSavedCount}
            onChanged={handleSavedChanged}
            onUnauthorized={handleUnauthorized}
          />

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
                <button onClick={() => router.push("/profile")} className="dash-edit-btn min-h-[44px]">
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
                  <><dt className="dash-account-dt">Land Size</dt><dd className="dash-account-dd">
                    {data.profile.land_unit && data.profile.land_unit !== "acre" && data.profile.land_size != null
                      ? `${data.profile.land_size} ${data.profile.land_unit} (${data.profile.land_size_acres} acres)`
                      : `${data.profile.land_size_acres} acres`}
                  </dd></>
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
              <button onClick={() => router.push("/profile")} className="dash-fill-btn min-h-[44px]">
                Set Up Profile →
              </button>
            </div>
          )}

          {/* Recent searches */}
          <SearchHistoryPanel onTotalChange={setHistoryTotal} onUnauthorized={handleUnauthorized} />
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
        h2.dash-card-title { margin: 0; }
        .dash-card--wide { grid-column: 1 / -1; }
        .dash-main button:focus-visible, .dash-main a:focus-visible,
        .dash-main select:focus-visible, .dash-main input:focus-visible, .dash-main summary:focus-visible {
          outline: 3px solid #2563eb;
          outline-offset: 2px;
        }
        .dash-primary-btn {
          background: #059669;
          color: white;
          border: none;
          border-radius: 0.5rem;
          padding: 0.4rem 1rem;
          font-size: 0.85rem;
          font-weight: 600;
          cursor: pointer;
          white-space: nowrap;
        }
        .dash-primary-btn:hover { background: #047857; }
        .dash-primary-btn:disabled, .dash-edit-btn:disabled { opacity: 0.6; cursor: not-allowed; }
        /* Eligibility */
        .elig-sub { font-size: 0.8rem; color: #4b5563; margin: -0.5rem 0 0.9rem; }
        .elig-stale {
          display: flex; flex-wrap: wrap; align-items: center; justify-content: space-between; gap: 0.75rem;
          background: #fffbeb; border: 1px solid #fcd34d; color: #92400e;
          border-radius: 0.6rem; padding: 0.6rem 0.9rem; font-size: 0.85rem; margin-bottom: 0.9rem;
        }
        .elig-tabs { display: flex; flex-wrap: wrap; gap: 0.4rem; margin-bottom: 0.9rem; }
        .elig-tab {
          background: #f9fafb; border: 1px solid #e5e7eb; color: #374151;
          border-radius: 99px; padding: 0.3rem 0.85rem; font-size: 0.8rem; font-weight: 600; cursor: pointer;
        }
        .elig-tab--active { background: #064e3b; border-color: #064e3b; color: white; }
        .elig-tab-count {
          display: inline-block; min-width: 1.4rem; margin-left: 0.25rem; padding: 0 0.35rem;
          border-radius: 99px; background: rgba(0,0,0,0.08); font-size: 0.75rem;
        }
        .elig-tab--active .elig-tab-count { background: rgba(255,255,255,0.2); }
        .elig-loading { display: flex; align-items: center; gap: 0.75rem; color: #4b5563; font-size: 0.85rem; padding: 1rem 0; }
        .elig-list { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 0.6rem; }
        .elig-list--busy { opacity: 0.55; }
        .elig-item { border: 1px solid #e5e7eb; border-radius: 0.75rem; padding: 0.75rem 0.9rem; background: #fcfcfd; }
        .elig-item-head { display: flex; justify-content: space-between; align-items: flex-start; gap: 0.75rem; }
        .elig-item-name { font-weight: 600; color: #111827; font-size: 0.9rem; }
        .elig-badge { flex-shrink: 0; border-radius: 99px; padding: 0.15rem 0.6rem; font-size: 0.72rem; font-weight: 700; }
        .elig-badge--ELIGIBLE { background: #d1fae5; color: #065f46; }
        .elig-badge--NOT_ELIGIBLE { background: #fee2e2; color: #991b1b; }
        .elig-badge--NEEDS_MORE_INFORMATION { background: #fef3c7; color: #92400e; }
        .elig-badge--UNVERIFIABLE { background: #e5e7eb; color: #374151; }
        .elig-expl, .elig-note { font-size: 0.8rem; color: #4b5563; margin: 0.4rem 0 0; line-height: 1.5; }
        .elig-note { color: #6b7280; font-style: italic; }
        .elig-changed { display: block; font-size: 0.78rem; color: #b45309; font-weight: 600; margin: 0.35rem 0 0; font-style: normal; }
        .elig-item-foot { display: flex; flex-wrap: wrap; justify-content: space-between; align-items: center; gap: 0.5rem; margin-top: 0.4rem; }
        .elig-why { font-size: 0.8rem; color: #374151; }
        .elig-why summary { cursor: pointer; color: #059669; font-weight: 600; padding: 0.4rem 0; }
        .elig-why ul { margin: 0.25rem 0 0; padding-left: 0.25rem; list-style: none; }
        .elig-crit--failed { color: #991b1b; }
        .elig-crit--missing { color: #92400e; }
        .elig-crit--matched { color: #065f46; }
        .elig-link { font-size: 0.8rem; color: #1d4ed8; font-weight: 600; text-decoration: underline; padding: 0.4rem 0; }
        .elig-pager { display: flex; justify-content: center; align-items: center; gap: 1rem; margin-top: 1rem; font-size: 0.85rem; color: #374151; }
        /* Details to fix */
        .fix-group + .fix-group { margin-top: 1.1rem; }
        .fix-heading { font-size: 0.85rem; font-weight: 700; color: #374151; margin: 0 0 0.5rem; }
        .fix-list { list-style: none; margin: 0; padding: 0; display: grid; grid-template-columns: repeat(auto-fill, minmax(280px, 1fr)); gap: 0.75rem; }
        .fix-item, .fix-conflict { background: white; border: 1px solid #e5e7eb; border-radius: 0.6rem; padding: 0.7rem 0.8rem; }
        .fix-conflict { border-color: #fca5a5; }
        .fix-conflict > p { font-size: 0.82rem; color: #991b1b; margin: 0 0 0.5rem; }
        .fix-why { font-size: 0.78rem; color: #6b7280; margin: 0 0 0.4rem; }
        .fix-editor + .fix-editor { margin-top: 0.5rem; }
        .fix-label { display: block; font-size: 0.8rem; font-weight: 600; color: #111827; margin-bottom: 0.25rem; }
        .fix-row { display: flex; flex-wrap: wrap; gap: 0.4rem; }
        .fix-input {
          flex: 1; min-width: 7rem; min-height: 44px; border: 1px solid #d1d5db; border-radius: 0.5rem;
          padding: 0.3rem 0.6rem; font-size: 0.85rem; background: white; color: #111827;
        }
        .fix-input--num { max-width: 8rem; }
        .fix-error { color: #b91c1c; font-size: 0.78rem; margin: 0.3rem 0 0; }
        .fix-notice {
          display: flex; align-items: center; justify-content: space-between; gap: 0.75rem;
          background: #ecfdf5; border: 1px solid #a7f3d0; color: #065f46;
          border-radius: 0.6rem; padding: 0.4rem 0.9rem; font-size: 0.85rem; margin: 0 0 1rem;
        }
        /* Saved schemes + checklists */
        .sv-list { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 0.75rem; }
        .sv-scheme { border: 1px solid #e5e7eb; border-radius: 0.75rem; padding: 0.8rem 0.9rem; background: #fcfcfd; }
        .sv-scheme-head { display: flex; justify-content: space-between; align-items: flex-start; gap: 0.75rem; }
        .sv-scheme-name { font-weight: 700; color: #111827; font-size: 0.9rem; }
        .sv-stage { flex-shrink: 0; border-radius: 99px; padding: 0.15rem 0.6rem; font-size: 0.72rem; font-weight: 700; background: #e5e7eb; color: #374151; }
        .sv-stage--PREPARING { background: #fef3c7; color: #92400e; }
        .sv-stage--SUBMITTED { background: #dbeafe; color: #1e3a8a; }
        .sv-stage--ACKNOWLEDGED { background: #d1fae5; color: #065f46; }
        .sv-progress { margin-top: 0.5rem; }
        .sv-scheme-actions { display: flex; flex-wrap: wrap; align-items: center; gap: 0.6rem; margin-top: 0.25rem; }
        .sv-checklist { margin-top: 0.75rem; border-top: 1px solid #e5e7eb; padding-top: 0.75rem; }
        .sv-reported { font-size: 0.8rem; color: #1e3a8a; background: #eff6ff; border: 1px solid #bfdbfe; border-radius: 0.5rem; padding: 0.45rem 0.7rem; margin: 0 0 0.75rem; }
        .sv-group + .sv-group { margin-top: 0.9rem; }
        .sv-items { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 0.35rem; }
        .sv-item { border: 1px solid #f3f4f6; border-radius: 0.5rem; padding: 0.35rem 0.6rem; background: white; }
        .sv-item--retired { opacity: 0.75; }
        .sv-item--retired .sv-item-label { text-decoration: line-through; }
        .sv-item-main { display: flex; align-items: flex-start; gap: 0.6rem; min-height: 44px; }
        .sv-check { width: 1.25rem; height: 1.25rem; margin-top: 0.7rem; accent-color: #059669; flex-shrink: 0; cursor: pointer; }
        .sv-item-label { font-size: 0.85rem; color: #111827; padding: 0.55rem 0; cursor: pointer; flex: 1; }
        .sv-item-detail { display: block; font-size: 0.76rem; color: #6b7280; margin-top: 0.15rem; text-decoration: none; }
        .sv-new { font-size: 0.7rem; font-weight: 700; color: #b45309; }
        .sv-note { font-size: 0.8rem; color: #374151; margin: 0 0 0.2rem 1.85rem; white-space: pre-wrap; }
        .sv-note-edit { margin: 0.25rem 0 0.35rem 1.85rem; display: flex; flex-direction: column; gap: 0.4rem; }
        .sv-item-actions { display: flex; flex-wrap: wrap; gap: 0.75rem; margin-left: 1.85rem; }
        .sv-link { background: none; border: none; padding: 0; color: #047857; font-size: 0.78rem; font-weight: 600; cursor: pointer; text-decoration: underline; }
        .sv-link--danger { color: #b91c1c; }
        .sv-link:disabled { opacity: 0.6; cursor: not-allowed; }
        .sv-textarea { width: 100%; min-height: 3.5rem; resize: vertical; }
        .sv-notes-btn { margin-top: 0.4rem; }
        /* Notifications */
        .notif-unread { border-left: 4px solid #059669; }
        .notif-summary { cursor: pointer; font-size: 0.88rem; font-weight: 600; color: #111827; min-height: 44px; display: flex; align-items: center; gap: 0.4rem; flex-wrap: wrap; }
        .nset-group { border: none; padding: 0; margin: 0 0 0.9rem; }
        .nset-row { display: flex; align-items: center; gap: 0.5rem; font-size: 0.85rem; min-height: 44px; flex-wrap: wrap; }
        .nset-row input[type=checkbox] { width: 1.15rem; height: 1.15rem; accent-color: #059669; }
        .nset-consent { align-items: flex-start; }
        .nset-consent span { font-size: 0.8rem; color: #374151; }
        /* Search history */
        .hist-row { display: flex; align-items: center; gap: 0.3rem; }
        .hist-more { margin-top: 0.75rem; width: 100%; }
        .hist-confirm { background: #fef2f2; border: 1px solid #fecaca; border-radius: 0.6rem; padding: 0.7rem 0.9rem; margin-bottom: 0.75rem; font-size: 0.85rem; color: #7f1d1d; }
        .hist-confirm p { margin: 0 0 0.5rem; }
        .hist-confirm-actions { display: flex; gap: 0.5rem; }
        .hist-danger { background: #dc2626; color: white; border: none; border-radius: 0.5rem; padding: 0.3rem 0.9rem; font-weight: 600; font-size: 0.85rem; cursor: pointer; }
        .hist-danger:hover { background: #b91c1c; }
      `}</style>
    </div>
  );
}
