"use client";

/**
 * System health, scheme corpus, ingestion, graph sync, pending reviews and recent
 * errors — one card each. A card whose source is down says so instead of showing
 * an all-clear (the backend computes each section independently).
 */

import React from "react";
import type { AdminOverview, Section } from "@/lib/types";

function when(iso?: string | null): string {
  return iso ? new Date(iso).toLocaleString("en-IN", { dateStyle: "medium", timeStyle: "short" }) : "—";
}

export function Badge({ ok, label }: { ok: boolean | null; label: string }) {
  const cls = ok === null ? "adm-badge adm-badge--muted" : ok ? "adm-badge adm-badge--ok" : "adm-badge adm-badge--bad";
  return <span className={cls}>{ok === null ? "○" : ok ? "✓" : "!"} {label}</span>;
}

function Card<T>({ title, section, children }: {
  title: string; section: Section<T>; children: (s: { status: "OK" } & T) => React.ReactNode;
}) {
  return (
    <section className="adm-card" aria-label={title}>
      <h2 className="adm-card-title">{title}</h2>
      {section.status === "OK" ? children(section as { status: "OK" } & T) : (
        <p className="adm-unavailable" role="status">⚠️ Unavailable: {section.message}</p>
      )}
    </section>
  );
}

function Row({ k, v }: { k: string; v: React.ReactNode }) {
  return <><dt>{k}</dt><dd>{v}</dd></>;
}

export default function OverviewPanel({ data }: { data: AdminOverview }) {
  return (
    <div className="adm-grid">
      <Card title="🩺 System health" section={data.system}>{(s) => (
        <>
          <dl className="adm-dl">
            <Row k="Version" v={`${s.version} (${s.environment})`} />
            <Row k="Uptime" v={`${Math.floor(s.uptime_seconds / 3600)} h ${Math.floor((s.uptime_seconds % 3600) / 60)} min`} />
            <Row k="Database" v={<Badge ok={s.database.connected} label={s.database.connected ? "connected" : "down"} />} />
            <Row k="Migration" v={<Badge ok={s.database.migration === s.database.expected_migration}
                                         label={`${s.database.migration ?? "none"} / expected ${s.database.expected_migration}`} />} />
            <Row k="Knowledge Graph" v={<Badge ok={s.knowledge_graph_loaded} label={s.knowledge_graph_loaded ? "loaded" : "not loaded"} />} />
            <Row k="Services" v={Object.entries(s.external_services).map(([n, on]) => (
              <Badge key={n} ok={on ? true : null} label={n} />))} />
          </dl>
          {s.warnings.length > 0 && <ul className="adm-warn">{s.warnings.map((w) => <li key={w}>{w}</li>)}</ul>}
        </>
      )}</Card>

      <Card title="📚 Scheme corpus" section={data.corpus}>{(s) => (
        <dl className="adm-dl">
          <Row k="Corpus file" v={`v${s.file.version ?? "?"} · ${s.file.schemes} schemes`} />
          <Row k="Database" v={`v${s.database.corpus_version?.version ?? "none"} · ${s.database.schemes} schemes · ${s.database.rules} rules`} />
          <Row k="By status" v={Object.entries(s.database.by_status).map(([k, n]) => `${k} ${n}`).join(" · ") || "—"} />
          <Row k="Flags" v={`${s.database.needs_review} need review · ${s.database.possible_duplicates} possible duplicates · ${s.database.without_rules} without rules`} />
          <Row k="File ↔ database" v={<Badge ok={s.in_step} label={s.in_step ? "in step" : "differ — run Validate"} />} />
        </dl>
      )}</Card>

      <Card title="⚙️ Ingestion jobs" section={data.ingestion}>{(s) => (
        <>
          <p className="adm-note">{s.active_job ? `Running: ${s.active_job.kind} (${s.active_job.status})` : "No job running."}</p>
          <ul className="adm-list">
            {s.recent_import_runs.slice(0, 3).map((r) => (
              <li key={r.id}>Import #{r.id}: <Badge ok={r.status === "SUCCESS"} label={r.status} /> {when(r.started_at)} · {r.records_read} read</li>
            ))}
            {s.recent_import_runs.length === 0 && <li>No import runs recorded.</li>}
          </ul>
        </>
      )}</Card>

      <Card title="🕸️ Graph synchronisation" section={data.graph}>{(s) => (
        s.loaded ? (
          <dl className="adm-dl">
            <Row k="Status" v={<Badge ok={s.in_sync} label={s.in_sync ? "in sync with the database" : "NOT in sync"} />} />
            <Row k="Graph" v={`${s.nodes} nodes · ${s.edges} edges · corpus v${s.graph_corpus_version}`} />
            <Row k="Database corpus" v={`v${s.db_corpus_version ?? "none"}`} />
            <Row k="Built" v={when(s.generated_at)} />
            {(s.schemes_missing_from_graph?.length ?? 0) > 0 &&
              <Row k="Missing from graph" v={s.schemes_missing_from_graph!.join(", ")} />}
            {(s.schemes_only_in_graph?.length ?? 0) > 0 &&
              <Row k="Only in graph" v={s.schemes_only_in_graph!.join(", ")} />}
          </dl>
        ) : <p className="adm-unavailable">⚠️ {s.message}</p>
      )}</Card>

      <Card title="🧑‍⚖️ Pending reviews" section={data.reviews}>{(s) => (
        <dl className="adm-dl">
          <Row k="Open" v={`${(s.stats.pending ?? 0) + (s.stats.in_review ?? 0)} (${s.stats.pending ?? 0} pending, ${s.stats.in_review ?? 0} in review)`} />
          <Row k="By reason" v={Object.entries(s.open_by_reason).map(([k, n]) => `${k} ${n}`).join(" · ") || "—"} />
          <Row k="Oldest open" v={when(s.oldest_open_created_at)} />
          <Row k="With source conflicts" v={s.with_source_conflicts} />
        </dl>
      )}</Card>

      <Card title="🚨 Recent errors" section={data.errors}>{(s) => (
        <>
          <p className="adm-note">{s.last_24h} in the last 24 h · {s.note}</p>
          <ul className="adm-list">
            {s.latest.map((e) => <li key={e.id}><code>{when(e.at)}</code> {e.message}</li>)}
            {s.latest.length === 0 && <li>No errors recorded.</li>}
          </ul>
        </>
      )}</Card>
    </div>
  );
}
