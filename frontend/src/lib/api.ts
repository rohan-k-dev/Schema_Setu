/**
 * Centralized API client — Phase 6 + Phase 9 (auth & profile).
 *
 * All backend requests go through this module.
 * Language parameter added to chat/voice for multilingual support (§12).
 */

import type {
  ChatResponse,
  TTSResponse,
  HealthResponse,
  SessionResponse,
  RegisterPayload,
  LoginPayload,
  SavedFarmerProfile,
  ProfileUpdatePayload,
  SavedSchemeDetail,
  SavedSchemeSummary,
  SaveSchemeResult,
  SearchHistoryEntry,
  DashboardData,
  EligibilityBasis,
  EligibilityDashboard,
  EligibilityStatusValue,
  AdminOverview,
  ValidationReport,
  ConflictReport,
  Page,
  OpsError,
  AdminJob,
  AdminJobKind,
  AuditEventView,
  AuditIntegrity,
  AppNotification,
  NotificationPreferences,
  PreferencesResponse,
  ChangeBatch,
  SchemeChange,
  FarmerReviewCase,
  ReviewCaseStatus,
  ReviewAccess,
  ReviewCaseSummary,
  ReviewCaseView,
  ReviewGrant,
  AdminUser,
  ReviewDecisionAction,
  ReviewEvent,
  ReviewStats,
  MyDataSummary,
  PrivacyPolicy,
} from "./types";

const API_BASE_URL =
  process.env.NEXT_PUBLIC_API_BASE_URL || "http://localhost:8000";

/**
 * Accounts use a server-managed session in an HttpOnly cookie (never readable by
 * JavaScript). Requests send it with `credentials: "include"`. State-changing
 * requests also send the session's CSRF token, which lives only in memory here.
 */
let csrfToken: string | null = null;

export function setCsrfToken(token: string | null): void {
  csrfToken = token;
}

function withCsrf(headers: Record<string, string> = {}): Record<string, string> {
  return csrfToken ? { ...headers, "X-CSRF-Token": csrfToken } : headers;
}

/** Error with the HTTP status, so callers can react to 401 (signed out) etc. */
export class ApiError extends Error {
  status: number;
  code?: string;
  constructor(message: string, status: number, code?: string) {
    super(message);
    this.status = status;
    this.code = code;
  }
}

type ErrorBody = {
  error?: { message?: string; code?: string };
  detail?: { message?: string; code?: string } | { msg?: string }[];
} | null;

async function apiError(res: Response, fallback: string): Promise<ApiError> {
  let data: ErrorBody = null;
  try { data = await res.json(); } catch { /* empty body */ }
  const detail = data?.detail;
  const validation = Array.isArray(detail) && detail[0]?.msg
    ? String(detail[0].msg).replace(/^Value error, /, "") : undefined;
  const message = data?.error?.message
    || (!Array.isArray(detail) ? detail?.message : undefined)
    || validation
    || (res.status === 429 ? "Too many attempts. Please wait a few minutes and try again." : fallback);
  const code = data?.error?.code || (!Array.isArray(detail) ? detail?.code : undefined);
  return new ApiError(message, res.status, code);
}

/**
 * Language info returned from /languages endpoint.
 */
export interface LanguageInfo {
  code: string;
  name: string;
  english_name: string;
  has_voice: boolean;
  has_tts: boolean;
}

/**
 * Fetch supported languages from backend (§11).
 */
export async function fetchLanguages(): Promise<LanguageInfo[]> {
  try {
    const response = await fetch(`${API_BASE_URL}/languages`);
    if (!response.ok) return [];
    const data = await response.json();
    return data.languages || [];
  } catch {
    return [];
  }
}

/**
 * Send a text chat message to the backend (§5 — same pipeline for text+voice).
 */
