"use client";

/**
 * Details the eligibility engine still needs, and saved details that conflict.
 * Each can be fixed in place: the change is saved to the profile (with the
 * profile version, so a newer edit elsewhere is never overwritten) and then
 * eligibility is recalculated.
 */

import React, { useState } from "react";
import { apiUpdateProfile, ApiError } from "@/lib/api";
import {
  CATEGORIES, CROPS, GENDERS, INCOME_RANGES, INDIAN_STATES, LAND_UNITS, OCCUPATIONS, RESIDENCES,
} from "@/lib/profileOptions";
import type { MissingDetail, ProfileConflict, ProfileUpdatePayload, SavedFarmerProfile } from "@/lib/types";

const LABELS: Record<string, string> = {
  state: "State", district: "District", land_size: "Land size", primary_crop: "Main crop",
  occupation: "Occupation", age: "Age", gender: "Gender", category: "Social category",
  income_range: "Yearly household income", residence: "Rural or urban",
};

type Opt = { value: string; label: string };
const plain = (xs: string[]): Opt[] => xs.map((x) => ({ value: x, label: x.charAt(0).toUpperCase() + x.slice(1) }));
const SELECTS: Record<string, Opt[]> = {
  state: plain(INDIAN_STATES), primary_crop: plain(CROPS), occupation: plain(OCCUPATIONS),
  gender: GENDERS, category: plain(CATEGORIES), income_range: INCOME_RANGES, residence: RESIDENCES,
};

function currentValue(p: SavedFarmerProfile, field: string): string {
  const v = (p as unknown as Record<string, unknown>)[field];
  return v === null || v === undefined ? "" : String(v);
}

function FieldEditor({
  field,
  profile,
  allowClear,
  onSaved,
}: {
  field: string;
  profile: SavedFarmerProfile;
  allowClear: boolean;
  onSaved: (message: string) => void;
}) {
  const id = `fix-${field}`;
  const [value, setValue] = useState(currentValue(profile, field));
  const [unit, setUnit] = useState<string>(profile.land_unit ?? "acre");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const label = LABELS[field] ?? field.replace(/_/g, " ");

  const save = async () => {
    setError(null);
    if (!value && !allowClear) { setError(`Please enter your ${label.toLowerCase()}.`); return; }
    const payload: ProfileUpdatePayload = {
      consent_given: profile.consent_given,
      expected_version: profile.version,
    };
    const v = value === "" ? null : value;
    if (field === "land_size") {
      payload.land_size = v === null ? null : Number(v);
      payload.land_unit = v === null ? null : (unit as ProfileUpdatePayload["land_unit"]);
    } else if (field === "age") {
      payload.age = v === null ? null : Number(v);
    } else {
      (payload as unknown as Record<string, unknown>)[field] = v;
    }
    setSaving(true);
    try {
      await apiUpdateProfile(payload);
      onSaved(`${label} saved. Eligibility updated.`);
    } catch (err) {
      if (err instanceof ApiError && err.status === 409) {
        onSaved("Your profile was changed somewhere else, so nothing was overwritten. The latest details are shown — please check and try again.");
      } else {
        setError(err instanceof Error ? err.message : "Could not save. Please try again.");
      }
    } finally {
      setSaving(false);
    }
  };

  const options = SELECTS[field];
  return (
    <div className="fix-editor">
      <label htmlFor={id} className="fix-label">{label}</label>
      <div className="fix-row">
        {options ? (
          <select id={id} value={value} onChange={(e) => setValue(e.target.value)} className="fix-input">
            <option value="">{allowClear ? "Not given" : "Choose…"}</option>
            {options.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
          </select>
        ) : field === "land_size" ? (
          <>
            <input id={id} type="number" min={0} step="any" inputMode="decimal" value={value}
                   onChange={(e) => setValue(e.target.value)} className="fix-input fix-input--num" />
            <select aria-label="Land unit" value={unit} onChange={(e) => setUnit(e.target.value)} className="fix-input">
              {LAND_UNITS.map((u) => <option key={u.value} value={u.value}>{u.label}</option>)}
            </select>
          </>
        ) : field === "age" ? (
          <input id={id} type="number" min={1} max={119} inputMode="numeric" value={value}
                 onChange={(e) => setValue(e.target.value)} className="fix-input fix-input--num" />
        ) : (
          <input id={id} type="text" maxLength={100} value={value}
                 onChange={(e) => setValue(e.target.value)} className="fix-input" />
        )}
        <button onClick={save} disabled={saving} className="dash-primary-btn min-h-[44px]">
          {saving ? "Saving…" : "Save & recheck"}
        </button>
      </div>
      {error && <p className="fix-error" role="alert">{error}</p>}
    </div>
  );
}

export default function ProfileFixesPanel({
  profile,
  missing,
  conflicts,
  onSaved,
  onSetUp,
}: {
  profile: SavedFarmerProfile | null;
  missing: MissingDetail[];
  conflicts: ProfileConflict[];
  onSaved: (message: string) => void;
  onSetUp: () => void;
}) {
  if (missing.length === 0 && conflicts.length === 0) return null;
  // The key resets the editors whenever the saved profile changes.
  const k = profile ? `v${profile.version}` : "none";

  return (
    <section className="dash-card dash-card--wide dash-card--highlight" aria-labelledby="fix-title">
      <div className="dash-card-header">
        <h2 id="fix-title" className="dash-card-title">📝 Details to check</h2>
      </div>

      {!profile ? (
        <>
          <p className="dash-empty">
            Eligibility needs a few details about you. Set up your profile once and every scheme is checked automatically.
          </p>
          <button onClick={onSetUp} className="dash-fill-btn min-h-[44px]">Set Up Profile →</button>
        </>
      ) : (
        <>
          {conflicts.length > 0 && (
            <div className="fix-group">
              <h3 className="fix-heading">These details don&apos;t fit together</h3>
              {conflicts.map((c, i) => (
                <div key={`${k}-c${i}`} className="fix-conflict" role="alert">
                  <p>{c.message}</p>
                  {c.fields.map((f) => (
                    <FieldEditor key={`${k}-${f}`} field={f} profile={profile} allowClear onSaved={onSaved} />
                  ))}
                </div>
              ))}
            </div>
          )}
          {missing.length > 0 && (
            <div className="fix-group">
              <h3 className="fix-heading">Missing details</h3>
              <ul className="fix-list">
                {missing.map((m) => (
                  <li key={`${k}-${m.field}`} className="fix-item">
                    <p className="fix-why">
                      Needed for {m.scheme_count} scheme{m.scheme_count !== 1 ? "s" : ""}: {m.schemes.join(", ")}
                      {m.scheme_count > m.schemes.length ? ` and ${m.scheme_count - m.schemes.length} more` : ""}.
                    </p>
                    <FieldEditor field={m.field} profile={profile} allowClear={false} onSaved={onSaved} />
                  </li>
                ))}
              </ul>
            </div>
          )}
        </>
      )}
    </section>
  );
}
