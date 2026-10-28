"use client";

/**
 * One review case (docs/HUMAN_REVIEW.md): the scheme, why it was escalated, the evidence and
 * source URLs, conflicting values, the minimal profile, the automated result (read-only),
 * assignment, comments, history, and the workflow actions. Every action is re-checked on the
 * server; a stale view (someone else acted first) gets 409 and the case is reloaded. Sensitive
 * actions ask for the password when the server requires a recent sign-in (useReauth).
 * Access (docs/HUMAN_REVIEW.md): assigned reviewers act; granted reviewers read and comment;
 * administrators read, assign and grant.
 */

import React, { useCallback, useEffect, useState } from "react";
import {
  apiReviewAssign, apiReviewCase, apiReviewClaim, apiReviewComment, apiReviewDecide, apiReviewDismiss,
  apiReviewGrant, apiReviewRelease, apiReviewRequestVerification, apiReviewRevokeGrant, ApiError,
} from "@/lib/api";
import type { ReviewAccess, ReviewCaseView, ReviewDecisionAction, ReviewEvent, ReviewGrant } from "@/lib/types";
import { useReauth } from "@/components/ReauthDialog";

export const REASON_LABEL: Record<string, string> = {
  UNVERIFIABLE: "Eligibility couldn't be verified automatically",
  RULE_CONFLICT: "The scheme's rules contradict each other",
  SOURCE_CONFLICT: "Sources disagree (database vs web)",
  SYSTEM_ERROR: "Retrieval channels failed",
  INSUFFICIENT_DATA: "Not enough data",
  AMBIGUOUS_QUERY: "Ambiguous question",
  OTHER: "Other",
};
export const STATUS_LABEL: Record<string, string> = {
  PENDING: "Pending", IN_REVIEW: "In review", RESOLVED: "Resolved", DISMISSED: "Dismissed",
};
const EVENT_LABEL: Record<string, string> = {
  CREATED: "Case opened", ASSIGNED: "Assigned", UNASSIGNED: "Released to the queue", COMMENT: "Comment",
  VERIFICATION_REQUESTED: "Additional verification requested", APPROVE: "Approved", REJECT: "Rejected",
  MARK_UNVERIFIABLE: "Marked unverifiable", RESOLVE: "Resolved", DISMISSED: "Dismissed",
  REQUEST_INFORMATION: "Additional verification requested",
};
const DECISIONS: { value: ReviewDecisionAction | "DISMISS"; label: string; help: string }[] = [
  { value: "APPROVE", label: "Approve", help: "The automated result is correct (checked against the official source)." },
  { value: "REJECT", label: "Reject", help: "The automated result or the scheme data is wrong." },
  { value: "MARK_UNVERIFIABLE", label: "Mark unverifiable", help: "It can't be confirmed from official sources." },
  { value: "RESOLVE", label: "Resolve", help: "Handled without a verdict on the result (e.g. a temporary outage)." },
  { value: "DISMISS", label: "Dismiss", help: "No action needed (duplicate or false alarm)." },
];

export const fmt = (iso: string | null) =>
  iso ? new Date(iso).toLocaleString("en-IN", { dateStyle: "medium", timeStyle: "short" }) : "—";

function show(v: unknown): string {
  if (v === null || v === undefined || v === "") return "—";
  if (Array.isArray(v)) return v.map(show).join(", ");
  if (typeof v === "object") return JSON.stringify(v);
  return String(v);
}

