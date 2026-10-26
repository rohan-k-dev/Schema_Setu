"use client";

/**
 * "More Relevant Schemes & Alternatives" (docs/RECOMMENDATIONS.md): schemes related to the farmer's
 * need that are NOT confirmed eligible. Each card says why it may be relevant and what still needs
 * checking; missing information, a known mismatch and incomplete scheme data look different.
 * Never shows an eligibility claim. Paged with "Show more"; schemes that don't match are collapsed.
 */

import React, { useState } from "react";
import type { RecommendationStatus, Scheme } from "@/lib/types";
import { FreshnessPanel } from "@/components/LiveCheck";
import { AlertTriangle, ExternalLink, HelpCircle, Info, Lightbulb, XCircle } from "lucide-react";

export const PAGE_SIZE = 5;

/** A stored date ("2026-09-26") as a local date with the year, or the raw value. */
function day(iso: string): string {
  const d = new Date(/^\d{4}-\d{2}-\d{2}$/.test(iso) ? `${iso}T00:00:00` : iso);
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleDateString(undefined, { dateStyle: "medium" });
}

const STATUS_BADGE: Record<RecommendationStatus, { text: string; cls: string; icon: React.ReactNode }> = {
  CONFIRMED_ELIGIBLE: { text: "Matches criteria", cls: "bg-emerald-50 text-emerald-800 border-emerald-200",
    icon: <Info className="h-3.5 w-3.5" /> },
  ADDITIONAL_INFORMATION_REQUIRED: { text: "Not confirmed — more information needed",
    cls: "bg-amber-50 text-amber-800 border-amber-200", icon: <HelpCircle className="h-3.5 w-3.5 text-amber-600" /> },
  ELIGIBILITY_UNCONFIRMED: { text: "Not confirmed — check the official criteria",
    cls: "bg-slate-50 text-slate-700 border-slate-300", icon: <Info className="h-3.5 w-3.5 text-slate-500" /> },
  SCHEME_INFORMATION_INCOMPLETE: { text: "Not confirmed — scheme details incomplete",
    cls: "bg-slate-50 text-slate-700 border-slate-300", icon: <AlertTriangle className="h-3.5 w-3.5 text-slate-500" /> },
  KNOWN_MISMATCH: { text: "Doesn't match a published criterion",
    cls: "bg-red-50 text-red-800 border-red-200", icon: <XCircle className="h-3.5 w-3.5 text-red-600" /> },
};

function Links({ s }: { s: Scheme }) {
  const official = s.official_url || s.source_url;
  return (
    <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
      {official && (
        <a href={official} target="_blank" rel="noopener noreferrer"
           className="inline-flex items-center gap-1 min-h-[32px] text-xs text-blue-700 hover:underline focus:outline-none focus-visible:ring-2 focus-visible:ring-blue-500 rounded">
          <ExternalLink className="h-3 w-3" />Official source<span className="sr-only"> for {s.name} (opens in a new tab)</span>
        </a>
      )}
      {s.application_url && (
        <a href={s.application_url} target="_blank" rel="noopener noreferrer"
           className="inline-flex items-center gap-1 min-h-[32px] text-xs text-blue-700 hover:underline focus:outline-none focus-visible:ring-2 focus-visible:ring-blue-500 rounded">
          <ExternalLink className="h-3 w-3" />Apply online<span className="sr-only"> for {s.name} (opens in a new tab)</span>
        </a>
      )}
      <span className="text-[11px] text-slate-500">
        {s.last_verified_at ? <>Last verified {day(s.last_verified_at)}</> : "Verification date not recorded"}
      </span>
    </div>
  );
}