export async function sendChat(
  message: string,
  threadId: string = "default_session",
  language: string = "en",
  consentToSaveProfile: boolean = false
): Promise<ChatResponse> {
  const response = await fetch(`${API_BASE_URL}/chat`, {
    method: "POST",
    credentials: "include",
    headers: withCsrf({ "Content-Type": "application/json" }),
    body: JSON.stringify({
      message,
      thread_id: threadId,
      language,
      consent_to_save_profile: consentToSaveProfile,
    }),
  });

  if (!response.ok) {
    throw new Error(`Chat request failed: ${response.status} ${response.statusText}`);
  }

  return response.json();
}

/**
 * Send voice audio to the backend for ASR + agent processing (§19).
 */
export async function sendVoice(
  audioBlob: Blob,
  filename: string,
  threadId: string = "default_session",
  language: string = "en",
  consentToSaveProfile: boolean = false
): Promise<ChatResponse> {
  const formData = new FormData();
  formData.append("file", audioBlob, filename);
  formData.append("thread_id", threadId);
  formData.append("language", language);
  formData.append("consent_to_save_profile", String(consentToSaveProfile));

  const response = await fetch(`${API_BASE_URL}/voice`, {
    method: "POST",
    credentials: "include",
    headers: withCsrf(),
    body: formData,
  });

  if (!response.ok) {
    throw new Error(`Voice request failed: ${response.status} ${response.statusText}`);
  }

  return response.json();
}

/**
 * Generate TTS audio from text (§32).
 */
export async function generateTTS(
  text: string,
  languageCode: string = "hi-IN"
): Promise<TTSResponse> {
  const response = await fetch(`${API_BASE_URL}/tts`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ text, language_code: languageCode }),
  });

  if (!response.ok) {
    throw new Error(`TTS request failed: ${response.status} ${response.statusText}`);
  }

  return response.json();
}

/**
 * Check backend health status.
 */
export async function healthCheck(): Promise<HealthResponse> {
  const response = await fetch(`${API_BASE_URL}/health`);

  if (!response.ok) {
    throw new Error(`Health check failed: ${response.status}`);
  }

  return response.json();
}

// ─── Auth API ─────────────────────────────────────────────────────────────────

async function postJson(path: string, body: unknown, fallback: string): Promise<Response> {
  const res = await fetch(`${API_BASE_URL}${path}`, {
    method: "POST",
    credentials: "include",
    headers: withCsrf({ "Content-Type": "application/json" }),
    body: JSON.stringify(body ?? {}),
  });
  if (!res.ok) throw await apiError(res, fallback);
  return res;
}

/** Creates an unverified account; the server e-mails a verification link. */
export async function apiRegister(payload: RegisterPayload): Promise<string> {
  const res = await postJson("/auth/register", payload, "Registration failed.");
  return (await res.json()).message;
}

export async function apiLogin(payload: LoginPayload): Promise<SessionResponse> {
  const res = await postJson("/auth/login", payload, "Sign-in failed.");
  return res.json();
}

/** The current session (user + CSRF token), or null when signed out. */
export async function apiGetSession(): Promise<SessionResponse | null> {
  const res = await fetch(`${API_BASE_URL}/auth/session`, { credentials: "include" });
  if (res.status === 401 || res.status === 503) return null;
  if (!res.ok) throw await apiError(res, "Could not check your session.");
  return res.json();
}

export async function apiLogout(): Promise<void> {
  await postJson("/auth/logout", {}, "Sign-out failed.");
}

export async function apiLogoutAll(): Promise<string> {
  const res = await postJson("/auth/logout-all", {}, "Sign-out failed.");
  return (await res.json()).message;
}

export async function apiVerifyEmail(token: string): Promise<string> {
  const res = await postJson("/auth/verify-email", { token }, "Verification failed.");
  return (await res.json()).message;
}

export async function apiResendVerification(email: string): Promise<string> {
  const res = await postJson("/auth/resend-verification", { email }, "Could not send the link.");
  return (await res.json()).message;
}

export async function apiForgotPassword(email: string): Promise<string> {
  const res = await postJson("/auth/forgot-password", { email }, "Could not send the link.");
  return (await res.json()).message;
}

export async function apiResetPassword(token: string, newPassword: string): Promise<string> {
  const res = await postJson("/auth/reset-password", { token, new_password: newPassword },
                             "Password reset failed.");
  return (await res.json()).message;
}

