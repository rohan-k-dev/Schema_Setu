"use client";

/**
 * Saved schemes with an application checklist each (docs/SAVED_SCHEMES.md):
 * documents, preparation, the official application steps, submission,
 * acknowledgement and the farmer's own milestones. Items can be ticked / unticked
 * and given a note; an application reference can be recorded if the farmer wants.
 *
 * Progress is USER-REPORTED: no government tracking system is connected, and the
 * page says so wherever progress is shown.
 */

import React, { useCallback, useEffect, useState } from "react";
import {
  apiAddMilestone,
  apiDeleteMilestone,
  apiDeleteSavedScheme,
  apiGetSavedScheme,
  apiGetSavedSchemes,
  apiUpdateChecklistItem,
  apiUpdateSavedScheme,
  ApiError,
} from "@/lib/api";
import type {
  ChecklistCategory,
  ChecklistItem,
  EligibilityStatusValue,
  SavedSchemeDetail,
  SavedSchemeSummary,
  SavedStatusChange,
} from "@/lib/types";
import { STATUS_LABEL } from "./EligibilityPanel";

const CATEGORY_ORDER: ChecklistCategory[] = [
  "DOCUMENT", "PREPARATION", "APPLICATION", "SUBMISSION", "ACKNOWLEDGEMENT", "MILESTONE",
];

const CATEGORY_LABEL: Record<ChecklistCategory, string> = {
  DOCUMENT: "Documents",
  PREPARATION: "Preparation",
  APPLICATION: "How to apply (official steps)",
  SUBMISSION: "Submission",
  ACKNOWLEDGEMENT: "Acknowledgement",
  MILESTONE: "Your own milestones",
};

const STAGE_LABEL = {
  NOT_STARTED: "Not started",
  PREPARING: "Preparing",
  SUBMITTED: "Submitted",
  ACKNOWLEDGED: "Acknowledgement received",
} as const;

const USER_REPORTED = "Your own record — not confirmed by any government department.";

type Fail = (err: unknown, fallback: string) => void;

function shortDate(iso: string | null): string {
  return iso ? new Date(iso).toLocaleDateString("en-IN", { day: "numeric", month: "short", year: "numeric" }) : "";
}

// ─── One checklist item ───────────────────────────────────────────────────────

