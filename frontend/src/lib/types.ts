/**
 * Centralized TypeScript type definitions — Phase 4.
 *
 * Field names are aligned exactly with backend API response fields.
 * Single source of truth — no duplicated interfaces across components.
 */

export interface FarmerProfile {
  state?: string | null;
  district?: string | null;
  land_size_acres?: number | null;
  primary_crop?: string | null;
  other_crops?: string[] | null;
  farming_type?: string | null;
  annual_income?: number | null;
  category?: string | null;
  gender?: string | null;
  has_aadhaar?: boolean | null;
  occupation?: string | null;
  age?: number | null;
  residence?: string | null;
}

export interface SchemeSource {
  name?: string;
  url?: string;
  type?: string;
}

export type EligibilityStatus =
  | "ELIGIBLE"
  | "NOT_ELIGIBLE"
  | "NEEDS_MORE_INFORMATION"
  | "UNVERIFIABLE";

export interface EligibilityCriteria {
  field: string;
  operator?: string;
  user_value?: string | number | boolean | null;
  required_value?: string | number | boolean | string[] | null;
  source_text?: string;
}

export interface Scheme {
  scheme_id?: string;
  name: string;
  description?: string;
  benefit_summary?: string;
  eligibility_summary?: string;
  documents?: string[];
  application_steps?: string[];
  official_url?: string;
  sources?: SchemeSource[];
  retrieval_sources?: string[];
  matched_fields?: string[];
  graph_evidence?: string[];
  // Phase 5 eligibility fields
  eligibility_status?: EligibilityStatus;
  matched_criteria?: EligibilityCriteria[];
  failed_criteria?: EligibilityCriteria[];
  missing_criteria?: EligibilityCriteria[];
  missing_information?: string[];
  profile_match_score?: number;
  rank?: number;
  rank_reasons?: string[];
  evidence_summary?: string;
  /** Query-time check against official websites (docs/LIVE_VERIFICATION.md). */
  freshness?: SchemeFreshness | null;
  /** Eligible schemes vs relevant alternatives (docs/RECOMMENDATIONS.md). Eligibility itself is eligibility_status. */
  recommendation_section?: RecommendationSection;
  recommendation_status?: RecommendationStatus;
  status_text?: string;
  relevance?: SchemeRelevance;
  conditions_to_verify?: string[];
  mismatches?: string[];
  application_url?: string | null;
  last_verified_at?: string | null;
  applicable_states?: string[];
  level?: string | null;
  // Legacy fields (backward compatibility)
  scheme_name?: string;
  benefit?: string;
  xai_explanation?: string;
  source?: string;
  // Legacy field names (pre-Phase 7); the backend now sends documents / official_url
  required_documents?: string[];
  source_url?: string;
}

export interface Message {
  sender: "user" | "agent";
  text: string;
}

export interface ErrorDetail {
  code: string;
  message: string;
  request_id?: string;
}

export interface RetrievalMetadata {
  db_latency_ms?: number;
  graph_latency_ms?: number;
  web_latency_ms?: number;
  total_retrieval_ms?: number;
  retrieval_success?: Record<string, boolean>;
  candidate_count?: number;
  conflict_count?: number;
}

export type ChatStatus =
  | "asking_question"
  | "schemes_found"
  | "scheme_details"
  | "no_results"
  | "partial_results"
  | "clarification_required"
  | "error";

export interface ChatResponse {
  status: ChatStatus;
  reply?: string;
  current_profile?: FarmerProfile;
  schemes?: Scheme[];
  user_transcript?: string;
  error?: ErrorDetail;
  request_id?: string;
  retrieval_metadata?: RetrievalMetadata;
  review?: ReviewStatus;
  thread_id?: string;
  profile_saved?: boolean;
  profile_save_error?: string;
  live_check?: LiveCheckReport | null;
  /** Language of the reply, detected from the farmer's message (e.g. "hi"). */
  language?: string | null;
  recommendation_summary?: { eligible: number; alternatives: number; not_matching: number; stated_needs: string[] } | null;
}

