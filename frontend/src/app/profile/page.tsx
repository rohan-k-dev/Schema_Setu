"use client";

/**
 * Profile edit page — save and edit farmer eligibility details.
 *
 * Route: /profile
 * Protected: redirects to /auth if not signed in.
 */

import React, { useCallback, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { useAuth } from "@/lib/AuthContext";
import { apiGetProfile, apiUpdateProfile, ApiError } from "@/lib/api";
import type { SavedFarmerProfile, ProfileUpdatePayload } from "@/lib/types";
import { CROPS, INCOME_RANGES, INDIAN_STATES, LAND_UNITS, OCCUPATIONS } from "@/lib/profileOptions";

// Fields the eligibility engine and scheme search use (Aadhaar status and exact
// income are not collected: no eligibility rule needs them).
const PROFILE_FIELDS = [
  "state","district","land_size","primary_crop",
  "age","gender","category","income_range","occupation","residence",
];

// Every editable field is sent on save; an empty field is sent as null = "unknown".
const EDITABLE: (keyof ProfileUpdatePayload)[] = [
  "state", "district", "land_size", "land_unit", "primary_crop", "farming_type", "occupation",
  "age", "gender", "category", "income_range", "residence",
];

function computeCompleteness(p: Partial<ProfileUpdatePayload>): number {
  const filled = PROFILE_FIELDS.filter((f) => {
    const v = (p as Record<string, unknown>)[f];
    return v !== undefined && v !== null && v !== "";
  });
  return Math.round((filled.length / PROFILE_FIELDS.length) * 100);
}

/** Form state from a saved profile (null → empty field = unknown). */
const formFromProfile = (p: SavedFarmerProfile): ProfileUpdatePayload => ({
  state: p.state ?? undefined,
  district: p.district ?? undefined,
  land_size: p.land_size ?? undefined,
  land_unit: p.land_unit ?? undefined,
  primary_crop: p.primary_crop ?? undefined,
  farming_type: p.farming_type ?? undefined,
  occupation: p.occupation ?? undefined,
  age: p.age ?? undefined,
  gender: p.gender ?? undefined,
  category: p.category ?? undefined,
  income_range: p.income_range ?? undefined,
  residence: p.residence ?? undefined,
  consent_given: p.consent_given,
});

export default function ProfilePage() {
  const router = useRouter();
  const { isAuthenticated, isLoading, user, handleUnauthorized } = useAuth();
  const signedInId = user?.farmer_id ?? null;

  const [profile, setProfile] = useState<SavedFarmerProfile | null>(null);
  const [form, setForm] = useState<ProfileUpdatePayload>({ consent_given: false });
  const [pageLoading, setPageLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);
  const [showConsent, setShowConsent] = useState(false);
  // Set when the profile was changed elsewhere (chat / another device) since it was loaded.
  const [conflict, setConflict] = useState(false);


  const reloadLatest = useCallback(async () => {
    const p = await apiGetProfile();
    if (p) { setProfile(p); setForm(formFromProfile(p)); }
    setConflict(false);
    setError(null);
  }, []);

  useEffect(() => {
    if (!isLoading && !isAuthenticated) {
      router.replace("/auth");
    }
  }, [isAuthenticated, isLoading, router]);

  useEffect(() => {
    if (!signedInId) return;
    (async () => {
      try {
        const p = await apiGetProfile();
        if (p) {
          setProfile(p);
          setForm(formFromProfile(p));
        }
      } catch (err) {
        if (err instanceof ApiError && err.status === 401) handleUnauthorized();
      } finally {
        setPageLoading(false);
      }
    })();
  }, [signedInId, handleUnauthorized]);

  const handleChange = (
    e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement>
  ) => {
    const { name, value, type } = e.target;
    const checked = (e.target as HTMLInputElement).checked;
    setForm((prev) => ({
      ...prev,
      [name]:
        type === "checkbox"
          ? checked
          : type === "number"
          ? value === ""
            ? undefined
            : parseFloat(value)
          : value === ""
          ? undefined
          : value,
    }));
    setSaved(false);
    setError(null);
  };

  const handleSubmit = useCallback(
    async (e: React.FormEvent) => {
      e.preventDefault();
      if (!form.consent_given && !profile?.consent_given) {
        setShowConsent(true);
        setError("Please give consent before saving your personal data.");
        return;
      }
      if (!signedInId) return;
      if (form.land_size != null && !form.land_unit) {
        setError("Please choose the unit for your land size.");
        return;
      }
      setSaving(true);
      setError(null);
      try {
        const payload: ProfileUpdatePayload = {
          consent_given: form.consent_given || profile?.consent_given || false,
        };
        for (const key of EDITABLE) {
          const v = form[key];
          (payload as unknown as Record<string, unknown>)[key] = v === undefined || v === "" ? null : v;
        }
        if (payload.land_size == null) payload.land_unit = null;
        if (profile) payload.expected_version = profile.version;
        const updated = await apiUpdateProfile(payload);
        setProfile(updated);
        setForm(formFromProfile(updated));
        setSaved(true);
        setTimeout(() => setSaved(false), 3000);
      } catch (err: unknown) {
        if (err instanceof ApiError && err.status === 401) handleUnauthorized();
        if (err instanceof ApiError && err.status === 409) setConflict(true);
        setError(err instanceof Error ? err.message : "Save failed. Please try again.");
      } finally {
        setSaving(false);
      }
    },
    [form, profile, signedInId, handleUnauthorized]
  );

  if (isLoading || pageLoading) {
    return (
      <div className="profile-loading">
        <div className="profile-spinner" />
        <p>Loading profile…</p>
      </div>
    );
  }

  const completeness = computeCompleteness(form);

  return (
    <div className="profile-page">
      <header className="profile-header">
        <div className="profile-header-inner">
          <button onClick={() => router.push("/dashboard")} className="profile-back min-h-[44px]">
            ← Dashboard
          </button>
          <div className="profile-header-title">
            <span className="profile-header-icon">🌾</span>
            <span>My Profile</span>
          </div>
        </div>
      </header>

      <main className="profile-main">
        {/* Completeness bar */}
        <div className="profile-completeness-card">
          <div className="profile-completeness-top">
            <span className="profile-completeness-label">Profile Completeness</span>
            <span className="profile-completeness-pct">{completeness}%</span>
          </div>
          <div className="profile-completeness-bar-bg">
            <div
              className="profile-completeness-bar-fill"
              style={{ width: `${completeness}%` }}
            />
          </div>
          <p className="profile-completeness-tip">
            A complete profile helps us find more accurate scheme matches for you.
          </p>
        </div>

        <form onSubmit={handleSubmit} className="profile-form" noValidate>
          {/* Location */}
          <section className="profile-section">
            <h2 className="profile-section-title">📍 Location</h2>
            <div className="profile-grid">
              <div className="profile-field">
                <label htmlFor="state" className="profile-label">State / UT</label>
                <select id="state" name="state" value={form.state ?? ""} onChange={handleChange} className="profile-select">
                  <option value="">Select state…</option>
                  {INDIAN_STATES.map((s) => <option key={s} value={s}>{s}</option>)}
                </select>
              </div>
              <div className="profile-field">
                <label htmlFor="district" className="profile-label">District</label>
                <input id="district" name="district" type="text" value={form.district ?? ""} onChange={handleChange} className="profile-input" placeholder="e.g. Nashik" />
              </div>
            </div>
          </section>

          {/* Farming Details */}
          <section className="profile-section">
            <h2 className="profile-section-title">🌱 Farming Details</h2>
            <div className="profile-grid">
              <div className="profile-field">
                <label htmlFor="land_size" className="profile-label">Land Size</label>
                <div className="profile-land-row">
                  <input id="land_size" name="land_size" type="number" min={0} step={0.01} value={form.land_size ?? ""} onChange={handleChange} className="profile-input" placeholder="e.g. 2.5" />
                  <select id="land_unit" name="land_unit" aria-label="Land unit" value={form.land_unit ?? ""} onChange={handleChange} className="profile-select">
                    <option value="">Unit…</option>
                    {LAND_UNITS.map((u) => <option key={u.value} value={u.value}>{u.label}</option>)}
                  </select>
                </div>
                {profile?.land_size_acres != null && profile.land_unit !== "acre" && (
                  <p className="profile-hint">= {profile.land_size_acres} acres</p>
                )}
              </div>
              <div className="profile-field">
                <label htmlFor="primary_crop" className="profile-label">Primary Crop</label>
                <select id="primary_crop" name="primary_crop" value={form.primary_crop ?? ""} onChange={handleChange} className="profile-select">
                  <option value="">Select crop…</option>
                  {CROPS.map((c) => <option key={c} value={c}>{c.charAt(0).toUpperCase() + c.slice(1)}</option>)}
                </select>
              </div>
              <div className="profile-field">
                <label htmlFor="farming_type" className="profile-label">Farming Type</label>
                <select id="farming_type" name="farming_type" value={form.farming_type ?? ""} onChange={handleChange} className="profile-select">
                  <option value="">Select…</option>
                  <option value="subsistence">Subsistence</option>
                  <option value="commercial">Commercial</option>
                  <option value="mixed">Mixed</option>
                </select>
              </div>
              <div className="profile-field">
                <label htmlFor="occupation" className="profile-label">Occupation</label>
                <select id="occupation" name="occupation" value={form.occupation ?? ""} onChange={handleChange} className="profile-select">
                  <option value="">Not given</option>
                  {[...OCCUPATIONS, ...(form.occupation && !OCCUPATIONS.includes(form.occupation) ? [form.occupation] : [])]
                    .map((o) => <option key={o} value={o}>{o.charAt(0).toUpperCase() + o.slice(1)}</option>)}
                </select>
              </div>
            </div>
          </section>

          {/* Demographics */}
          <section className="profile-section">
            <h2 className="profile-section-title">👤 Personal Details</h2>
            <div className="profile-grid">
              <div className="profile-field">
                <label htmlFor="age" className="profile-label">Age (years)</label>
                <input id="age" name="age" type="number" min={1} max={119} value={form.age ?? ""} onChange={handleChange} className="profile-input" placeholder="e.g. 35" />
              </div>
              <div className="profile-field">
                <label htmlFor="gender" className="profile-label">Gender</label>
                <select id="gender" name="gender" value={form.gender ?? ""} onChange={handleChange} className="profile-select">
                  <option value="">Prefer not to say</option>
                  <option value="male">Male</option>
                  <option value="female">Female</option>
                  <option value="other">Other</option>
                </select>
              </div>
              <div className="profile-field">
                <label htmlFor="category" className="profile-label">Category</label>
                <select id="category" name="category" value={form.category ?? ""} onChange={handleChange} className="profile-select">
                  <option value="">Prefer not to say</option>
                  {["General","OBC","SC","ST","EWS"].map((c) => <option key={c} value={c}>{c}</option>)}
                </select>
              </div>
              <div className="profile-field">
                <label htmlFor="income_range" className="profile-label">Yearly Household Income</label>
                <select id="income_range" name="income_range" value={form.income_range ?? ""} onChange={handleChange} className="profile-select">
                  <option value="">Prefer not to say</option>
                  {INCOME_RANGES.map((r) => <option key={r.value} value={r.value}>{r.label}</option>)}
                </select>
              </div>
              <div className="profile-field">
                <label htmlFor="residence" className="profile-label">Where you live</label>
                <select id="residence" name="residence" value={form.residence ?? ""} onChange={handleChange} className="profile-select">
                  <option value="">Not given</option>
                  <option value="rural">Village (rural)</option>
                  <option value="urban">Town / city (urban)</option>
                </select>
              </div>
            </div>
            <p className="profile-hint">
              All personal details are optional. Leave a field empty if you are not sure — it is
              kept as &quot;unknown&quot;, never as &quot;no&quot;. We never ask for your Aadhaar number.
            </p>
          </section>

          {/* Consent */}
          <section className={`profile-consent ${showConsent && !form.consent_given ? "profile-consent--highlight" : ""}`}>
            <div className="profile-consent-header">
              <span className="profile-consent-icon">🔒</span>
              <h3 className="profile-consent-title">Data Consent</h3>
            </div>
            <p className="profile-consent-body">
              Your details (state, land, crop, age, income range, etc.) will be securely
              stored to provide personalized government scheme recommendations. You can
              edit or delete your data at any time. We will never share your data with
              third parties without your permission.
            </p>
            <div className="profile-checkbox-row">
              <input
                id="consent_given"
                name="consent_given"
                type="checkbox"
                checked={form.consent_given}
                onChange={handleChange}
                className="profile-checkbox"
              />
              <label htmlFor="consent_given" className="profile-checkbox-label profile-checkbox-label--consent">
                I understand and agree to save my personal data for scheme recommendations.
              </label>
            </div>
            <p className="profile-hint">
              What is kept, why, which outside services receive some details, and how to download or delete them:{" "}
              <a href="/privacy" className="underline">Privacy and data settings</a>. You can withdraw this consent there
              at any time (your saved details are then deleted).
            </p>
          </section>

          {/* Error / Success */}
          {error && <div className="profile-alert profile-alert--error" role="alert">⚠️ {error}</div>}
          {conflict && (
            <button type="button" onClick={reloadLatest} className="profile-cancel min-h-[44px]">
              Reload latest profile
            </button>
          )}
          {saved && <div className="profile-alert profile-alert--success" role="status">✅ Profile saved successfully!</div>}

          {/* Submit */}
          <div className="profile-actions">
            <button type="button" onClick={() => router.push("/dashboard")} className="profile-cancel min-h-[44px]">
              Cancel
            </button>
            <button type="submit" disabled={saving} className="profile-save min-h-[44px]">
              {saving ? (
                <span className="profile-btn-loading">
                  <span className="profile-spinner-sm" /> Saving…
                </span>
              ) : "Save Profile"}
            </button>
          </div>
        </form>
      </main>

      <style>{`
        .profile-page {
          min-height: 100vh;
          background: #f0fdf4;
          font-family: var(--font-geist-sans, sans-serif);
        }
        .profile-loading {
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
        .profile-header {
          background: linear-gradient(135deg, #064e3b 0%, #065f46 100%);
          color: white;
          padding: 1rem 1.5rem;
          position: sticky;
          top: 0;
          z-index: 10;
          box-shadow: 0 2px 12px rgba(0,0,0,0.2);
        }
        .profile-header-inner {
          max-width: 800px;
          margin: 0 auto;
          display: flex;
          align-items: center;
          gap: 1rem;
        }
        .profile-back {
          background: rgba(255,255,255,0.15);
          border: 1px solid rgba(255,255,255,0.2);
          color: white;
          padding: 0.4rem 0.9rem;
          border-radius: 0.5rem;
          cursor: pointer;
          font-size: 0.85rem;
          font-weight: 600;
          transition: background 0.2s;
          white-space: nowrap;
        }
        .profile-back:hover { background: rgba(255,255,255,0.25); }
        .profile-header-title {
          display: flex;
          align-items: center;
          gap: 0.5rem;
          font-size: 1.1rem;
          font-weight: 700;
        }
        .profile-header-icon { font-size: 1.3rem; }
        .profile-main {
          max-width: 800px;
          margin: 0 auto;
          padding: 1.5rem 1rem 3rem;
        }
        .profile-completeness-card {
          background: white;
          border-radius: 1rem;
          padding: 1.25rem 1.5rem;
          margin-bottom: 1.5rem;
          box-shadow: 0 2px 12px rgba(0,0,0,0.06);
          border: 1px solid #d1fae5;
        }
        .profile-completeness-top {
          display: flex;
          justify-content: space-between;
          align-items: center;
          margin-bottom: 0.6rem;
        }
        .profile-completeness-label {
          font-size: 0.9rem;
          font-weight: 700;
          color: #374151;
        }
        .profile-completeness-pct {
          font-size: 1.1rem;
          font-weight: 800;
          color: #059669;
        }
        .profile-completeness-bar-bg {
          height: 8px;
          background: #d1fae5;
          border-radius: 99px;
          overflow: hidden;
          margin-bottom: 0.5rem;
        }
        .profile-completeness-bar-fill {
          height: 100%;
          background: linear-gradient(90deg, #059669, #10b981);
          border-radius: 99px;
          transition: width 0.5s ease;
        }
        .profile-completeness-tip {
          font-size: 0.78rem;
          color: #6b7280;
          margin: 0;
        }
        .profile-form {
          display: flex;
          flex-direction: column;
          gap: 1.25rem;
        }
        .profile-section {
          background: white;
          border-radius: 1rem;
          padding: 1.5rem;
          box-shadow: 0 2px 12px rgba(0,0,0,0.06);
          border: 1px solid #e5e7eb;
        }
        .profile-section-title {
          font-size: 0.95rem;
          font-weight: 700;
          color: #064e3b;
          margin: 0 0 1rem;
          padding-bottom: 0.6rem;
          border-bottom: 2px solid #d1fae5;
        }
        .profile-grid {
          display: grid;
          grid-template-columns: 1fr 1fr;
          gap: 1rem;
        }
        @media (max-width: 560px) {
          .profile-grid { grid-template-columns: 1fr; }
        }
        .profile-field {
          display: flex;
          flex-direction: column;
          gap: 0.3rem;
        }
        .profile-label {
          font-size: 0.8rem;
          font-weight: 600;
          color: #374151;
        }
        .profile-input, .profile-select {
          padding: 0.6rem 0.8rem;
          border: 1.5px solid #d1d5db;
          border-radius: 0.6rem;
          font-size: 0.88rem;
          color: #111827;
          background: #f9fafb;
          transition: border-color 0.2s, box-shadow 0.2s;
          outline: none;
          width: 100%;
          box-sizing: border-box;
        }
        .profile-input:focus, .profile-select:focus {
          border-color: #059669;
          box-shadow: 0 0 0 3px rgba(5,150,105,0.12);
          background: white;
        }
        .profile-land-row { display: grid; grid-template-columns: 1fr 1fr; gap: 0.5rem; }
        .profile-hint { font-size: 0.78rem; color: #6b7280; margin-top: 0.35rem; }
        .profile-checkbox-row {
          display: flex;
          align-items: flex-start;
          gap: 0.6rem;
          margin-top: 1rem;
        }
        .profile-checkbox {
          width: 1.1rem;
          height: 1.1rem;
          accent-color: #059669;
          flex-shrink: 0;
          margin-top: 0.15rem;
          cursor: pointer;
        }
        .profile-checkbox-label {
          font-size: 0.87rem;
          color: #374151;
          cursor: pointer;
          line-height: 1.4;
        }
        .profile-checkbox-label--consent {
          font-weight: 600;
          color: #064e3b;
        }
        .profile-consent {
          background: white;
          border-radius: 1rem;
          padding: 1.5rem;
          box-shadow: 0 2px 12px rgba(0,0,0,0.06);
          border: 2px solid #d1fae5;
          transition: border-color 0.3s;
        }
        .profile-consent--highlight {
          border-color: #f59e0b;
          background: #fffbeb;
          animation: shake 0.4s ease;
        }
        @keyframes shake {
          0%,100% { transform: translateX(0); }
          25% { transform: translateX(-6px); }
          75% { transform: translateX(6px); }
        }
        .profile-consent-header {
          display: flex;
          align-items: center;
          gap: 0.5rem;
          margin-bottom: 0.75rem;
        }
        .profile-consent-icon { font-size: 1.2rem; }
        .profile-consent-title {
          font-size: 0.95rem;
          font-weight: 700;
          color: #064e3b;
          margin: 0;
        }
        .profile-consent-body {
          font-size: 0.83rem;
          color: #4b5563;
          line-height: 1.6;
          margin: 0 0 0.75rem;
        }
        .profile-alert {
          padding: 0.75rem 1rem;
          border-radius: 0.7rem;
          font-size: 0.875rem;
          font-weight: 500;
        }
        .profile-alert--error {
          background: #fef2f2;
          color: #991b1b;
          border: 1px solid #fecaca;
        }
        .profile-alert--success {
          background: #f0fdf4;
          color: #166534;
          border: 1px solid #bbf7d0;
        }
        .profile-actions {
          display: flex;
          gap: 0.75rem;
          justify-content: flex-end;
        }
        .profile-cancel {
          padding: 0.7rem 1.5rem;
          border: 1.5px solid #d1d5db;
          border-radius: 0.7rem;
          background: white;
          color: #4b5563;
          font-size: 0.9rem;
          font-weight: 600;
          cursor: pointer;
          transition: all 0.2s;
        }
        .profile-cancel:hover { background: #f3f4f6; border-color: #9ca3af; }
        .profile-save {
          padding: 0.7rem 2rem;
          background: linear-gradient(135deg, #059669, #047857);
          color: white;
          border: none;
          border-radius: 0.7rem;
          font-size: 0.9rem;
          font-weight: 700;
          cursor: pointer;
          box-shadow: 0 4px 12px rgba(5,150,105,0.3);
          transition: all 0.2s;
          min-height: 44px;
        }
        .profile-save:hover:not(:disabled) {
          background: linear-gradient(135deg, #047857, #065f46);
          box-shadow: 0 6px 16px rgba(5,150,105,0.4);
          transform: translateY(-1px);
        }
        .profile-save:disabled { opacity: 0.65; cursor: not-allowed; transform: none; }
        .profile-btn-loading {
          display: flex;
          align-items: center;
          gap: 0.4rem;
        }
        .profile-spinner {
          width: 2rem;
          height: 2rem;
          border: 3px solid #d1fae5;
          border-top-color: #059669;
          border-radius: 50%;
          animation: spin 0.7s linear infinite;
        }
        .profile-spinner-sm {
          width: 0.9rem;
          height: 0.9rem;
          border: 2px solid rgba(255,255,255,0.4);
          border-top-color: white;
          border-radius: 50%;
          animation: spin 0.7s linear infinite;
          display: inline-block;
        }
        @keyframes spin { to { transform: rotate(360deg); } }
      `}</style>
    </div>
  );
}
