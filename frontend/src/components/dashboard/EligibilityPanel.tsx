"use client";

/**
 * Eligibility for every active scheme, computed from the saved profile by the
 * deterministic engine on the server (the AI never decides eligibility).
 * Status tabs, pagination, recalculate, and a notice when the result is stale.
 */

import React from "react";
import type {
  Criterion,
  DashboardSchemeResult,
  EligibilityDashboard,
  EligibilityStatusValue,
} from "@/lib/types";

export const STATUS_LABEL: Record<EligibilityStatusValue, string> = {
  ELIGIBLE: "Eligible",
  NOT_ELIGIBLE: "Not eligible",
  NEEDS_MORE_INFORMATION: "Needs more information",
  UNVERIFIABLE: "Can't verify",
};

const STATUS_ORDER: EligibilityStatusValue[] = [
  "ELIGIBLE", "NEEDS_MORE_INFORMATION", "NOT_ELIGIBLE", "UNVERIFIABLE",
];

export type StaleReason = "profile" | "schemes" | "engine";

const STALE_TEXT: Record<StaleReason, string> = {
  profile: "your profile changed",
  schemes: "scheme details or eligibility rules were updated",
  engine: "the eligibility checker was updated",
};

function show(v: unknown): string {
  if (v === null || v === undefined || v === "") return "not given";
  if (Array.isArray(v)) return v.join(", ");
  if (typeof v === "boolean") return v ? "yes" : "no";
  return String(v);
}

function criterionText(c: Criterion, kind: "matched" | "failed" | "missing"): string {
  const label = c.field.replace(/_/g, " ");
  if (kind === "missing") return `${label}: needed (${show(c.required_value)})`;
  return `${label}: yours ${show(c.user_value)} · needed ${show(c.required_value)}`;
}

function SchemeRow({
  item, saving, onSave, following, onFollow,
}: {
  item: DashboardSchemeResult;
  saving: boolean;
  onSave?: (item: DashboardSchemeResult) => void;
  following?: boolean;
  onFollow?: (item: DashboardSchemeResult, follow: boolean) => void;
}) {
  const hasCriteria =
    item.matched_criteria.length + item.failed_criteria.length + item.missing_criteria.length > 0;
  return (
    <li className="elig-item">
      <div className="elig-item-head">
        <span className="elig-item-name">{item.scheme_name || item.scheme_id}</span>
        <span className={`elig-badge elig-badge--${item.status}`}>{STATUS_LABEL[item.status]}</span>
      </div>
      {item.under_review && (
        <p className="elig-changed">
          🧑‍⚖️ Being checked by our team — treat this result as unconfirmed for now.{" "}
          <a href="#review-status" className="elig-link">See the check</a>
        </p>
      )}
      {item.status_changed_since_saved && (
        <p className="elig-changed">
          Changed since you saved it (was {item.saved_status?.replace(/_/g, " ").toLowerCase()}).
        </p>
      )}
      {item.status_note && <p className="elig-note">{item.status_note}</p>}
      {item.explanation && <p className="elig-expl">{item.explanation}</p>}
      <div className="elig-item-foot">
        {hasCriteria && (
          <details className="elig-why">
            <summary>Why this result?</summary>
            <ul>
              {item.failed_criteria.map((c, i) => <li key={`f${i}`} className="elig-crit--failed">✗ {criterionText(c, "failed")}</li>)}
              {item.missing_criteria.map((c, i) => <li key={`m${i}`} className="elig-crit--missing">? {criterionText(c, "missing")}</li>)}
              {item.matched_criteria.map((c, i) => <li key={`p${i}`} className="elig-crit--matched">✓ {criterionText(c, "matched")}</li>)}
            </ul>
          </details>
        )}
        {item.official_url && (
          <a href={item.official_url} target="_blank" rel="noopener noreferrer" className="elig-link">
            Official website<span className="sr-only"> for {item.scheme_name} (opens in a new tab)</span>
          </a>
        )}
        {item.saved ? (
          <a href="#saved-schemes" className="elig-link">
            ★ Saved — see checklist<span className="sr-only"> for {item.scheme_name}</span>
          </a>
        ) : onSave && (
          <button onClick={() => onSave(item)} disabled={saving} className="dash-edit-btn min-h-[44px]">
            {saving ? "Saving…" : "☆ Save"}<span className="sr-only"> {item.scheme_name}</span>
          </button>
        )}
        {/* saved schemes already send update notifications; others can be followed */}
        {!item.saved && onFollow && (
          <button onClick={() => onFollow(item, !following)} className="dash-edit-btn min-h-[44px]"
                  aria-pressed={following}>
            {following ? "🔕 Unfollow" : "🔔 Follow updates"}<span className="sr-only"> for {item.scheme_name}</span>
          </button>
        )}
      </div>
    </li>
  );
}

