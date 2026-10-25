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
}

export interface TokenResponse {
  access_token: string;
  refresh_token: string;
  token_type: string;
  expires_in: number;
  farmer_id: string;
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

export interface SavedFarmerProfile {
  farmer_id: string;
  full_name?: string | null;
  email: string;
  state?: string | null;
  district?: string | null;
  land_size_acres?: number | null;
  primary_crop?: string | null;
  other_crops?: string[] | null;
  farming_type?: string | null;
  age?: number | null;
  gender?: string | null;
  category?: string | null;
  annual_income?: number | null;
  has_aadhaar?: boolean | null;
  occupation?: string | null;
  consent_given: boolean;
  consent_given_at?: string | null;
  profile_completeness: number;
}

export interface ProfileUpdatePayload {
  state?: string;
  district?: string;
  land_size_acres?: number;
  primary_crop?: string;
  other_crops?: string[];
  farming_type?: string;
  age?: number;
  gender?: string;
  category?: string;
  annual_income?: number;
  has_aadhaar?: boolean;
  occupation?: string;
  consent_given: boolean;
}

export interface SavedScheme {
  id: number;
  scheme_id: string;
  scheme_name: string;
  eligibility_status?: string | null;
  notes?: string | null;
  saved_at?: string | null;
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