function ItemRow({
  item, schemeId, busy, run,
}: {
  item: ChecklistItem;
  schemeId: string;
  busy: boolean;
  run: (action: () => Promise<SavedSchemeDetail>, fallback: string, done?: string) => Promise<boolean>;
}) {
  const [editing, setEditing] = useState(false);
  const [note, setNote] = useState(item.note ?? "");
  // Shown at once while the change is saved; dropped afterwards (the saved value wins, and a
  // failed save goes back to it).
  const [pending, setPending] = useState<boolean | null>(null);
  const inputId = `chk-${item.id}`;

  const setCompleted = async (completed: boolean) => {
    setPending(completed);
    await run(() => apiUpdateChecklistItem(schemeId, item.id, { completed }), "Could not update the checklist.",
              `${item.label}: marked ${completed ? "done" : "not done"}.`);
    setPending(null);
  };

  const saveNote = async (value: string | null) => {
    if (await run(() => apiUpdateChecklistItem(schemeId, item.id, { note: value }), "Could not save the note.",
                  value ? "Note saved." : "Note removed.")) {
      setEditing(false);
    }
  };

  return (
    <li className={`sv-item ${item.current ? "" : "sv-item--retired"}`}>
      <div className="sv-item-main">
        <input
          id={inputId}
          type="checkbox"
          checked={pending ?? item.completed}
          disabled={busy}
          onChange={(e) => setCompleted(e.target.checked)}
          className="sv-check"
        />
        <label htmlFor={inputId} className="sv-item-label">
          {item.label}
          {item.added_in_update && <span className="sv-new"> New</span>}
          {item.detail && <span className="sv-item-detail">{item.detail}</span>}
          {item.completed && item.completed_at && (
            <span className="sv-item-detail">You marked this done on {shortDate(item.completed_at)}.</span>
          )}
        </label>
      </div>

      {item.note && !editing && <p className="sv-note">📝 {item.note}</p>}

      {editing ? (
        <div className="sv-note-edit">
          <label htmlFor={`note-${item.id}`} className="sr-only">Note for {item.label}</label>
          <textarea
            id={`note-${item.id}`}
            value={note}
            maxLength={500}
            rows={2}
            onChange={(e) => setNote(e.target.value)}
            className="fix-input sv-textarea"
          />
          <div className="fix-row">
            <button onClick={() => saveNote(note.trim() || null)} disabled={busy} className="dash-primary-btn min-h-[44px]">
              Save note
            </button>
            <button onClick={() => { setEditing(false); setNote(item.note ?? ""); }} disabled={busy}
                    className="dash-edit-btn min-h-[44px]">Cancel</button>
          </div>
        </div>
      ) : (
        <div className="sv-item-actions">
          <button onClick={() => setEditing(true)} disabled={busy} className="sv-link min-h-[44px]">
            {item.note ? "Edit note" : "Add note"}<span className="sr-only"> for {item.label}</span>
          </button>
          {item.note && (
            <button onClick={() => saveNote(null)} disabled={busy} className="sv-link min-h-[44px]">
              Remove note<span className="sr-only"> for {item.label}</span>
            </button>
          )}
          {item.source === "USER" && (
            <button
              onClick={() => run(() => apiDeleteMilestone(schemeId, item.id), "Could not delete the milestone.",
                                 `Deleted “${item.label}”.`)}
              disabled={busy}
              className="sv-link sv-link--danger min-h-[44px]"
            >
              Delete<span className="sr-only"> milestone {item.label}</span>
            </button>
          )}
        </div>
      )}
    </li>
  );
}

// ─── The checklist of one saved scheme ────────────────────────────────────────