export async function apiChangePassword(currentPassword: string, newPassword: string): Promise<SessionResponse> {
  const res = await postJson("/auth/change-password",
                             { current_password: currentPassword, new_password: newPassword },
                             "Password change failed.");
  return res.json();
}

// ─── Farmer / Profile API (signed in: session cookie) ─────────────────────────

async function farmerFetch(path: string, init: RequestInit = {}): Promise<Response> {
  const method = (init.method || "GET").toUpperCase();
  const base: Record<string, string> = init.body ? { "Content-Type": "application/json" } : {};
  return fetch(`${API_BASE_URL}${path}`, {
    ...init,
    credentials: "include",
    headers: method === "GET" ? base : withCsrf(base),
  });
}

export async function apiGetDashboard(): Promise<DashboardData> {
  const res = await farmerFetch("/farmers/me/dashboard");
  if (!res.ok) throw await apiError(res, "Failed to load dashboard.");
  return res.json();
}

export async function apiGetProfile(): Promise<SavedFarmerProfile | null> {
  const res = await farmerFetch("/farmers/me/profile");
  if (res.status === 404) return null;
  if (!res.ok) throw await apiError(res, "Failed to load profile.");
  return res.json();
}

export async function apiUpdateProfile(payload: ProfileUpdatePayload): Promise<SavedFarmerProfile> {
  const res = await farmerFetch("/farmers/me/profile", { method: "PUT", body: JSON.stringify(payload) });
  if (!res.ok) throw await apiError(res, "Profile update failed.");
  return res.json();
}

// Saved schemes + checklists. Progress is user-reported (docs/SAVED_SCHEMES.md).

const savedPath = (schemeId: string) => `/farmers/me/saved-schemes/${encodeURIComponent(schemeId)}`;

export async function apiGetSavedSchemes(): Promise<SavedSchemeSummary[]> {
  const res = await farmerFetch("/farmers/me/saved-schemes");
  if (!res.ok) throw await apiError(res, "Failed to load saved schemes.");
  return res.json();
}

/** Saves a scheme from SchemeSetu's database; saving it again changes nothing (created: false). */
export async function apiSaveScheme(
  payload: { scheme_id: string; eligibility_status?: string | null; notes?: string }
): Promise<SaveSchemeResult> {
  const res = await farmerFetch("/farmers/me/saved-schemes", { method: "POST", body: JSON.stringify(payload) });
  if (!res.ok) throw await apiError(res, "Failed to save scheme.");
  return res.json();
}

export async function apiDeleteSavedScheme(schemeId: string): Promise<void> {
  const res = await farmerFetch(savedPath(schemeId), { method: "DELETE" });
  if (!res.ok && res.status !== 404) throw await apiError(res, "Failed to remove scheme.");
}

export async function apiGetSavedScheme(schemeId: string): Promise<SavedSchemeDetail> {
  const res = await farmerFetch(savedPath(schemeId));
  if (!res.ok) throw await apiError(res, "Failed to load the checklist.");
  return res.json();
}

/** Left-out fields are unchanged; null clears notes / the application reference. */
export async function apiUpdateSavedScheme(
  schemeId: string,
  payload: { notes?: string | null; application_reference?: string | null; acknowledge_scheme_update?: true }
): Promise<SavedSchemeDetail> {
  const res = await farmerFetch(savedPath(schemeId), { method: "PATCH", body: JSON.stringify(payload) });
  if (!res.ok) throw await apiError(res, "Could not save.");
  return res.json();
}

export async function apiUpdateChecklistItem(
  schemeId: string, itemId: number, payload: { completed?: boolean; note?: string | null }
): Promise<SavedSchemeDetail> {
  const res = await farmerFetch(`${savedPath(schemeId)}/checklist/${itemId}`,
                                { method: "PATCH", body: JSON.stringify(payload) });
  if (!res.ok) throw await apiError(res, "Could not update the checklist.");
  return res.json();
}