export default function CaseDetail({
  caseId, me, canDecide, canAssign, onChanged, fail,
}: {
  caseId: string;
  me: string;
  canDecide: boolean;
  canAssign: boolean;
  onChanged: () => void;
  fail: (err: unknown) => void;
}) {
  const [c, setC] = useState<ReviewCaseView | null>(null);
  const [history, setHistory] = useState<ReviewEvent[]>([]);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const [comment, setComment] = useState("");
  const [decision, setDecision] = useState<ReviewDecisionAction | "DISMISS" | "VERIFY">("VERIFY");
  const [note, setNote] = useState("");
  const [correction, setCorrection] = useState(false);
  const [assignee, setAssignee] = useState("");
  const [access, setAccess] = useState<ReviewAccess | null>(null);
  const [grants, setGrants] = useState<ReviewGrant[]>([]);
  const [grantee, setGrantee] = useState("");
  const [grantHours, setGrantHours] = useState(72);
  const reauth = useReauth();

  const load = useCallback(async () => {
    try {
      const d = await apiReviewCase(caseId);
      setC(d.case);
      setHistory(d.history);
      setAccess(d.access);
      setGrants(d.grants ?? []);
    } catch (err) {
      fail(err);
    }
  }, [caseId, fail]);

  useEffect(() => { setC(null); setMsg(null); setNote(""); setComment(""); load(); }, [load]);

  const run = async (fn: () => Promise<unknown>, done: string) => {
    setBusy(true);
    setMsg(null);
    try {
      await reauth.guard(fn);
      setMsg({ ok: true, text: done });
      setNote("");
      setComment("");
      setCorrection(false);
      onChanged();
    } catch (err) {
      if (err instanceof ApiError && err.code === "REAUTH_CANCELLED") setMsg({ ok: false, text: "Not saved: your password wasn't confirmed." });
      else if (err instanceof ApiError && err.status === 409) setMsg({ ok: false, text: `${err.message} The case has been reloaded.` });
      else if (err instanceof ApiError && err.status === 404) setMsg({ ok: false, text: "This case is no longer available to you." });
      else if (err instanceof ApiError && err.status === 422) setMsg({ ok: false, text: err.message });
      else fail(err);
    } finally {
      setBusy(false);
      load();
    }
  };

  if (!c) return <section className="rv-card" aria-busy="true"><p role="status">Loading case…</p></section>;

  const open = c.status === "PENDING" || c.status === "IN_REVIEW";
  const mine = c.assignee === me;
  const canAct = canDecide && open && (!c.assignee || mine) && access !== "granted";
  const canComment = canDecide && (mine || access === "granted");

  return (
    <section className="rv-card" aria-labelledby="case-title">
      <div className="rv-row rv-between">
        <h2 id="case-title" className="rv-h2">Case {c.case_id}</h2>
        <span className={`rv-badge rv-badge--${c.status}`}>{STATUS_LABEL[c.status]}</span>
      </div>
      <dl className="rv-dl">
        <dt>Reason</dt><dd>{REASON_LABEL[c.reason] ?? c.reason}</dd>
        <dt>Opened</dt><dd>{fmt(c.created_at)}</dd>
        <dt>Last change</dt><dd>{fmt(c.updated_at)}</dd>
        <dt>Assigned to</dt><dd>{c.assignee ? `${c.assignee}${mine ? " (you)" : ""} · ${fmt(c.assigned_at)}` : "Nobody yet"}</dd>
        {c.awaiting_verification && <><dt>Note</dt><dd><span className="rv-badge rv-badge--PENDING">Awaiting additional verification</span></dd></>}
        {c.decision && <><dt>Decision</dt><dd>{DECISIONS.find((d) => d.value === c.decision)?.label} by {c.reviewer_id} · {fmt(c.reviewed_at)}{c.data_correction_needed && " · scheme data correction needed"}</dd></>}
        <dt>Farmer</dt><dd>{c.farmer_follows_case ? "A signed-in farmer will see the outcome on their dashboard." : "Anonymous search (shown only in that chat)."}</dd>
      </dl>

      {access === "granted" && (
        <p className="rv-info" role="note">You have temporary read access to this case. You can comment, but only the
          assigned reviewer can act on it.</p>
      )}
      {msg && <p className={msg.ok ? "rv-ok" : "rv-warn"} role={msg.ok ? "status" : "alert"}>{msg.text}</p>}

      <h3 className="rv-h3">Scheme{c.schemes.length !== 1 && "s"}</h3>
      {c.schemes.length === 0 ? <p className="rv-muted">No specific scheme (retrieval-level issue).</p> : (
        <ul className="rv-list">
          {c.schemes.map((s) => (
            <li key={s.scheme_id}>
              <strong>{s.name}</strong> <code>{s.scheme_id}</code>{" "}
              {s.official_url && <a href={s.official_url} target="_blank" rel="noopener noreferrer">Official website<span className="sr-only"> (opens in a new tab)</span></a>}
            </li>
          ))}
        </ul>
      )}

      <h3 className="rv-h3">Automated result <span className="rv-muted">(read-only — a review decision never changes it)</span></h3>
      {c.eligibility_results.length === 0 ? <p className="rv-muted">None.</p> : (
        <ul className="rv-list">
          {c.eligibility_results.map((r, i) => (
            <li key={i}><code>{r.scheme_id}</code>: {r.status.replace(/_/g, " ").toLowerCase()}
              {r.missing_information && r.missing_information.length > 0 && ` · missing: ${r.missing_information.join(", ")}`}
              {r.summary && <div className="rv-muted">{r.summary}</div>}</li>
          ))}
        </ul>
      )}

      {(c.rule_conflicts.length > 0 || c.source_conflicts.length > 0) && (
        <>
          <h3 className="rv-h3">Conflicting values</h3>
          <table className="rv-table">
            <thead><tr><th scope="col">Scheme</th><th scope="col">Field</th><th scope="col">Values</th></tr></thead>
            <tbody>
              {c.rule_conflicts.map((rc, i) => (
                <tr key={`r${i}`}><td>{show(rc.scheme_id)}</td><td>{show(rc.field)}</td><td>{show(rc.message ?? rc)}</td></tr>
              ))}
              {c.source_conflicts.map((sc, i) => (
                <tr key={`s${i}`}><td>{show(sc.scheme_id)}</td><td>{show(sc.field)}</td>
                  <td>{sc.values ? Object.entries(sc.values).map(([src, v]) => `${src}: ${show(v)}`).join(" · ") : show(sc)}</td></tr>
              ))}
            </tbody>
          </table>
        </>
      )}

      {c.failed_channels.length > 0 && (
        <><h3 className="rv-h3">Failed retrieval channels</h3><p>{c.failed_channels.join(", ")}</p></>
      )}

      <h3 className="rv-h3">Supporting evidence</h3>
      {c.evidence.length === 0 ? <p className="rv-muted">No source text recorded — check the official website.</p> : (
        <ul className="rv-list">
          {c.evidence.map((e, i) => (
            <li key={i}><code>{e.field ?? "—"}</code> {e.text ? `“${e.text}”` : ""}{" "}
              {e.url && <a href={e.url} target="_blank" rel="noopener noreferrer">source<span className="sr-only"> for {e.field} (opens in a new tab)</span></a>}</li>
          ))}
        </ul>
      )}

      <h3 className="rv-h3">Farmer details needed for this check</h3>
      {Object.keys(c.profile_snapshot).length === 0 ? <p className="rv-muted">None.</p> : (
        <dl className="rv-dl">
          {Object.entries(c.profile_snapshot).map(([k, v]) => <React.Fragment key={k}><dt>{k.replace(/_/g, " ")}</dt><dd>{show(v)}</dd></React.Fragment>)}
        </dl>
      )}
      <p className="rv-muted">Only the fields the scheme&apos;s rules use are shown — no name, contact or ID numbers.</p>
      {c.query && <><h3 className="rv-h3">The farmer&apos;s question</h3><p className="rv-quote">{c.query}</p></>}

      {/* ── workflow ── */}
      {canDecide && open && (
        <div className="rv-actions">
          <h3 className="rv-h3">Actions</h3>
          {c.status === "PENDING" && (
            <div className="rv-row">
              <button className="rv-btn" disabled={busy} onClick={() => run(() => apiReviewClaim(c.case_id, c.version), "You took the case.")}>Take this case</button>
              <span className="rv-muted">Taking a case assigns it to you so nobody else acts on it.</span>
            </div>
          )}
          {c.status === "IN_REVIEW" && mine && (
            <div className="rv-row">
              <button className="rv-btn rv-btn--ghost" disabled={busy} onClick={() => run(() => apiReviewRelease(c.case_id, c.version), "Case returned to the queue.")}>Release to the queue</button>
            </div>
          )}
          {!canAct ? (
            <p className="rv-muted">This case is assigned to {c.assignee}. Only they can act on it (an administrator can reassign it).</p>
          ) : (
            <form className="rv-form" onSubmit={(e) => {
              e.preventDefault();
              if (decision === "VERIFY") run(() => apiReviewRequestVerification(c.case_id, c.version, note), "Additional verification requested.");
              else if (decision === "DISMISS") run(() => apiReviewDismiss(c.case_id, c.version, note), "Case dismissed.");
              else run(() => apiReviewDecide(c.case_id, c.version, decision, note, correction), "Decision saved.");
            }}>
              <fieldset className="rv-fieldset">
                <legend className="rv-legend">What did you conclude?</legend>
                <label className="rv-radio"><input type="radio" name="decision" value="VERIFY" checked={decision === "VERIFY"} onChange={() => setDecision("VERIFY")} />
                  <span><strong>Request additional verification</strong> — keep it open while someone checks with the official source.</span></label>
                {DECISIONS.map((d) => (
                  <label key={d.value} className="rv-radio">
                    <input type="radio" name="decision" value={d.value} checked={decision === d.value}
                           disabled={d.value !== "DISMISS" && c.status !== "IN_REVIEW"} onChange={() => setDecision(d.value)} />
                    <span><strong>{d.label}</strong> — {d.help}{d.value !== "DISMISS" && c.status !== "IN_REVIEW" && " (take the case first)"}</span>
                  </label>
                ))}
              </fieldset>
              {decision === "REJECT" && (
                <label className="rv-radio">
                  <input type="checkbox" checked={correction} onChange={(e) => setCorrection(e.target.checked)} />
                  <span>The scheme data needs a correction. Rules are never edited here: an administrator corrects them through
                    the verified Scheme updates process.</span>
                </label>
              )}
              <label htmlFor="rv-note" className="rv-label">Note (what you checked, and where)</label>
              <textarea id="rv-note" className="rv-input" rows={3} maxLength={2000} required minLength={3}
                        value={note} onChange={(e) => setNote(e.target.value)} />
              <button type="submit" className="rv-btn" disabled={busy || note.trim().length < 3}>{busy ? "Saving…" : "Save"}</button>
            </form>
          )}
        </div>
      )}

      {canAssign && open && (
        <form className="rv-row" onSubmit={(e) => { e.preventDefault(); run(() => apiReviewAssign(c.case_id, c.version, assignee), `Assigned to ${assignee}.`); }}>
          <label htmlFor="rv-assign" className="rv-label">Assign to reviewer (e-mail)</label>
          <input id="rv-assign" type="email" className="rv-input rv-input--inline" required value={assignee} onChange={(e) => setAssignee(e.target.value)} />
          <button type="submit" className="rv-btn" disabled={busy}>Assign</button>
        </form>
      )}

      {canAssign && (
        <div className="rv-grants">
          <h3 className="rv-h3">Read access for other reviewers</h3>
          {grants.filter((g) => !g.revoked_at && new Date(g.expires_at) > new Date()).length === 0
            ? <p className="rv-muted">Only the assigned reviewer can see this case.</p>
            : (
              <ul className="rv-list">
                {grants.filter((g) => !g.revoked_at && new Date(g.expires_at) > new Date()).map((g) => (
                  <li key={`${g.reviewer}-${g.granted_at}`}>{g.reviewer} · until {fmt(g.expires_at)}{" "}
                    <button className="rv-link" disabled={busy}
                            onClick={() => run(() => apiReviewRevokeGrant(c.case_id, g.reviewer ?? ""), `Access for ${g.reviewer} ended.`)}>
                      End access<span className="sr-only"> for {g.reviewer}</span>
                    </button>
                  </li>
                ))}
              </ul>
            )}
          <form className="rv-row" onSubmit={(e) => { e.preventDefault(); run(() => apiReviewGrant(c.case_id, grantee, grantHours), `${grantee} can read this case for ${grantHours} hours.`); }}>
            <label htmlFor="rv-grantee" className="rv-label">Reviewer e-mail</label>
            <input id="rv-grantee" type="email" required className="rv-input rv-input--inline" value={grantee} onChange={(e) => setGrantee(e.target.value)} />
            <label htmlFor="rv-hours" className="rv-label">Hours</label>
            <input id="rv-hours" type="number" min={1} max={168} required className="rv-input rv-input--num" value={grantHours}
                   onChange={(e) => setGrantHours(Number(e.target.value))} />
            <button type="submit" className="rv-btn rv-btn--ghost" disabled={busy}>Give read access</button>
          </form>
        </div>
      )}

      <h3 className="rv-h3">Comments and history</h3>
      <ol className="rv-history">
        {history.map((h, i) => (
          <li key={i} className={h.event === "COMMENT" ? "rv-comment" : ""}>
            <span className="rv-muted">{fmt(h.created_at)}</span> · <strong>{EVENT_LABEL[h.event] ?? h.event}</strong> · {h.actor}
            {h.from_status && h.to_status && h.from_status !== h.to_status && ` · ${STATUS_LABEL[h.from_status] ?? h.from_status} → ${STATUS_LABEL[h.to_status] ?? h.to_status}`}
            {h.note && <div className="rv-quote">{h.note}</div>}
          </li>
        ))}
      </ol>
      {canComment && (
        <form className="rv-form" onSubmit={(e) => { e.preventDefault(); run(() => apiReviewComment(c.case_id, comment), "Comment added."); }}>
          <label htmlFor="rv-comment" className="rv-label">Add a comment</label>
          <textarea id="rv-comment" className="rv-input" rows={2} maxLength={2000} value={comment} onChange={(e) => setComment(e.target.value)} />
          <button type="submit" className="rv-btn rv-btn--ghost" disabled={busy || comment.trim().length < 3}>Add comment</button>
        </form>
      )}
      {reauth.dialog}
    </section>
  );
}
