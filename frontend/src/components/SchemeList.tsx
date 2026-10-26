"use client";

import React, { useState } from "react";
import Link from "next/link";
import type { Scheme, EligibilityStatus, LiveCheckReport } from "@/lib/types";
import { FreshnessPanel, LiveCheckSummary } from "@/components/LiveCheck";
import AlternativesSection from "@/components/AlternativesSection";
import {
  CheckCircle2, AlertCircle, Sparkles, XCircle, HelpCircle, Info,
  ChevronDown, ChevronUp, FileText, ExternalLink, ListChecks, AlertTriangle,
} from "lucide-react";

interface SchemeListProps {
  schemes: Scheme[];
  /** Signed in: show Save on schemes from SchemeSetu's database (they have a scheme_id). */
  save?: {
    savedIds: Set<string>;
    savingId: string | null;
    error: { schemeId: string; message: string } | null;
    onSave: (scheme: Scheme) => void;
  };
  /** What the query-time check of official websites did for the latest question. */
  liveCheck?: LiveCheckReport | null;
}

type SaveProps = SchemeListProps["save"];

/**
 * Status badge configuration — text + icon, never color-only (§249, §50).
 */
const STATUS_CONFIG: Record<EligibilityStatus, {
  label: string;
  bgColor: string;
  textColor: string;
  borderColor: string;
  icon: React.ReactNode;
}> = {
  ELIGIBLE: {
    label: "Matches available criteria",
    bgColor: "bg-emerald-50",
    textColor: "text-emerald-800",
    borderColor: "border-emerald-200",
    icon: <CheckCircle2 className="h-3.5 w-3.5 text-emerald-600" />,
  },
  NEEDS_MORE_INFORMATION: {
    label: "More information needed",
    bgColor: "bg-amber-50",
    textColor: "text-amber-800",
    borderColor: "border-amber-200",
    icon: <HelpCircle className="h-3.5 w-3.5 text-amber-600" />,
  },
  NOT_ELIGIBLE: {
    label: "Does not match current criteria",
    bgColor: "bg-red-50",
    textColor: "text-red-800",
    borderColor: "border-red-200",
    icon: <XCircle className="h-3.5 w-3.5 text-red-600" />,
  },
  UNVERIFIABLE: {
    label: "Needs additional verification",
    bgColor: "bg-slate-50",
    textColor: "text-slate-700",
    borderColor: "border-slate-200",
    icon: <AlertTriangle className="h-3.5 w-3.5 text-slate-500" />,
  },
};

const FIELD_LABELS: Record<string, string> = {
  state: "State",
  district: "District",
  primary_crop: "Crop",
  land_size_acres: "Land size",
  annual_income: "Annual income",
  category: "Category",
  gender: "Gender",
  occupation: "Occupation",
  has_aadhaar: "Aadhaar status",
  has_land: "Land holding",
  age: "Age",
  residence: "Residence",
};

function fieldLabel(field: string): string {
  return FIELD_LABELS[field] || field.replace(/_/g, " ").replace(/\b\w/g, c => c.toUpperCase());
}