export type RecommendationSection = "ELIGIBLE" | "ALTERNATIVE" | "NOT_MATCHING";
export type RecommendationStatus = "CONFIRMED_ELIGIBLE" | "ELIGIBILITY_UNCONFIRMED" | "ADDITIONAL_INFORMATION_REQUIRED"
  | "KNOWN_MISMATCH" | "SCHEME_INFORMATION_INCOMPLETE";

export interface SchemeRelevance {
  tier?: 1 | 2 | 3;
  score?: number;
  rank?: number;
  reasons?: string[];
  categories?: string[];
  similar_to?: string[];
  matched_needs?: string[];
}

/** LIVE_VERIFIED: read on an official site during this request. CACHED: an earlier read, re-used.
 *  SOURCE_REACHABLE / NOT_VERIFIED / STORED: the details shown are stored records. */
export type FreshnessStatus = "LIVE_VERIFIED" | "SOURCE_REACHABLE" | "CACHED" | "NOT_VERIFIED" | "STORED";

export interface LiveSource {
  url: string;
  host: string;
  category?: string;
  label?: string;
  method: "direct" | "tavily" | null;
  status: string;
  http_status?: number | null;
  retrieved_at?: string | null;
  checked_at?: string | null;
  from_cache?: boolean;
  scheme_id?: string | null;
  fields_found?: string[];
  found_by?: string[];
  reason?: string;
}

export interface LiveField {
  status: "CONFIRMED" | "CONFLICT" | "LIVE_ONLY" | "STORED_ONLY" | "EVIDENCE_ONLY";
  live?: unknown;
  stored?: unknown;
  evidence?: string | null;
  source_url?: string;
}

export interface SchemeFreshness {
  status: FreshnessStatus;
  label: string;
  checked_at?: string | null;
  retrieved_at?: string | null;
  stored_last_verified?: string | null;
  sources: LiveSource[];
  verified_fields: string[];
  fields: Record<string, LiveField>;
  conflicts: { field: string; stored: unknown; live: unknown; source_url?: string; evidence?: string | null }[];
  new_discovery?: boolean;
}

export interface LiveCheckReport {
  performed: boolean;
  started_at?: string;
  finished_at?: string;
  duration_ms?: number;
  discovery?: { status: "OK" | "PARTIAL" | "FAILED" | "NOT_CONFIGURED"; official_results: number;
    duplicates_merged: number; non_official_results_ignored: number };
  sources: LiveSource[];
  sources_accessed: number;
  sources_cached: number;
  sources_failed: number;
  sources_not_checked?: number;
  hosts_accessed: string[];
  new_discoveries: { name: string; url: string }[];
  coverage_note?: string;
  warnings: string[];
}

/** Safe human-review status shown to the user (no reviewer data). */
export interface ReviewStatus {
  needs_review: boolean;
  reason?: string | null;
  case_id?: string | null;
}

export interface TTSResponse {
  audio_base64?: string;
  error?: ErrorDetail;
  request_id?: string;
}

export interface HealthResponse {
  status: string;
  db_connected: boolean;
  graph_available?: boolean;
  environment?: string;
  version: string;
}

// ─── Auth types ───────────────────────────────────────────────────────────────

export interface AuthUser {
  farmer_id: string;
  email: string;
  full_name?: string | null;
  is_verified?: boolean;
  /** FARMER / REVIEWER / ADMIN — display only; every permission is checked by the backend. */
  role?: "FARMER" | "REVIEWER" | "ADMIN" | string;
}

/** Returned by /auth/login and /auth/session. The session itself is an HttpOnly cookie. */
export interface SessionResponse {
  user: AuthUser;
  csrf_token: string;
  session_expires_at: string;
}

export interface RegisterPayload {
  email: string;
  password: string;
  full_name?: string;
  phone?: string;
}

export interface LoginPayload {
  email: string;
  password: string;
}

// ─── Farmer profile & dashboard types ─────────────────────────────────────────

export type LandUnit = "acre" | "hectare" | "guntha" | "cent";
export type IncomeRange = "below_1_lakh" | "1_to_2.5_lakh" | "2.5_to_5_lakh" | "5_to_10_lakh" | "above_10_lakh";

