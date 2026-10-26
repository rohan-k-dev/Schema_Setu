"use client";

/**
 * How fresh each scheme's details are, and what the query-time check of official websites
 * actually did (docs/LIVE_VERIFICATION.md). Every label comes from the server; nothing here
 * upgrades a stored or re-used result to "live". Text + icon, never colour only.
 */

import React, { useState } from "react";
import type { FreshnessStatus, LiveCheckReport, LiveSource, SchemeFreshness } from "@/lib/types";
import { AlertTriangle, CheckCircle2, Clock, Database, ExternalLink, Globe, XCircle } from "lucide-react";

const FIELD_LABELS: Record<string, string> = {
  name: "Name", description: "Description", eligibility: "Eligibility", exclusions: "Who is excluded",
  benefits: "Benefits", benefit_amounts: "Amounts", income_requirement: "Income rule", land_requirement: "Land rule",
  documents: "Documents", application_process: "How to apply", application_url: "Application link",
  important_dates: "Dates", application_status: "Open / closed", ministry: "Ministry",
};

const BADGE: Record<FreshnessStatus, { text: string; cls: string; icon: React.ReactNode }> = {
  LIVE_VERIFIED: { text: "Verified live", cls: "bg-emerald-50 text-emerald-800 border-emerald-200",
    icon: <CheckCircle2 className="h-3.5 w-3.5 text-emerald-600" /> },
  CACHED: { text: "Checked earlier (not re-checked now)", cls: "bg-sky-50 text-sky-800 border-sky-200",
    icon: <Clock className="h-3.5 w-3.5 text-sky-600" /> },
  SOURCE_REACHABLE: { text: "Stored details — page reached, not readable", cls: "bg-amber-50 text-amber-800 border-amber-200",
    icon: <AlertTriangle className="h-3.5 w-3.5 text-amber-600" /> },
  NOT_VERIFIED: { text: "Stored details — couldn't check now", cls: "bg-amber-50 text-amber-800 border-amber-200",
    icon: <XCircle className="h-3.5 w-3.5 text-amber-600" /> },
  STORED: { text: "Stored details — not checked live", cls: "bg-slate-50 text-slate-700 border-slate-200",
    icon: <Database className="h-3.5 w-3.5 text-slate-500" /> },
};

/** Local date and time, or the raw value when it can't be parsed. */
export function when(iso?: string | null): string {
  if (!iso) return "";
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });
}

function show(v: unknown): string {
  if (v == null) return "—";
  if (Array.isArray(v)) return v.map((x) => (typeof x === "object" && x ? show((x as { amount?: unknown }).amount) : String(x))).join(", ");
  return String(v);
}

function SourceLine({ s }: { s: LiveSource }) {
  const how = s.method === "tavily" ? "text from the search service" : s.from_cache ? "re-used earlier read" : "read directly";
  return (
    <li className="text-[11px] text-slate-600">
      <a href={s.url} target="_blank" rel="noopener noreferrer"
         className="inline-flex items-center gap-1 text-blue-700 hover:underline break-all focus:outline-none focus-visible:ring-2 focus-visible:ring-blue-500 rounded">
        <ExternalLink className="h-3 w-3 shrink-0" />{s.host}<span className="sr-only"> (opens in a new tab)</span>
      </a>
      {" — "}
      {s.retrieved_at ? <>retrieved {when(s.retrieved_at)} ({how})</> : <>not read{s.reason ? `: ${s.reason}` : ""}</>}
    </li>
  );
}