export default function EligibilityPanel({
  data,
  loading,
  error,
  filter,
  page,
  staleReasons,
  onFilter,
  onPage,
  onRecalculate,
  onSave,
  savingId = null,
  saveError = null,
  followed,
  onFollow,
}: {
  data: EligibilityDashboard | null;
  loading: boolean;
  error: string | null;
  filter: EligibilityStatusValue | null;
  page: number;
  staleReasons: StaleReason[];
  onFilter: (s: EligibilityStatusValue | null) => void;
  onPage: (p: number) => void;
  onRecalculate: () => void;
  onSave?: (item: DashboardSchemeResult) => void;
  savingId?: string | null;
  saveError?: string | null;
  followed?: Set<string>;
  onFollow?: (item: DashboardSchemeResult, follow: boolean) => void;
}) {
  const total = data?.total ?? 0;
  const pages = data ? Math.max(1, Math.ceil(total / data.page_size)) : 1;
  const allCount = data ? Object.values(data.counts).reduce((a, b) => a + b, 0) : 0;
  const tabs: { key: EligibilityStatusValue | null; label: string; count: number }[] = [
    { key: null, label: "All", count: allCount },
    ...STATUS_ORDER.map((s) => ({ key: s, label: STATUS_LABEL[s], count: data?.counts[s] ?? 0 })),
  ];

  return (
    <section className="dash-card dash-card--wide" aria-labelledby="elig-title">
      <div className="dash-card-header">
        <h2 id="elig-title" className="dash-card-title">✅ Your Scheme Eligibility</h2>
        <button
          onClick={onRecalculate}
          disabled={loading}
          className="dash-edit-btn min-h-[44px]"
        >
          {loading ? "Checking…" : "Recalculate"}
        </button>
      </div>
      <p className="elig-sub">
        Checked against your saved profile using each scheme&apos;s official rules.
        {data && <> Last checked {new Date(data.computed_at).toLocaleString("en-IN", { dateStyle: "medium", timeStyle: "short" })} · {data.basis.scheme_count} schemes.</>}
      </p>

      {staleReasons.length > 0 && (
        <div className="elig-stale" role="status">
          <span>
            ⚠️ These results may be out of date: {staleReasons.map((r) => STALE_TEXT[r]).join(" and ")} since they
            were checked.
          </span>
          <button onClick={onRecalculate} disabled={loading} className="dash-primary-btn min-h-[44px]">
            Recalculate now
          </button>
        </div>
      )}

      {data && !data.has_profile && (
        <p className="elig-note">
          You haven&apos;t saved a profile yet, so most schemes show &ldquo;Needs more information&rdquo;.
          Save your details to get a real answer.
        </p>
      )}

      {saveError && <div className="dash-error" role="alert">⚠️ {saveError}</div>}

      <div role="tablist" aria-label="Filter by eligibility" className="elig-tabs">
        {tabs.map((t) => (
          <button
            key={t.key ?? "ALL"}
            role="tab"
            aria-selected={filter === t.key}
            aria-controls="elig-results"
            onClick={() => onFilter(t.key)}
            className={`elig-tab min-h-[44px] ${filter === t.key ? "elig-tab--active" : ""}`}
          >
            {t.label} <span className="elig-tab-count">{t.count}</span>
          </button>
        ))}
      </div>

      <div id="elig-results" role="tabpanel" aria-busy={loading} aria-live="polite">
        {error ? (
          <div className="dash-error" role="alert">
            ⚠️ {error}
            <button onClick={onRecalculate} className="dash-retry min-h-[44px]">Retry</button>
          </div>
        ) : loading && !data ? (
          <div className="elig-loading" role="status">
            <div className="dash-spinner-lg" aria-hidden="true" />
            <span>Checking your eligibility…</span>
          </div>
        ) : data && data.items.length === 0 ? (
          <p className="dash-empty">
            {filter ? `No schemes are “${STATUS_LABEL[filter].toLowerCase()}” for you right now.`
                    : "No active schemes to check right now."}
          </p>
        ) : data ? (
          <>
            <p className="sr-only">
              Showing {data.items.length} of {total} schemes{filter ? ` marked ${STATUS_LABEL[filter]}` : ""}, page {page} of {pages}.
            </p>
            <ol className={`elig-list ${loading ? "elig-list--busy" : ""}`} start={(page - 1) * data.page_size + 1}>
              {data.items.map((item) => (
                <SchemeRow key={item.scheme_id} item={item} saving={savingId === item.scheme_id} onSave={onSave}
                           following={followed?.has(item.scheme_id)} onFollow={onFollow} />
              ))}
            </ol>
          </>
        ) : null}
      </div>

      {data && pages > 1 && (
        <nav className="elig-pager" aria-label="Eligibility results pages">
          <button onClick={() => onPage(page - 1)} disabled={page <= 1 || loading} className="dash-edit-btn min-h-[44px]">
            ← Previous
          </button>
          <span>Page {page} of {pages}</span>
          <button onClick={() => onPage(page + 1)} disabled={page >= pages || loading} className="dash-edit-btn min-h-[44px]">
            Next →
          </button>
        </nav>
      )}
    </section>
  );
}