/** Saved profile. null = unknown / not given (never "no"). */
export interface SavedFarmerProfile {
  farmer_id: string;
  full_name?: string | null;
  email: string;
  state?: string | null;
  district?: string | null;
  land_size?: number | null;          // as entered, in land_unit
  land_unit?: LandUnit | null;
  land_size_acres?: number | null;    // converted (used by the eligibility engine)
  primary_crop?: string | null;
  other_crops?: string[] | null;
  farming_type?: string | null;
  occupation?: string | null;
  age?: number | null;
  gender?: string | null;
  category?: string | null;
  income_range?: IncomeRange | null;
  residence?: "rural" | "urban" | null;
  consent_given: boolean;
  consent_given_at?: string | null;
  profile_completeness: number;
  version: number;
  updated_at?: string | null;
}

/**
 * Partial update: a field left out keeps its value; null clears it to unknown.
 * Aadhaar status / number and exact income are not collected.
 */
export interface ProfileUpdatePayload {
  state?: string | null;
  district?: string | null;
  land_size?: number | null;
  land_unit?: LandUnit | null;
  primary_crop?: string | null;
  other_crops?: string[] | null;
  farming_type?: string | null;
  occupation?: string | null;
  age?: number | null;
  gender?: string | null;
  category?: string | null;
  income_range?: IncomeRange | null;
  residence?: "rural" | "urban" | null;
  consent_given: boolean;
  expected_version?: number;
}

export interface SavedScheme {
  id: number;
  scheme_id: string;
  scheme_name: string;
  eligibility_status?: string | null;
  notes?: string | null;
  saved_at?: string | null;
}

// ─── Saved schemes + application checklists (docs/SAVED_SCHEMES.md) ──────────
// Progress is reported by the farmer; no government tracking system is connected.

export type ChecklistCategory =
  | "DOCUMENT" | "PREPARATION" | "APPLICATION" | "SUBMISSION" | "ACKNOWLEDGEMENT" | "MILESTONE";

export interface ChecklistItem {
  id: number;
  key: string;
  category: ChecklistCategory;
  source: "SCHEME" | "USER";
  label: string;
  detail: string | null;
  completed: boolean;
  completed_at: string | null;
  note: string | null;
  current: boolean;            // false: the scheme no longer lists it (kept, not counted)
  added_in_update: boolean;
}

export interface SavedSchemeProgress {
  completed: number;
  total: number;
  stage: "NOT_STARTED" | "PREPARING" | "SUBMITTED" | "ACKNOWLEDGED";
  reported_by: "FARMER";
}

export interface SchemeUpdateNotice {
  changed_at: string | null;
  previous_version: string | null;
  current_version: string;
  added: string[];
  removed: string[];
}

export interface SavedSchemeSummary {
  id: number;
  scheme_id: string;
  scheme_name: string;
  eligibility_status: string | null;
  notes: string | null;
  saved_at: string | null;
  application_reference: string | null;
  scheme_available: boolean;
  scheme_status: string | null;
  scheme_version: string | null;
  saved_scheme_version: string | null;
  scheme_data_version: string | null;
  official_url: string | null;
  application_url: string | null;
  progress: SavedSchemeProgress;
  update_notice: SchemeUpdateNotice | null;
  progress_source: "USER_REPORTED";
  official_tracking: false;
}

export interface SavedSchemeDetail extends SavedSchemeSummary {
  checklist: ChecklistItem[];
  progress_notice: string;
}

export interface SaveSchemeResult extends SavedSchemeDetail {
  created: boolean;            // false: it was already saved (nothing changed)
}

// ─── Administrator operations (docs/ADMIN_OPERATIONS.md) ─────────────────────

export interface Page<T> { items: T[]; total: number; limit: number; offset: number }

/** Each section is "OK" with its fields, or "UNAVAILABLE" with a message. */
export type Section<T> = ({ status: "OK" } & T) | { status: "UNAVAILABLE"; message: string };