export async function apiAddMilestone(
  schemeId: string, payload: { label: string; note?: string; completed?: boolean }
): Promise<SavedSchemeDetail> {
  const res = await farmerFetch(`${savedPath(schemeId)}/checklist`, { method: "POST", body: JSON.stringify(payload) });
  if (!res.ok) throw await apiError(res, "Could not add the milestone.");
  return res.json();
}

export async function apiDeleteMilestone(schemeId: string, itemId: number): Promise<SavedSchemeDetail> {
  const res = await farmerFetch(`${savedPath(schemeId)}/checklist/${itemId}`, { method: "DELETE" });
  if (!res.ok) throw await apiError(res, "Could not delete the milestone.");
  return res.json();
}

export async function apiGetSearchHistory(limit = 10): Promise<SearchHistoryEntry[]> {
  const res = await farmerFetch(`/farmers/me/search-history?limit=${limit}`);
  if (!res.ok) return [];
  return res.json();
}

export async function apiGetSearchHistoryPage(
  limit: number, offset: number
): Promise<{ items: SearchHistoryEntry[]; total: number }> {
  const res = await farmerFetch(`/farmers/me/search-history?limit=${limit}&offset=${offset}`);
  if (!res.ok) throw await apiError(res, "Failed to load search history.");
  const items: SearchHistoryEntry[] = await res.json();
  return { items, total: Number(res.headers.get("X-Total-Count") ?? items.length) };
}

export async function apiDeleteSearch(entryId: number): Promise<void> {
  const res = await farmerFetch(`/farmers/me/search-history/${entryId}`, { method: "DELETE" });
  if (!res.ok && res.status !== 404) throw await apiError(res, "Failed to delete search.");
}

export async function apiClearSearchHistory(): Promise<number> {
  const res = await farmerFetch("/farmers/me/search-history", { method: "DELETE" });
  if (!res.ok) throw await apiError(res, "Failed to clear search history.");
  return (await res.json()).deleted;
}

// ─── Administrator operations (docs/ADMIN_OPERATIONS.md) ─────────────────────
// The backend enforces ADMIN on every call; the page only displays what it returns.

async function adminJson<T>(path: string, init: RequestInit = {}, fallback = "Request failed."): Promise<T> {
  const res = await farmerFetch(path, init);
  if (!res.ok) throw await apiError(res, fallback);
  return res.json();
}

export const apiAdminOverview = () => adminJson<AdminOverview>("/admin/ops/overview", {}, "Could not load the dashboard.");
export const apiAdminValidate = () =>
  adminJson<ValidationReport>("/admin/ops/validate", { method: "POST" }, "Validation failed.");
export const apiAdminConflicts = () => adminJson<ConflictReport>("/admin/ops/conflicts", {}, "Could not load conflicts.");
export const apiAdminErrors = (limit: number, offset: number) =>
  adminJson<Page<OpsError>>(`/admin/ops/errors?limit=${limit}&offset=${offset}`);
export const apiAdminJobs = (limit = 10, offset = 0) =>
  adminJson<Page<AdminJob>>(`/admin/ops/jobs?limit=${limit}&offset=${offset}`);
export const apiAdminJob = (id: string) => adminJson<AdminJob>(`/admin/ops/jobs/${encodeURIComponent(id)}`);
export const apiAdminStartJob = (payload: { kind: AdminJobKind; dry_run: boolean; reason: string; confirm?: string }) =>
  adminJson<AdminJob>("/admin/ops/jobs", { method: "POST", body: JSON.stringify(payload) }, "Could not start the job.");

export function apiAdminAudit(q: { limit: number; offset: number; action?: string; outcome?: string;
                                   correlation_id?: string }): Promise<Page<AuditEventView>> {
  const p = new URLSearchParams({ limit: String(q.limit), offset: String(q.offset) });
  for (const k of ["action", "outcome", "correlation_id"] as const) if (q[k]) p.set(k, q[k] as string);
  return adminJson<Page<AuditEventView>>(`/admin/audit-events?${p}`, {}, "Could not load the audit log.");
}
export const apiAdminVerifyAudit = () =>
  adminJson<AuditIntegrity>("/admin/audit-events/verify", {}, "Could not verify the audit log.");

