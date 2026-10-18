/**
 * Centralized TypeScript type definitions — Phase 4.
 *
 * Field names are aligned exactly with backend API response fields.
 * Single source of truth — no duplicated interfaces across components.
 */

export interface FarmerProfile {
  state?: string;
  district?: string;
  land_size_acres?: number;
  primary_crop?: string;
  annual_income?: number;
  category?: string;
  gender?: string;
  has_aadhaar?: boolean;
  occupation?: string;
  age?: number;
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