export interface AdminJob {
  id: string;
  kind: AdminJobKind;
  status: "QUEUED" | "RUNNING" | "SUCCEEDED" | "FAILED";
  dry_run: boolean;
  reason: string;
  requested_by: string;
  correlation_id: string | null;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
  result: Record<string, unknown> | null;
  error: string | null;
}
export type AdminJobKind = "IMPORT_CORPUS" | "REBUILD_GRAPH" | "PUBLISH_CHANGES";

export interface OpsError {
  id: number; at: string; level: string; logger: string; message: string;
  exception_type: string | null; correlation_id: string | null;
}

export interface AdminOverview {
  generated_at: string;
  system: Section<{
    version: string; environment: string; uptime_seconds: number;
    database: { connected: boolean; migration: string | null; expected_migration: string };
    knowledge_graph_loaded: boolean; external_services: Record<string, boolean>; warnings: string[];
  }>;
  corpus: Section<{
    file: { version: string | null; schemes: number; generated_at: string | null };
    database: { schemes: number; rules: number; documents: number; needs_review: number;
                possible_duplicates: number; without_rules: number; by_status: Record<string, number>;
                corpus_version: { version: string; imported_at: string | null } | null };
    in_step: boolean;
  }>;
  ingestion: Section<{
    active_job: AdminJob | null; recent_jobs: AdminJob[]; jobs_total: number;
    recent_import_runs: { id: number; status: string; started_at: string; records_read: number;
                          errors: number; corpus_version: string | null }[];
  }>;
  graph: Section<{
    loaded: boolean; in_sync: boolean; nodes?: number; edges?: number; graph_corpus_version?: string;
    db_corpus_version?: string | null; generated_at?: string | null; message?: string;
    schemes_missing_from_graph?: string[]; schemes_only_in_graph?: string[];
  }>;
  reviews: Section<{
    stats: Record<string, number>; open_by_reason: Record<string, number>;
    oldest_open_created_at: string | null; with_source_conflicts: number;
  }>;
  errors: Section<{ buffered: number; last_24h: number; latest: OpsError[]; note: string }>;
}

export interface ValidationCheck {
  name: string; status: "PASS" | "WARN" | "FAIL" | "ERROR"; summary: string; items: unknown[];
}
export interface ValidationReport { overall: ValidationCheck["status"]; checked_at: string; checks: ValidationCheck[] }

export interface ConflictReport {
  source_conflicts: { case_id: string; case_status: string; created_at: string; scheme_id: string | null;
                      field: string | null; values: Record<string, string> | string; resolution: string }[];
  source_conflicts_total: number;
  rule_conflicts: { scheme_id: string; field: string; type: string; message: string }[] | null;
  flagged_schemes: { scheme_id: string; name: string; status: string; needs_review: boolean;
                     possible_duplicate: boolean; review_notes: string | null }[] | null;
  database_status?: string;
}

export interface AuditEventView {
  id: number; occurred_at: string; actor_label: string; actor_role: string | null; action: string;
  target_type: string | null; target_id: string | null; details: Record<string, unknown> | null;
  outcome: "SUCCESS" | "FAILURE" | "DENIED"; correlation_id: string | null;
}
export interface AuditIntegrity {
  valid: boolean; checked: number; first_broken_id: number | null; reason: string | null; verified_at: string;
}

// ─── Scheme updates & notifications (docs/SCHEME_UPDATES.md) ─────────────────

export interface AppNotification {
  id: number; scheme_id: string; title: string; body: string; consequential: boolean;
  created_at: string; read: boolean;
}
export interface NotificationPreferences {
  in_app: boolean; email: boolean; sms: boolean; consequential_only: boolean;
  sms_consent_at: string | null; sms_consent_version: string | null; sms_opted_out_at: string | null;
}
export interface NotificationChannels {
  email_configured: boolean; sms_available: boolean;
  phone: string | null; phone_verified: boolean; sms_consent_text: string; sms_consent_version: string;
}
export interface PreferencesResponse { preferences: NotificationPreferences; channels: NotificationChannels }