// ─── Notifications (own account) ─────────────────────────────────────────────

export const apiNotifications = (unreadOnly = false, limit = 20, offset = 0) =>
  adminJson<{ items: AppNotification[]; total: number; unread: number }>(
    `/farmers/me/notifications?unread_only=${unreadOnly}&limit=${limit}&offset=${offset}`, {},
    "Could not load notifications.");
export async function apiMarkNotificationRead(id: number): Promise<void> {
  const res = await farmerFetch(`/farmers/me/notifications/${id}/read`, { method: "POST" });
  if (!res.ok && res.status !== 404) throw await apiError(res, "Could not update the notification.");
}
export const apiMarkAllRead = () =>
  adminJson<{ marked: number }>("/farmers/me/notifications/read-all", { method: "POST" });
export const apiGetNotificationPrefs = () =>
  adminJson<PreferencesResponse>("/farmers/me/notification-preferences", {}, "Could not load settings.");
export const apiUpdateNotificationPrefs = (p: Partial<Pick<NotificationPreferences,
  "in_app" | "email" | "sms" | "consequential_only">> & { sms_consent?: boolean }) =>
  adminJson<PreferencesResponse>("/farmers/me/notification-preferences",
                                 { method: "PUT", body: JSON.stringify(p) }, "Could not save the settings.");
export const apiFollowedSchemes = () =>
  adminJson<{ scheme_id: string; scheme_name: string | null; since: string }[]>("/farmers/me/subscriptions");
export const apiFollowScheme = (schemeId: string) =>
  adminJson<{ following: boolean }>(`/farmers/me/subscriptions/${encodeURIComponent(schemeId)}`,
                                    { method: "PUT" }, "Could not follow the scheme.");
export async function apiUnfollowScheme(schemeId: string): Promise<void> {
  const res = await farmerFetch(`/farmers/me/subscriptions/${encodeURIComponent(schemeId)}`, { method: "DELETE" });
  if (!res.ok && res.status !== 404) throw await apiError(res, "Could not unfollow.");
}
export const apiStartPhoneVerification = (phone: string) =>
  adminJson<{ sent_to: string; expires_in_minutes: number }>("/farmers/me/phone",
    { method: "POST", body: JSON.stringify({ phone }) }, "Could not send the code.");
export const apiConfirmPhone = (code: string) =>
  adminJson<{ phone: string }>("/farmers/me/phone/verify", { method: "POST", body: JSON.stringify({ code }) },
                               "Could not verify the code.");
export async function apiRemovePhone(): Promise<void> {
  const res = await farmerFetch("/farmers/me/phone", { method: "DELETE" });
  if (!res.ok) throw await apiError(res, "Could not remove the number.");
}
export async function apiUnsubscribe(token: string): Promise<string> {
  const res = await fetch(`${API_BASE_URL}/notifications/unsubscribe`, {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ token }) });
  if (!res.ok) throw await apiError(res, "This link is not valid.");
  return (await res.json()).unsubscribed;
}

// ─── Scheme updates (administrators) ─────────────────────────────────────────

export const apiChangeSources = () =>
  adminJson<{ items: { name: string; bytes: number; modified_at: string }[] }>("/admin/scheme-changes/sources");
export const apiDetectChanges = (source: string) =>
  adminJson<{ batch_id: string; new_changes: number; duplicates_skipped: number; warnings: string[];
              invalid_records: { scheme_id: string | null; reason: string }[]; consequential: number }>(
    "/admin/scheme-changes/detect", { method: "POST", body: JSON.stringify({ source }) }, "Detection failed.");
export const apiChangeBatches = () => adminJson<Page<ChangeBatch>>("/admin/scheme-changes/batches?limit=10");
export const apiSchemeChanges = (batchId: string) =>
  adminJson<Page<SchemeChange>>(`/admin/scheme-changes?batch_id=${batchId}&limit=200`);