function Checklist({
  detail, busy, run,
}: {
  detail: SavedSchemeDetail;
  busy: boolean;
  run: (action: () => Promise<SavedSchemeDetail>, fallback: string, done?: string) => Promise<boolean>;
}) {
  const [reference, setReference] = useState(detail.application_reference ?? "");
  const [notes, setNotes] = useState(detail.notes ?? "");
  const [milestone, setMilestone] = useState("");
  const sid = detail.scheme_id;
  const current = detail.checklist.filter((i) => i.current);
  const retired = detail.checklist.filter((i) => !i.current);
  const n = detail.update_notice;

  return (
    <div className="sv-checklist" id={`checklist-${sid}`}>
      <p className="sv-reported" role="note">ℹ️ {detail.progress_notice}</p>

      {n && (
        <div className="elig-stale" role="status">
          <div>
            <strong>This scheme&apos;s information was updated{n.changed_at ? ` on ${shortDate(n.changed_at)}` : ""}.</strong>
            {n.added.length > 0 && <> New: {n.added.join(", ")}.</>}
            {n.removed.length > 0 && <> No longer listed: {n.removed.join(", ")}.</>}
            {" "}What you already ticked is kept.
          </div>
          <button
            onClick={() => run(() => apiUpdateSavedScheme(sid, { acknowledge_scheme_update: true }),
                               "Could not save.", "Update notice dismissed.")}
            disabled={busy}
            className="dash-primary-btn min-h-[44px]"
          >
            OK, got it
          </button>
        </div>
      )}
      {!detail.scheme_available && (
        <p className="elig-note">This scheme is no longer in SchemeSetu&apos;s database. Your checklist is kept as it was.</p>
      )}

      {CATEGORY_ORDER.map((cat) => {
        const items = current.filter((i) => i.category === cat);
        if (items.length === 0 && cat !== "MILESTONE") return null;
        return (
          <section key={cat} className="sv-group" aria-labelledby={`grp-${sid}-${cat}`}>
            <h4 id={`grp-${sid}-${cat}`} className="fix-heading">{CATEGORY_LABEL[cat]}</h4>
            {items.length > 0 ? (
              <ul className="sv-items">
                {items.map((i) => <ItemRow key={i.id} item={i} schemeId={sid} busy={busy} run={run} />)}
              </ul>
            ) : (
              <p className="fix-why">Add later steps you want to keep track of, e.g. &ldquo;Field verification visit done&rdquo;.</p>
            )}
            {cat === "MILESTONE" && (
              <form
                className="fix-row"
                onSubmit={async (e) => {
                  e.preventDefault();
                  if (milestone.trim() && await run(() => apiAddMilestone(sid, { label: milestone.trim() }),
                                                    "Could not add the milestone.", "Milestone added.")) {
                    setMilestone("");
                  }
                }}
              >
                <label htmlFor={`ms-${sid}`} className="sr-only">New milestone</label>
                <input id={`ms-${sid}`} value={milestone} maxLength={120} onChange={(e) => setMilestone(e.target.value)}
                       placeholder="e.g. First instalment received" className="fix-input" />
                <button type="submit" disabled={busy || !milestone.trim()} className="dash-edit-btn min-h-[44px]">
                  Add milestone
                </button>
              </form>
            )}
          </section>
        );
      })}

      {retired.length > 0 && (
        <section className="sv-group" aria-labelledby={`grp-${sid}-retired`}>
          <h4 id={`grp-${sid}-retired`} className="fix-heading">No longer listed by the scheme</h4>
          <p className="fix-why">Kept so your record isn&apos;t lost; not counted in your progress.</p>
          <ul className="sv-items">
            {retired.map((i) => <ItemRow key={i.id} item={i} schemeId={sid} busy={busy} run={run} />)}
          </ul>
        </section>
      )}

      <section className="sv-group" aria-labelledby={`ref-${sid}-h`}>
        <h4 id={`ref-${sid}-h`} className="fix-heading">Application reference (optional)</h4>
        <p className="fix-why">
          Only if you want to keep it here, e.g. the number on your receipt or SMS. SchemeSetu does not check it
          with the department.
        </p>
        <form
          className="fix-row"
          onSubmit={(e) => {
            e.preventDefault();
            run(() => apiUpdateSavedScheme(sid, { application_reference: reference.trim() || null }),
                "Could not save the reference.", reference.trim() ? "Reference saved." : "Reference removed.");
          }}
        >
          <label htmlFor={`ref-${sid}`} className="sr-only">Application reference</label>
          <input id={`ref-${sid}`} value={reference} maxLength={64} onChange={(e) => setReference(e.target.value)}
                 placeholder="Not recorded" className="fix-input" autoComplete="off" />
          <button type="submit" disabled={busy || reference.trim() === (detail.application_reference ?? "")}
                  className="dash-edit-btn min-h-[44px]">
            Save reference
          </button>
        </form>
      </section>

      <section className="sv-group" aria-labelledby={`notes-${sid}-h`}>
        <h4 id={`notes-${sid}-h`} className="fix-heading">Your notes</h4>
        <form
          onSubmit={(e) => {
            e.preventDefault();
            run(() => apiUpdateSavedScheme(sid, { notes: notes.trim() || null }), "Could not save the notes.",
                "Notes saved.");
          }}
        >
          <label htmlFor={`notes-${sid}`} className="sr-only">Notes for {detail.scheme_name}</label>
          <textarea id={`notes-${sid}`} value={notes} maxLength={1000} rows={2} onChange={(e) => setNotes(e.target.value)}
                    className="fix-input sv-textarea" />
          <button type="submit" disabled={busy || notes.trim() === (detail.notes ?? "")}
                  className="dash-edit-btn min-h-[44px] sv-notes-btn">
            Save notes
          </button>
        </form>
      </section>
    </div>
  );
}