export interface SchemeChange {
  id: number; batch_id: string; scheme_id: string; scheme_name: string; category: string;
  consequential: boolean; summary: string; before: unknown; after: unknown;
  provenance: { source_file: string; source_sha256: string; records: Record<string, unknown>[] };
  status: "PENDING" | "APPROVED" | "REJECTED" | "PUBLISHED" | "DISCARDED";
  detected_at: string; reviewed_by: string | null; reviewed_at: string | null; review_note: string | null;
}
export interface ChangeBatch {
  id: string; source_name: string; base_version: string | null; candidate_count: number; status: string;
  detected_by: string; detected_at: string; published_version: string | null;
  warnings: string[]; invalid_records: { scheme_id: string | null; reason: string }[];
  pending: number; approved: number; rejected: number; published: number; total: number;
}

export interface SearchHistoryEntry {
  id: number;
  query: string;
  results_count: number;
  language: string;
  searched_at?: string | null;
}

export interface AccountInfo {
  farmer_id: string;
  email: string;
  full_name?: string | null;
  phone?: string | null;
  is_active: boolean;
  is_verified: boolean;
  created_at?: string | null;
  last_login_at?: string | null;
}

export interface DashboardData {
  account: AccountInfo;
  profile: SavedFarmerProfile | null;
  missing_fields: string[];
  profile_completeness: number;
  saved_schemes: SavedScheme[];
  recent_searches: SearchHistoryEntry[];
}

// ─── Dashboard eligibility (deterministic engine, saved profile) ──────────────

export type EligibilityStatusValue =
  | "ELIGIBLE" | "NOT_ELIGIBLE" | "NEEDS_MORE_INFORMATION" | "UNVERIFIABLE";

export interface EligibilityBasis {
  profile_version: number | null;
  profile_updated_at: string | null;
  data_fingerprint: string;
  engine_version: string;
  scheme_count: number;
  rule_count: number;
}

export interface Criterion {
  field: string;
  user_value?: unknown;
  required_value?: unknown;
  source_text?: string | null;
}

export interface DashboardSchemeResult {
  scheme_id: string;
  scheme_name: string;
  status: EligibilityStatusValue;
  rank: number;
  reasons: string[];
  matched_criteria: Criterion[];
  failed_criteria: Criterion[];
  missing_criteria: Criterion[];
  explanation: string | null;
  status_note: string | null;
  official_url: string | null;
  saved: boolean;
  saved_status: string | null;
  status_changed_since_saved: boolean;
  under_review?: boolean;          // an open human-review case from your own search
}

export interface MissingDetail {
  field: string;
  label: string;
  scheme_count: number;
  schemes: string[];
}

export interface ProfileConflict {
  fields: string[];
  message: string;
}

export interface SavedStatusChange {
  scheme_id: string;
  scheme_name: string;
  saved_status: string | null;
  current_status: EligibilityStatusValue;
}

export interface EligibilityDashboard {
  basis: EligibilityBasis;
  computed_at: string;
  has_profile: boolean;
  counts: Record<EligibilityStatusValue, number>;
  status_filter: EligibilityStatusValue | null;
  total: number;
  page: number;
  page_size: number;
  items: DashboardSchemeResult[];
  missing_details: MissingDetail[];
  conflicts: ProfileConflict[];
  saved_status_changes: SavedStatusChange[];
}

// ─── Human review (docs/HUMAN_REVIEW.md) ──────────────────────────────────────

export type ReviewCaseStatus = "PENDING" | "IN_REVIEW" | "RESOLVED" | "DISMISSED";
export type ReviewDecisionAction = "APPROVE" | "REJECT" | "MARK_UNVERIFIABLE" | "RESOLVE";