export function AlternativeCard({ s }: { s: Scheme }) {
  const status = s.recommendation_status ?? "ELIGIBILITY_UNCONFIRMED";
  const badge = STATUS_BADGE[status];
  const r = s.relevance ?? {};
  const known = s.eligibility_summary;
  return (
    <div className="border border-slate-200 rounded-xl p-3 space-y-1.5 bg-white" role="article"
         aria-label={`Alternative scheme: ${s.name}`} data-testid="alternative" data-status={status}>
      <div className="flex items-start justify-between gap-2">
        <h4 className="font-semibold text-slate-800 text-sm leading-snug">{s.name}</h4>
        {r.categories && r.categories.length > 0 && (
          <span className="shrink-0 text-[10px] text-slate-500 text-right">{r.categories.slice(0, 2).join(" · ")}</span>
        )}
      </div>
      <span className={`inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-[11px] font-semibold ${badge.cls}`}>
        {badge.icon}{badge.text}
      </span>
      {s.description && <p className="text-xs text-slate-600">{s.description}</p>}

      {r.reasons && r.reasons.length > 0 && (
        <div className="text-xs text-slate-700">
          <span className="font-semibold flex items-center gap-1"><Lightbulb className="h-3 w-3 text-amber-500" />Why it may be relevant</span>
          <ul className="list-disc pl-5">{r.reasons.map((x, i) => <li key={i}>{x}</li>)}</ul>
        </div>
      )}

      {status === "KNOWN_MISMATCH" && (s.mismatches?.length ?? 0) > 0 && (
        <div className="text-xs text-red-800 bg-red-50 border border-red-100 rounded-lg p-2">
          <span className="font-semibold">Why it doesn&apos;t match now: </span>{s.mismatches!.join("; ")}
        </div>
      )}
      {status !== "KNOWN_MISMATCH" && (s.conditions_to_verify?.length ?? 0) > 0 && (
        <div className="text-xs text-amber-900 bg-amber-50 border border-amber-100 rounded-lg p-2">
          <span className="font-semibold">Still to check: </span>{s.conditions_to_verify!.join(" · ")}
        </div>
      )}
      {known && (
        <p className="text-xs text-slate-600"><span className="font-semibold text-slate-700">Published criteria: </span>{known}</p>
      )}
      <FreshnessPanel freshness={s.freshness} />
      <Links s={s} />
    </div>
  );
}

export default function AlternativesSection({ alternatives, notMatching }: { alternatives: Scheme[]; notMatching: Scheme[] }) {
  const [shown, setShown] = useState(PAGE_SIZE);
  const [openMismatch, setOpenMismatch] = useState(false);
  const visible = alternatives.slice(0, shown);
  const remaining = alternatives.length - visible.length;
  return (
    <section aria-labelledby="alternatives-heading" className="mt-5 pt-4 border-t border-slate-200" data-testid="alternatives-section">
      <h3 id="alternatives-heading" className="text-sm font-semibold text-slate-600 uppercase tracking-wider">
        More Relevant Schemes &amp; Alternatives ({alternatives.length})
      </h3>
      <p className="text-[11px] text-slate-500 mt-1 mb-3 leading-snug">
        Related support you may want to look at. <strong>Your eligibility for these is not confirmed</strong> — each
        card says why it may be relevant and what still needs checking.
      </p>
      {alternatives.length === 0 ? (
        <p className="text-xs text-slate-500 border border-dashed border-slate-200 rounded-xl p-3" data-testid="alternatives-empty">
          No other related schemes were found for your details. Ask about a specific need — for example irrigation,
          crop insurance, credit or livestock — or add your crop and land size to widen the search.
        </p>
      ) : (
        <div className="space-y-3">
          {visible.map((s) => <AlternativeCard key={s.scheme_id ?? s.name} s={s} />)}
          {remaining > 0 && (
            <button onClick={() => setShown(shown + PAGE_SIZE)}
                    className="w-full min-h-[44px] rounded-lg border border-slate-300 text-xs font-semibold text-slate-700 hover:bg-slate-50 focus:outline-none focus-visible:ring-2 focus-visible:ring-emerald-600">
              Show more ({Math.min(PAGE_SIZE, remaining)} of {remaining} more)
            </button>
          )}
        </div>
      )}
      {notMatching.length > 0 && (
        <div className="mt-3">
          <button onClick={() => setOpenMismatch(!openMismatch)} aria-expanded={openMismatch}
                  className="text-xs text-slate-600 underline min-h-[44px] focus:outline-none focus-visible:ring-2 focus-visible:ring-emerald-600 rounded">
            {openMismatch ? "Hide" : "Show"} schemes that don&apos;t match your details ({notMatching.length})
          </button>
          {openMismatch && (
            <div className="space-y-3 mt-2" data-testid="not-matching">
              {notMatching.map((s) => <AlternativeCard key={s.scheme_id ?? s.name} s={s} />)}
            </div>
          )}
        </div>
      )}
    </section>
  );
}
