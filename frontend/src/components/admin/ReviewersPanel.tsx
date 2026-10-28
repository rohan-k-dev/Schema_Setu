"use client";

/**
 * Reviewer approvals (docs/HUMAN_REVIEW.md, Access policy). The REVIEWER role alone gives no access
 * to review cases; an administrator approves the account here. Revoking signs the reviewer out and
 * ends their case grants. Both need a recent sign-in (the password is asked for when required).
 */

import React, { useCallback, useEffect, useState } from "react";
import { apiAdminReviewers, apiAdminSetReviewerApproval, ApiError } from "@/lib/api";
import type { AdminUser } from "@/lib/types";
import { useReauth } from "@/components/ReauthDialog";

export default function ReviewersPanel({ fail }: { fail: (err: unknown) => void }) {
  const [rows, setRows] = useState<AdminUser[] | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const reauth = useReauth();

  const load = useCallback(async () => {
    try {
      setRows((await apiAdminReviewers()).items);
    } catch (err) {
      fail(err);
    }
  }, [fail]);

  useEffect(() => { load(); }, [load]);

  const set = async (u: AdminUser, approved: boolean) => {
    setBusy(u.farmer_id);
    setMsg(null);
    try {
      await reauth.guard(() => apiAdminSetReviewerApproval(u.farmer_id, approved));
      setMsg({ ok: true, text: approved ? `${u.email} can now work review cases.`
                                        : `${u.email} no longer has review access and was signed out.` });
      load();
    } catch (err) {
      if (err instanceof ApiError && err.code === "REAUTH_CANCELLED") setMsg({ ok: false, text: "Not changed: password not confirmed." });
      else if (err instanceof ApiError && (err.status === 422 || err.status === 403)) setMsg({ ok: false, text: err.message });
      else fail(err);
    } finally {
      setBusy(null);
    }
  };

  return (
    <section className="adm-card" aria-labelledby="reviewers-title">
      <h2 id="reviewers-title" className="adm-card-title">Reviewer access</h2>
      <p className="adm-note">Accounts with the REVIEWER role can work review cases only after you approve them here.
        Revoking access signs the reviewer out immediately. Every change is audited.</p>
      {msg && <p className={msg.ok ? "adm-ok" : "adm-unavailable"} role={msg.ok ? "status" : "alert"}>{msg.text}</p>}
      {rows === null ? <p role="status">Loading…</p> : rows.length === 0 ? (
        <p className="adm-note">No REVIEWER accounts yet. Give an account the REVIEWER role first.</p>
      ) : (
        <table className="adm-table">
          <thead><tr><th scope="col">Reviewer</th><th scope="col">Account</th><th scope="col">Review access</th><th scope="col"><span className="sr-only">Action</span></th></tr></thead>
          <tbody>
            {rows.map((u) => (
              <tr key={u.farmer_id}>
                <td>{u.email}</td>
                <td>{u.is_active ? "active" : "deactivated"}</td>
                <td><span className={`adm-badge ${u.reviewer_approved ? "adm-badge--ok" : "adm-badge--muted"}`}>
                  {u.reviewer_approved ? "Approved" : "Not approved"}</span></td>
                <td>
                  <button className={`adm-btn ${u.reviewer_approved ? "adm-btn--ghost" : ""}`} disabled={busy === u.farmer_id}
                          onClick={() => set(u, !u.reviewer_approved)}>
                    {u.reviewer_approved ? "Revoke" : "Approve"}<span className="sr-only"> {u.email}</span>
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {reauth.dialog}
    </section>
  );
}