export interface ReviewCaseView {
  case_id: string;
  session_id: string;
  reason: string;
  status: ReviewCaseStatus;
  query: string;
  profile_snapshot: Record<string, unknown>;
  scheme_ids: string[];
  schemes: { scheme_id: string; name: string; official_url: string | null }[];
  eligibility_results: { scheme_id: string; status: string; missing_information?: string[]; summary?: string | null }[];
  evidence: { scheme_id: string; field: string | null; text: string | null; url: string | null }[];
  rule_conflicts: Record<string, unknown>[];
  source_conflicts: { scheme_id?: string; field?: string; values?: Record<string, unknown>; sources?: string[] }[];
  failed_channels: string[];
  assignee: string | null;
  assigned_at: string | null;
  awaiting_verification: boolean;
  decision: ReviewDecisionAction | null;
  data_correction_needed: boolean;
  reviewer_id: string | null;
  reviewer_action: string | null;
  reviewer_note: string | null;
  reviewed_at: string | null;
  version: number;
  created_at: string;
  updated_at: string;
  farmer_follows_case: boolean;
}

export interface ReviewEvent {
  event: string;
  actor: string;
  from_status: string | null;
  to_status: string | null;
  note: string | null;
  created_at: string;
}

export interface ReviewStats {
  total: number;
  pending: number;
  in_review: number;
  resolved: number;
  dismissed: number;
  awaiting_verification: number;
}

export interface FarmerReviewCase {
  case_id: string;
  schemes: { scheme_id: string; name: string }[];
  reason: string;
  reason_text: string;
  status: ReviewCaseStatus;
  open: boolean;
  outcome_text: string;
  opened_at: string;
  updated_at: string;
}

// ─── Reviewer access policy (docs/HUMAN_REVIEW.md) ────────────────────────────

/** How you may see a case: full detail when assigned / granted (admins: always); queue = summary only. */
export type ReviewAccess = "admin" | "assigned" | "granted" | "queue" | "key";

export interface ReviewCaseSummary {
  case_id: string;
  reason: string;
  status: ReviewCaseStatus;
  schemes: { scheme_id: string; name: string }[];
  assignee: string | null;
  awaiting_verification: boolean;
  decision: ReviewDecisionAction | null;
  version: number;
  created_at: string;
  updated_at: string;
  access: ReviewAccess | null;
}

export interface ReviewGrant {
  reviewer: string | null;
  granted_by: string;
  granted_at: string;
  expires_at: string;
  revoked_at: string | null;
}

export interface AdminUser {
  farmer_id: string;
  email: string;
  full_name: string | null;
  role: string;
  is_active: boolean;
  is_verified: boolean;
  locked: boolean;
  reviewer_approved: boolean;
  created_at: string | null;
  last_login_at: string | null;
}


// ─── Privacy and data settings (docs/PRIVACY.md) ─────────────────────────────

export interface PrivacyField {
  field: string;
  label: string;
  required: boolean;
  why: string;
  stored?: string;
  used_for_eligibility?: boolean;
  shared_with: string[];
  shared_note: string;
}

export interface PrivacyPolicy {
  account_fields: PrivacyField[];
  profile_fields: PrivacyField[];
  not_collected: string[];
  chat_note: string;
  required_note: string;
  records: { record: string; label: string; what: string; when: string; retention: string; you_can: string }[];
  processors: { id: string; name: string; purpose: string; receives: string; when: string; configured: boolean }[];
  processor_note: string;
  exceptions: { what: string; why: string; how_long: string }[];
  retention_days: Record<string, number>;
}

export interface MyDataSummary {
  has_profile: boolean;
  consent_given: boolean;
  consent_given_at: string | null;
  profile_fields_filled: string[];
  counts: Record<string, number>;
  has_phone: boolean;
  errors: Record<string, string>;
}

// ─── Chat history (docs/CHAT_HISTORY.md) ──────────────────────────────────────

export interface ConversationSummary {
  thread_id: string;
  title: string | null;
  language: string | null;
  message_count: number;
  created_at: string | null;
  last_activity_at: string | null;
}

export interface ConversationMessage {
  role: "USER" | "ASSISTANT" | string;
  content: string;
  language: string | null;
  input_mode: "text" | "voice" | null;
  status: string | null;
  schemes: { scheme_id?: string; name?: string; recommendation_section?: string; eligibility_status?: string }[] | null;
  created_at: string | null;
}

export interface Conversation extends ConversationSummary {
  messages: ConversationMessage[];
}