export function FreshnessPanel({ freshness }: { freshness?: SchemeFreshness | null }) {
  const [open, setOpen] = useState(false);
  if (!freshness) return null;
  const b = BADGE[freshness.status] ?? BADGE.STORED;
  const hasMore = freshness.sources.length > 0 || freshness.verified_fields.length > 0;
  return (
    <div className="space-y-1" data-testid="freshness">
      <div className="flex flex-wrap items-center gap-1.5">
        <span className={`inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-[11px] font-semibold ${b.cls}`}
              data-status={freshness.status}>
          {b.icon}{freshness.new_discovery ? "New — found live" : b.text}
        </span>
        {hasMore && (
          <button onClick={() => setOpen(!open)} aria-expanded={open}
                  className="text-[11px] text-slate-600 underline min-h-[32px] px-1 focus:outline-none focus-visible:ring-2 focus-visible:ring-emerald-600 rounded">
            {open ? "Hide sources" : "Sources and checks"}
          </button>
        )}
      </div>
      <p className="text-[11px] text-slate-600 leading-snug">{freshness.label}</p>

      {freshness.conflicts.length > 0 && (
        <div className="rounded-lg border border-red-200 bg-red-50 p-2" role="note">
          <p className="text-[11px] font-semibold text-red-800 flex items-center gap-1">
            <AlertTriangle className="h-3 w-3" /> The official page differs from our stored record
          </p>
          <ul className="mt-1 space-y-0.5">
            {freshness.conflicts.map((c, i) => (
              <li key={i} className="text-[11px] text-red-900">
                {FIELD_LABELS[c.field] ?? c.field}: official page says <strong>{show(c.live)}</strong>, stored record
                says <strong>{show(c.stored)}</strong>.
              </li>
            ))}
          </ul>
          <p className="text-[11px] text-red-800 mt-1">Please confirm on the official website before applying.</p>
        </div>
      )}

      {open && (
        <div className="rounded-lg border border-slate-200 bg-white p-2 space-y-1">
          {freshness.verified_fields.length > 0 && (
            <p className="text-[11px] text-slate-700">
              <span className="font-semibold">Found on the official page now: </span>
              {freshness.verified_fields.map((f) => {
                const st = freshness.fields[f]?.status;
                return `${FIELD_LABELS[f] ?? f}${st === "CONFIRMED" ? " (matches our record)" : ""}`;
              }).join(", ")}
            </p>
          )}
          {freshness.sources.length > 0 && <ul className="space-y-0.5">{freshness.sources.map((s, i) => <SourceLine key={i} s={s} />)}</ul>}
          <p className="text-[11px] text-slate-500">Eligibility is still decided by SchemeSetu&apos;s stored rules.</p>
        </div>
      )}
    </div>
  );
}

export function LiveCheckSummary({ report }: { report?: LiveCheckReport | null }) {
  const [open, setOpen] = useState(false);
  if (!report?.performed) return null;
  const failed = report.sources.filter((s) => !["OK", "NOT_MODIFIED", "TAVILY_CONTENT", "CACHED", "NOT_CHECKED"].includes(s.status));
  return (
    <div className="mb-3 rounded-lg border border-slate-200 bg-slate-50 p-2.5 space-y-1" role="status" data-testid="live-check">
      <p className="text-[11px] font-semibold text-slate-700 flex items-center gap-1">
        <Globe className="h-3.5 w-3.5 text-slate-500" />
        Official websites checked for this question: {report.sources_accessed} read
        {report.sources_cached > 0 && <>, {report.sources_cached} re-used</>}
        {report.sources_failed > 0 && <>, {report.sources_failed} not readable</>}
        {report.finished_at && <> · {when(report.finished_at)}</>}
      </p>
      {report.coverage_note && <p className="text-[11px] text-slate-600">{report.coverage_note}</p>}
      {report.warnings.map((w, i) => (
        <p key={i} className="text-[11px] text-amber-800 flex items-start gap-1">
          <AlertTriangle className="h-3 w-3 mt-0.5 shrink-0" />{w}
        </p>
      ))}
      {report.new_discoveries.length > 0 && (
        <p className="text-[11px] text-slate-700">
          Also found on official sites (not in our records, not checked against rules):{" "}
          {report.new_discoveries.map((n, i) => (
            <React.Fragment key={n.url}>
              {i > 0 && ", "}
              <a href={n.url} target="_blank" rel="noopener noreferrer" className="text-blue-700 hover:underline">{n.name}</a>
            </React.Fragment>
          ))}
        </p>
      )}
      {failed.length > 0 && (
        <>
          <button onClick={() => setOpen(!open)} aria-expanded={open}
                  className="text-[11px] text-slate-600 underline min-h-[32px] focus:outline-none focus-visible:ring-2 focus-visible:ring-emerald-600 rounded">
            {open ? "Hide sources that couldn't be read" : "Which sources couldn't be read?"}
          </button>
          {open && <ul className="space-y-0.5">{failed.map((s, i) => <SourceLine key={i} s={s} />)}</ul>}
        </>
      )}
    </div>
  );
}