function EligibilityBadge({ status }: { status: EligibilityStatus }) {
  const config = STATUS_CONFIG[status];
  if (!config) return null;
  return (
    <div
      className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-[11px] font-semibold ${config.bgColor} ${config.textColor} border ${config.borderColor}`}
      role="status"
      aria-label={`Eligibility: ${config.label}`}
    >
      {config.icon}
      {config.label}
    </div>
  );
}

/** Human-readable criterion value (true → Yes, lists joined, "tamil nadu" → "Tamil Nadu"). */
function displayValue(v: unknown): string {
  if (v === true) return "Yes";
  if (v === false) return "No";
  if (Array.isArray(v)) return v.map(displayValue).join(", ");
  if (typeof v === "string" && v === v.toLowerCase() && v.length > 3) {
    return v.replace(/\b\w/g, (c) => c.toUpperCase());
  }
  return v == null ? "" : String(v);
}

function MatchedSection({ criteria }: { criteria: Scheme["matched_criteria"] }) {
  if (!criteria || criteria.length === 0) return null;
  return (
    <div className="space-y-0.5 mt-2">
      <span className="text-[11px] font-bold text-emerald-700 uppercase tracking-wider flex items-center">
        <Sparkles className="h-3 w-3 mr-1" /> Why it matches
      </span>
      <div className="bg-emerald-50/50 p-2 rounded-lg border border-emerald-100">
        {criteria.map((c, i) => (
          <p key={i} className="text-xs text-emerald-900">
            ✓ {fieldLabel(c.field)}: {displayValue(c.user_value)}
          </p>
        ))}
      </div>
    </div>
  );
}

function FailedSection({ criteria }: { criteria: Scheme["failed_criteria"] }) {
  if (!criteria || criteria.length === 0) return null;
  return (
    <div className="space-y-0.5 mt-2">
      <span className="text-[11px] font-bold text-red-700 uppercase tracking-wider">
        Does not match
      </span>
      <div className="bg-red-50/50 p-2 rounded-lg border border-red-100">
        {criteria.map((c, i) => (
          <p key={i} className="text-xs text-red-900">
            ✗ {fieldLabel(c.field)}: profile has {displayValue(c.user_value ?? "N/A")}, required: {displayValue(c.required_value)}
          </p>
        ))}
      </div>
    </div>
  );
}

function MissingSection({ fields }: { fields?: string[] }) {
  if (!fields || fields.length === 0) return null;
  return (
    <div className="space-y-0.5 mt-2">
      <span className="text-[11px] font-bold text-amber-700 uppercase tracking-wider">
        Missing information
      </span>
      <div className="bg-amber-50/50 p-2 rounded-lg border border-amber-100">
        {fields.map((f, i) => (
          <p key={i} className="text-xs text-amber-900">
            ○ {fieldLabel(f)}
          </p>
        ))}
      </div>
    </div>
  );
}

/**
 * Expandable scheme card details — documents, steps, source link (§51–§55).
 */
function SchemeDetails({ scheme }: { scheme: Scheme }) {
  // Backend contract: documents / application_steps / official_url (legacy names kept as fallback)
  const documents = scheme.documents ?? scheme.required_documents ?? [];
  const steps = scheme.application_steps ?? [];
  const sourceUrl = scheme.official_url || scheme.source_url;
  const hasDocuments = documents.length > 0;
  const hasSteps = steps.length > 0;
  const hasSource = Boolean(sourceUrl);

  if (!hasDocuments && !hasSteps && !hasSource) return null;

  return (
    <div className="mt-2 space-y-2 animate-in slide-in-from-top-2 duration-200">
      {/* Required Documents (§51) */}
      {hasDocuments && (
        <div>
          <span className="text-[11px] font-bold text-slate-600 uppercase tracking-wider flex items-center gap-1">
            <FileText className="h-3 w-3" /> Required Documents
          </span>
          <ul className="mt-1 pl-4 space-y-0.5">
            {documents.map((doc, i) => (
              <li key={i} className="text-xs text-slate-700 list-disc">{doc}</li>
            ))}
          </ul>
        </div>
      )}

      {/* Application Steps (§52) */}
      {hasSteps && (
        <div>
          <span className="text-[11px] font-bold text-slate-600 uppercase tracking-wider flex items-center gap-1">
            <ListChecks className="h-3 w-3" /> How to Apply
          </span>
          <ol className="mt-1 pl-4 space-y-0.5">
            {steps.map((step, i) => (
              <li key={i} className="text-xs text-slate-700 list-decimal">{step}</li>
            ))}
          </ol>
        </div>
      )}

      {/* Source Link (§53, §93) */}
      {hasSource && (
        <div>
          <a
            href={sourceUrl}
            target="_blank"
            rel="noopener noreferrer"
            className="inline-flex items-center gap-1 min-h-[44px] text-xs text-blue-600 hover:text-blue-800 hover:underline focus:outline-none focus-visible:ring-2 focus-visible:ring-blue-500 rounded"
          >
            <ExternalLink className="h-3 w-3" />
            View official source
            <span className="sr-only"> (opens in a new tab)</span>
          </a>
        </div>
      )}
    </div>
  );
}

/**
 * Single expandable scheme card.
 */
function SaveButton({ scheme, save }: { scheme: Scheme; save: NonNullable<SaveProps> }) {
  const id = scheme.scheme_id;
  if (!id) return null;
  const name = scheme.scheme_name || scheme.name;
  if (save.savedIds.has(id)) {
    return (
      <Link href="/dashboard#saved-schemes"
            className="inline-flex items-center min-h-[44px] text-xs font-semibold text-emerald-700 hover:underline focus:outline-none focus-visible:ring-2 focus-visible:ring-emerald-600 rounded">
        ★ Saved — checklist on your dashboard<span className="sr-only"> for {name}</span>
      </Link>
    );
  }
  return (
    <button
      onClick={() => save.onSave(scheme)}
      disabled={save.savingId === id}
      className="inline-flex items-center min-h-[44px] px-3 rounded-lg border border-emerald-200 bg-white text-xs font-semibold text-emerald-800 hover:bg-emerald-50 disabled:opacity-60 focus:outline-none focus-visible:ring-2 focus-visible:ring-emerald-600"
    >
      {save.savingId === id ? "Saving…" : "☆ Save scheme"}<span className="sr-only"> {name}</span>
    </button>
  );
}

function SchemeCard({ scheme, idx, save }: { scheme: Scheme; idx: number; save?: SaveProps }) {
  const [expanded, setExpanded] = useState(false);
  const status = scheme.eligibility_status;
  const cardBorder = status === "ELIGIBLE" ? "border-emerald-100 bg-emerald-50/30"
    : status === "NEEDS_MORE_INFORMATION" ? "border-amber-100 bg-amber-50/20"
    : status === "NOT_ELIGIBLE" ? "border-red-100 bg-red-50/20"
    : "border-slate-100 bg-slate-50/20";

  const hasDetails = (scheme.documents?.length ?? scheme.required_documents?.length ?? 0) > 0
    || (scheme.application_steps?.length ?? 0) > 0
    || Boolean(scheme.official_url || scheme.source_url);

  return (
    <div
      className={`border rounded-xl p-4 space-y-2 transition-all ${cardBorder}`}
      role="article"
      aria-label={`Scheme: ${scheme.scheme_name || scheme.name}`}
      id={`scheme-card-${idx}`}
    >
      <div className="flex items-start justify-between gap-2">
        <h3 className="font-bold text-slate-800 text-sm leading-snug">
          {scheme.scheme_name || scheme.name}
        </h3>
        <div className="flex items-center gap-1.5 shrink-0">
          {scheme.rank && (
            <span className="text-[10px] font-mono text-slate-400">#{scheme.rank}</span>
          )}
          {hasDetails && (
            <button
              onClick={() => setExpanded(!expanded)}
              className="p-1 rounded-lg hover:bg-slate-200/50 transition-colors min-w-[44px] min-h-[44px] flex items-center justify-center focus:outline-none focus-visible:ring-2 focus-visible:ring-emerald-600"
              aria-expanded={expanded}
              aria-label={expanded ? "Collapse details" : "Expand details"}
            >
              {expanded
                ? <ChevronUp className="h-4 w-4 text-slate-400" />
                : <ChevronDown className="h-4 w-4 text-slate-400" />
              }
            </button>
          )}
        </div>
      </div>

      {/* Eligibility status badge — text + icon, not color-only (§249, §50) */}
      {status && <EligibilityBadge status={status} />}

      {/* Freshness: verified live / re-used / stored, with sources and timestamps */}
      <FreshnessPanel freshness={scheme.freshness} />

      {/* Conditions that still need official verification (docs/RECOMMENDATIONS.md) */}
      {status === "ELIGIBLE" && (scheme.conditions_to_verify?.length ?? 0) > 0 && (
        <p className="text-[11px] text-slate-600" data-testid="conditions-to-verify">
          <span className="font-semibold">Still confirm with the department: </span>{scheme.conditions_to_verify!.join(" · ")}
        </p>
      )}

      {/* Benefit */}
      {scheme.benefit && (
        <p className="text-xs text-slate-600 bg-white p-2 rounded-lg border border-slate-100">
          <span className="font-semibold text-slate-700">Benefit: </span>{scheme.benefit}
        </p>
      )}

      {/* XAI sections — evidence-based (§193) */}
      {status === "ELIGIBLE" && (
        <>
          <MatchedSection criteria={scheme.matched_criteria} />
          {scheme.xai_explanation && !scheme.matched_criteria?.length && (
            <div className="bg-emerald-100/50 p-2.5 rounded-lg border border-emerald-200/60">
              <span className="text-[11px] font-bold text-emerald-800 uppercase tracking-wider block mb-0.5 flex items-center">
                <Sparkles className="h-3 w-3 mr-1 text-emerald-700" /> Why you are eligible (XAI)
              </span>
              <p className="text-xs text-emerald-950 leading-relaxed font-medium">
                {scheme.xai_explanation}
              </p>
            </div>
          )}
        </>
      )}

      {status === "NOT_ELIGIBLE" && (
        <FailedSection criteria={scheme.failed_criteria} />
      )}

      {status === "NEEDS_MORE_INFORMATION" && (
        <MissingSection fields={scheme.missing_information} />
      )}

      {/* UNVERIFIABLE — human review indicator (§111) */}
      {status === "UNVERIFIABLE" && (
        <div className="bg-slate-100/50 p-2 rounded-lg border border-slate-200">
          <p className="text-xs text-slate-600 italic">
            Needs additional verification. This case may be reviewed for accuracy.
          </p>
        </div>
      )}

      {/* Fallback for no status (Phase 4 backward compat) */}
      {!status && scheme.xai_explanation && (
        <div className="bg-emerald-100/50 p-2.5 rounded-lg border border-emerald-200/60">
          <span className="text-[11px] font-bold text-emerald-800 uppercase tracking-wider block mb-0.5 flex items-center">
            <Sparkles className="h-3 w-3 mr-1 text-emerald-700" /> Why you are eligible (XAI)
          </span>
          <p className="text-xs text-emerald-950 leading-relaxed font-medium">
            {scheme.xai_explanation}
          </p>
        </div>
      )}

      {/* Expandable details — documents, steps, source (§51–§55) */}
      {expanded && <SchemeDetails scheme={scheme} />}

      {save && scheme.scheme_id && (
        <div>
          <SaveButton scheme={scheme} save={save} />
          {save.error?.schemeId === scheme.scheme_id && (
            <p className="text-xs text-red-700 mt-1" role="alert">{save.error.message}</p>
          )}
        </div>
      )}
    </div>
  );
}

export default function SchemeList({ schemes, save, liveCheck }: SchemeListProps) {
  // Sectioned replies: eligible first; related alternatives below (older replies have no sections)
  const sectioned = schemes.some((s) => s.recommendation_section);
  const eligible = sectioned ? schemes.filter((s) => s.recommendation_section === "ELIGIBLE") : schemes;
  const alternatives = schemes.filter((s) => s.recommendation_section === "ALTERNATIVE");
  const notMatching = schemes.filter((s) => s.recommendation_section === "NOT_MATCHING");
  return (
    <div
      className="bg-white p-4 sm:p-5 rounded-xl shadow-sm border border-slate-200 flex-1 flex flex-col"
      role="region"
      aria-label="Personalized scheme recommendations"
    >
      <h2 className="text-sm font-semibold text-slate-500 uppercase tracking-wider mb-3 flex items-center">
        <CheckCircle2 className="h-4 w-4 mr-2 text-emerald-600" />
        {sectioned ? <>Eligible Schemes ({eligible.length})</> : <>Personalized Schemes ({schemes.length})</>}
      </h2>

      {schemes.length > 0 && (
        <p className="text-[11px] text-slate-500 mb-3 leading-snug">
          Checked against the published criteria in SchemeSetu&apos;s scheme database. A match is not a
          guarantee of approval; the final decision rests with the issuing department.
        </p>
      )}

      {schemes.length > 0 && <LiveCheckSummary report={liveCheck} />}

      {schemes.length > 0 ? (
        <div className="space-y-4 overflow-y-auto flex-1 pr-1">
          {sectioned && eligible.length === 0 && (
            <p className="text-xs text-slate-600 border border-dashed border-slate-200 rounded-xl p-3" data-testid="eligible-empty">
              No scheme is confirmed as matching all its published criteria from the details you shared yet.
              Related schemes are listed below — adding missing details (such as land size or age) may confirm more.
            </p>
          )}
          {eligible.map((scheme, idx) => (
            <SchemeCard key={scheme.scheme_id ?? idx} scheme={scheme} idx={idx} save={save} />
          ))}
          {sectioned && <AlternativesSection alternatives={alternatives} notMatching={notMatching} />}
        </div>
      ) : (
        <div className="flex-1 flex flex-col items-center justify-center text-center p-6 border-2 border-dashed border-slate-200 rounded-xl">
          <AlertCircle className="h-8 w-8 text-slate-300 mb-2" />
          <p className="text-xs text-slate-500 max-w-[200px]">
            Provide your critical details (State, Land, Crop) to generate explainable recommendations.
          </p>
        </div>
      )}
    </div>
  );
}