// ─── Panel ────────────────────────────────────────────────────────────────────

export default function SavedSchemesPanel({
  changes,
  refreshKey,
  onCountChange,
  onChanged,
  onUnauthorized,
}: {
  changes: SavedStatusChange[];
  refreshKey: number;                     // bump after a scheme is saved elsewhere on the page
  onCountChange: (n: number) => void;
  onChanged: () => void;                  // a scheme was removed (eligibility list shows "saved")
  onUnauthorized: () => void;
}) {
  const [list, setList] = useState<SavedSchemeSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [open, setOpen] = useState<string | null>(null);
  const [detail, setDetail] = useState<SavedSchemeDetail | null>(null);
  const [confirmRemove, setConfirmRemove] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const changed = new Map(changes.map((c) => [c.scheme_id, c.current_status]));

  const fail: Fail = useCallback((err, fallback) => {
    if (err instanceof ApiError && err.status === 401) onUnauthorized();
    else setError(err instanceof Error ? err.message : fallback);
  }, [onUnauthorized]);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      setList(await apiGetSavedSchemes());
    } catch (err) {
      fail(err, "Failed to load saved schemes.");
    } finally {
      setLoading(false);
    }
  }, [fail]);

  useEffect(() => { load(); }, [load, refreshKey]);
  useEffect(() => { onCountChange(list.length); }, [list.length, onCountChange]);

  const applyDetail = (d: SavedSchemeDetail) => {
    setDetail(d);
    setList((prev) => prev.map((s) => (s.scheme_id === d.scheme_id ? { ...s, ...d } : s)));
  };

  const run = async (action: () => Promise<SavedSchemeDetail>, fallback: string, done?: string) => {
    setBusy(true);
    setError(null);
    try {
      applyDetail(await action());
      if (done) setNotice(done);
      return true;
    } catch (err) {
      if (err instanceof ApiError && err.status === 404) load();      // removed elsewhere
      fail(err, fallback);
      return false;
    } finally {
      setBusy(false);
    }
  };

  const toggle = async (sid: string) => {
    if (open === sid) {
      setOpen(null);
      return;
    }
    setOpen(sid);
    setDetail(null);
    await run(() => apiGetSavedScheme(sid), "Failed to load the checklist.");
  };

  const remove = async (s: SavedSchemeSummary) => {
    setBusy(true);
    setError(null);
    try {
      await apiDeleteSavedScheme(s.scheme_id);
      setList((prev) => prev.filter((x) => x.scheme_id !== s.scheme_id));
      if (open === s.scheme_id) setOpen(null);
      setNotice(`Removed “${s.scheme_name}” and its checklist.`);
      onChanged();
    } catch (err) {
      fail(err, "Failed to remove scheme.");
    } finally {
      setBusy(false);
      setConfirmRemove(null);
    }
  };

  return (
    <section className="dash-card dash-card--wide" id="saved-schemes" aria-labelledby="saved-title">
      <div className="dash-card-header">
        <h2 id="saved-title" className="dash-card-title">🔖 Saved Schemes &amp; Applications</h2>
        <span className="dash-card-count" aria-label={`${list.length} saved`}>{list.length}</span>
      </div>
      <p className="elig-sub">
        A checklist for each saved scheme. Progress is what you record yourself — SchemeSetu is not connected
        to government application tracking.
      </p>

      <p className="sr-only" aria-live="polite">{notice}</p>
      {error && (
        <div className="dash-error" role="alert">
          ⚠️ {error}
          <button onClick={() => { setError(null); load(); }} className="dash-retry min-h-[44px]">Retry</button>
        </div>
      )}

      {loading && list.length === 0 ? (
        <p className="dash-empty" role="status">Loading saved schemes…</p>
      ) : list.length === 0 && !error ? (
        <p className="dash-empty">
          No saved schemes yet. Press <strong>Save</strong> on a scheme in your eligibility list above or in the AI
          chat to get a checklist for applying.
        </p>
      ) : (
        <ul className="sv-list" aria-busy={loading}>
          {list.map((s) => {
            const pct = s.progress.total ? Math.round((s.progress.completed / s.progress.total) * 100) : 0;
            const isOpen = open === s.scheme_id;
            const now = changed.get(s.scheme_id);
            return (
              <li key={s.scheme_id} className="sv-scheme">
                <div className="sv-scheme-head">
                  <div className="dash-scheme-info">
                    <span className="sv-scheme-name">{s.scheme_name}</span>
                    {s.eligibility_status && (
                      <span className="dash-scheme-status">
                        When saved: {STATUS_LABEL[s.eligibility_status as EligibilityStatusValue] ?? s.eligibility_status}
                      </span>
                    )}
                    {now && <span className="elig-changed">Now: {STATUS_LABEL[now]} (changed since you saved it)</span>}
                    {s.update_notice && <span className="elig-changed">Scheme information updated — please check the checklist.</span>}
                    {!s.scheme_available && <span className="elig-changed">No longer in SchemeSetu&apos;s database.</span>}
                  </div>
                  <span className={`sv-stage sv-stage--${s.progress.stage}`}>{STAGE_LABEL[s.progress.stage]}</span>
                </div>

                <div className="sv-progress">
                  <div className="dash-progress-bar-bg" role="progressbar" aria-valuemin={0} aria-valuemax={s.progress.total}
                       aria-valuenow={s.progress.completed}
                       aria-label={`${s.scheme_name}: ${s.progress.completed} of ${s.progress.total} steps done, as recorded by you`}>
                    <div className="dash-progress-bar-fill" style={{ width: `${pct}%`, background: "#059669" }} />
                  </div>
                  <span className="dash-progress-caption">
                    {s.progress.completed} of {s.progress.total} done · {USER_REPORTED}
                    {s.application_reference && <> · Ref: {s.application_reference}</>}
                  </span>
                </div>

                {confirmRemove === s.scheme_id ? (
                  <div className="hist-confirm" role="alertdialog" aria-labelledby={`rm-${s.scheme_id}`}>
                    <p id={`rm-${s.scheme_id}`}>Remove “{s.scheme_name}” and its checklist? Your ticks and notes will be deleted.</p>
                    <div className="hist-confirm-actions">
                      <button onClick={() => remove(s)} disabled={busy} className="hist-danger min-h-[44px]" autoFocus>
                        {busy ? "Removing…" : "Yes, remove"}
                      </button>
                      <button onClick={() => setConfirmRemove(null)} disabled={busy} className="dash-edit-btn min-h-[44px]">
                        Cancel
                      </button>
                    </div>
                  </div>
                ) : (
                  <div className="sv-scheme-actions">
                    <button onClick={() => toggle(s.scheme_id)} aria-expanded={isOpen} aria-controls={`checklist-${s.scheme_id}`}
                            className="dash-primary-btn min-h-[44px]">
                      {isOpen ? "Hide checklist" : "Open checklist"}
                    </button>
                    {s.official_url && (
                      <a href={s.official_url} target="_blank" rel="noopener noreferrer" className="elig-link">
                        Official website<span className="sr-only"> for {s.scheme_name} (opens in a new tab)</span>
                      </a>
                    )}
                    <button onClick={() => setConfirmRemove(s.scheme_id)} disabled={busy} className="sv-link sv-link--danger min-h-[44px]">
                      Remove<span className="sr-only"> {s.scheme_name}</span>
                    </button>
                  </div>
                )}

                {isOpen && (detail && detail.scheme_id === s.scheme_id
                  ? <Checklist key={`${detail.scheme_id}-${detail.scheme_version}`} detail={detail} busy={busy} run={run} />
                  : <p className="dash-empty" role="status">Loading checklist…</p>)}
              </li>
            );
          })}
        </ul>
      )}
    </section>
  );
}