export const apiReviewChange = (id: number, decision: "APPROVED" | "REJECTED", note: string, confirm: boolean) =>
  adminJson<SchemeChange>(`/admin/scheme-changes/${id}/review`, {
    method: "POST", body: JSON.stringify({ decision, note: note || null, confirm_consequential: confirm }) },
    "Could not save the decision.");
export const apiPublishChanges = (batchId: string, dryRun: boolean, reason: string) =>
  adminJson<AdminJob>("/admin/ops/jobs", { method: "POST", body: JSON.stringify({
    kind: "PUBLISH_CHANGES", batch_id: batchId, dry_run: dryRun, reason,
    ...(dryRun ? {} : { confirm: "PUBLISH_CHANGES" }) }) }, "Could not start publishing.");
export const apiDeliveries = () =>
  adminJson<{ items: Record<string, unknown>[]; total: number; counts: Record<string, number> }>(
    "/admin/notifications/deliveries?limit=20");
export const apiDispatchNow = () =>
  adminJson<{ handled: number }>("/admin/notifications/dispatch", { method: "POST" }, "Dispatch failed.");

export async function apiGetEligibility(
  opts: { status?: EligibilityStatusValue | null; page?: number; pageSize?: number } = {}
): Promise<EligibilityDashboard> {
  const q = new URLSearchParams({ page: String(opts.page ?? 1), page_size: String(opts.pageSize ?? 10) });
  if (opts.status) q.set("status", opts.status);
  const res = await farmerFetch(`/farmers/me/eligibility?${q}`);
  if (!res.ok) throw await apiError(res, "Failed to check eligibility.");
  return res.json();
}

export async function apiGetEligibilityBasis(): Promise<EligibilityBasis> {
  const res = await farmerFetch("/farmers/me/eligibility/basis");
  if (!res.ok) throw await apiError(res, "Failed to check for updates.");
  return res.json();
}

// ─── Human review (docs/HUMAN_REVIEW.md) ─────────────────────────────────────

export function apiReviewCases(q: { status?: ReviewCaseStatus | null; reason?: string | null;
                                    assigned?: "me" | "unassigned" | null; limit: number; offset: number }) {
  const p = new URLSearchParams({ limit: String(q.limit), offset: String(q.offset) });
  if (q.status) p.set("status", q.status);
  if (q.reason) p.set("reason", q.reason);
  if (q.assigned) p.set("assigned", q.assigned);
  return adminJson<{ cases: ReviewCaseSummary[]; total: number; stats: ReviewStats }>(
    `/review-cases?${p}`, {}, "Could not load the review queue.");
}
export const apiReviewCase = (id: string) =>
  adminJson<{ case: ReviewCaseView; history: ReviewEvent[]; access: ReviewAccess; grants?: ReviewGrant[] }>(
    `/review-cases/${encodeURIComponent(id)}`, {},
    "Could not load the case.");
const reviewPost = <T,>(id: string, action: string, body: object, fallback: string) =>
  adminJson<T>(`/review-cases/${encodeURIComponent(id)}/${action}`, { method: "POST", body: JSON.stringify(body) },
    fallback);
export const apiReviewClaim = (id: string, version: number) =>
  reviewPost<{ case: ReviewCaseView }>(id, "claim", { expected_version: version }, "Could not take the case.");
export const apiReviewRelease = (id: string, version: number) =>
  reviewPost<{ case: ReviewCaseView }>(id, "release", { expected_version: version }, "Could not release the case.");
export const apiReviewAssign = (id: string, version: number, reviewerEmail: string) =>
  reviewPost<{ case: ReviewCaseView }>(id, "assign", { expected_version: version, reviewer_email: reviewerEmail },
    "Could not assign the case.");
export const apiReviewComment = (id: string, text: string) =>
  reviewPost<{ comment: ReviewEvent }>(id, "comments", { text }, "Could not add the comment.");
export const apiReviewRequestVerification = (id: string, version: number, note: string) =>
  reviewPost<{ case: ReviewCaseView }>(id, "resolve", { action: "REQUEST_INFORMATION", note, expected_version: version },
    "Could not request verification.");
export const apiReviewDecide = (id: string, version: number, action: ReviewDecisionAction, note: string,
                                dataCorrectionNeeded = false) =>
  reviewPost<{ case: ReviewCaseView }>(id, "resolve", { action, note, expected_version: version,
    data_correction_needed: dataCorrectionNeeded }, "Could not save the decision.");
export const apiReviewDismiss = (id: string, version: number, note: string) =>
  reviewPost<{ case: ReviewCaseView }>(id, "dismiss", { note, expected_version: version }, "Could not dismiss the case.");
export const apiMyReviewCases = () =>
  adminJson<{ items: FarmerReviewCase[]; open: number }>("/farmers/me/review-cases", {},
    "Could not load the checks on your results.");

/** Confirm the password before a sensitive action (the server answers 403 REAUTH_REQUIRED otherwise). */
export async function apiReauthenticate(password: string): Promise<void> {
  const res = await fetch(`${API_BASE_URL}/auth/reauthenticate`, {
    method: "POST", credentials: "include", headers: withCsrf({ "Content-Type": "application/json" }),
    body: JSON.stringify({ password }),
  });
  if (!res.ok) throw await apiError(res, "Password confirmation failed.");
}

export const isReauthRequired = (err: unknown) =>
  err instanceof ApiError && err.status === 403 && err.code === "REAUTH_REQUIRED";

export const apiReviewGrant = (id: string, reviewerEmail: string, hours: number) =>
  reviewPost<{ grant: { reviewer: string; expires_at: string } }>(id, "grants",
    { reviewer_email: reviewerEmail, hours }, "Could not grant access.");
export async function apiReviewRevokeGrant(id: string, reviewerEmail: string): Promise<void> {
  const res = await farmerFetch(`/review-cases/${encodeURIComponent(id)}/grants/revoke`,
    { method: "POST", body: JSON.stringify({ reviewer_email: reviewerEmail }) });
  if (!res.ok) throw await apiError(res, "Could not revoke access.");
}

export const apiAdminReviewers = () =>
  adminJson<{ items: AdminUser[]; total: number }>("/admin/users?role=REVIEWER&limit=100&offset=0", {},
    "Could not load reviewer accounts.");
export const apiAdminSetReviewerApproval = (farmerId: string, approved: boolean) =>
  adminJson<AdminUser>(`/admin/users/${encodeURIComponent(farmerId)}/reviewer-approval`,
    { method: "PATCH", body: JSON.stringify({ approved }) }, "Could not change reviewer approval.");


// ─── Privacy and data settings (docs/PRIVACY.md) ─────────────────────────────

export async function apiPrivacyPolicy(): Promise<PrivacyPolicy> {
  const res = await fetch(`${API_BASE_URL}/privacy/policy`);
  if (!res.ok) throw await apiError(res, "Could not load the privacy information.");
  return res.json();
}
export const apiMyData = () => adminJson<MyDataSummary>("/farmers/me/data", {}, "Could not load your data.");

/** Downloads everything stored about you as a JSON file (needs a recent sign-in). */
export async function apiExportMyData(): Promise<void> {
  const res = await farmerFetch("/farmers/me/data/export");
  if (!res.ok) throw await apiError(res, "Could not export your data.");
  const blob = await res.blob();
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = "schemesetu-my-data.json";
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}

const deleteOwn = (path: string, fallback: string) =>
  adminJson<{ deleted: Record<string, number> }>(path, { method: "DELETE" }, fallback);
export const apiDeleteMyProfile = () => deleteOwn("/farmers/me/profile", "Could not delete your profile.");
export const apiDeleteAllSavedSchemes = () => deleteOwn("/farmers/me/saved-schemes", "Could not delete saved schemes.");
export const apiDeleteNotificationData = () =>
  deleteOwn("/farmers/me/notification-data", "Could not delete notification data.");
export const apiDeleteAccount = (password: string, confirm: string) =>
  adminJson<{ deleted: boolean; summary: Record<string, number>; still_kept: string[] }>(
    "/farmers/me/delete-account", { method: "POST", body: JSON.stringify({ password, confirm }) },
    "Could not delete your account.");
