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
  TokenResponse,
  RegisterPayload,
  LoginPayload,
  SavedFarmerProfile,
  ProfileUpdatePayload,
  SavedScheme,
  SearchHistoryEntry,
  DashboardData,
} from "./types";

const API_BASE_URL =
  process.env.NEXT_PUBLIC_API_BASE_URL || "http://localhost:8000";

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
  accessToken?: string | null,
  consentToSaveProfile: boolean = false
): Promise<ChatResponse> {
  const headers: Record<string, string> = { "Content-Type": "application/json" };
  if (accessToken) headers.Authorization = `Bearer ${accessToken}`;
  const response = await fetch(`${API_BASE_URL}/chat`, {
    method: "POST",
    headers,
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
  accessToken?: string | null,
  consentToSaveProfile: boolean = false
): Promise<ChatResponse> {
  const formData = new FormData();
  formData.append("file", audioBlob, filename);
  formData.append("thread_id", threadId);
  formData.append("language", language);
  formData.append("consent_to_save_profile", String(consentToSaveProfile));

  const headers: Record<string, string> = {};
  if (accessToken) headers.Authorization = `Bearer ${accessToken}`;
  const response = await fetch(`${API_BASE_URL}/voice`, {
    method: "POST",
    headers,
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

function authHeaders(accessToken: string) {
  return {
    "Content-Type": "application/json",
    Authorization: `Bearer ${accessToken}`,
  };
}

export async function apiRegister(payload: RegisterPayload): Promise<TokenResponse> {
  const res = await fetch(`${API_BASE_URL}/auth/register`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  const data = await res.json();
  if (!res.ok) throw new Error(data?.error?.message || data?.detail?.message || "Registration failed.");
  return data as TokenResponse;
}

export async function apiLogin(payload: LoginPayload): Promise<TokenResponse> {
  const res = await fetch(`${API_BASE_URL}/auth/login`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  const data = await res.json();
  if (!res.ok) throw new Error(data?.error?.message || data?.detail?.message || "Login failed.");
  return data as TokenResponse;
}

export async function apiRefreshToken(refreshToken: string): Promise<TokenResponse> {
  const res = await fetch(`${API_BASE_URL}/auth/refresh`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ refresh_token: refreshToken }),
  });
  const data = await res.json();
  if (!res.ok) throw new Error(data?.error?.message || "Token refresh failed.");
  return data as TokenResponse;
}

export async function apiLogout(refreshToken: string): Promise<void> {
  await fetch(`${API_BASE_URL}/auth/logout`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ refresh_token: refreshToken }),
  });
}

export async function apiForgotPassword(email: string): Promise<void> {
  await fetch(`${API_BASE_URL}/auth/forgot-password`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email }),
  });
}

export async function apiResetPassword(token: string, newPassword: string): Promise<void> {
  const res = await fetch(`${API_BASE_URL}/auth/reset-password`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ token, new_password: newPassword }),
  });
  if (!res.ok) {
    const data = await res.json();
    throw new Error(data?.error?.message || "Password reset failed.");
  }
}

// ─── Farmer / Profile API ─────────────────────────────────────────────────────

export async function apiGetDashboard(accessToken: string): Promise<DashboardData> {
  const res = await fetch(`${API_BASE_URL}/farmers/me/dashboard`, {
    headers: authHeaders(accessToken),
  });
  if (!res.ok) throw new Error("Failed to load dashboard.");
  return res.json();
}

export async function apiGetProfile(accessToken: string): Promise<SavedFarmerProfile | null> {
  const res = await fetch(`${API_BASE_URL}/farmers/me/profile`, {
    headers: authHeaders(accessToken),
  });
  if (res.status === 404) return null;
  if (!res.ok) throw new Error("Failed to load profile.");
  return res.json();
}

export async function apiUpdateProfile(
  accessToken: string,
  payload: ProfileUpdatePayload
): Promise<SavedFarmerProfile> {
  const res = await fetch(`${API_BASE_URL}/farmers/me/profile`, {
    method: "PUT",
    headers: authHeaders(accessToken),
    body: JSON.stringify(payload),
  });
  const data = await res.json();
  if (!res.ok) throw new Error(data?.detail?.message || data?.error?.message || "Profile update failed.");
  return data as SavedFarmerProfile;
}

export async function apiGetSavedSchemes(accessToken: string): Promise<SavedScheme[]> {
  const res = await fetch(`${API_BASE_URL}/farmers/me/saved-schemes`, {
    headers: authHeaders(accessToken),
  });
  if (!res.ok) return [];
  return res.json();
}

export async function apiSaveScheme(
  accessToken: string,
  payload: { scheme_id: string; scheme_name: string; eligibility_status?: string; notes?: string }
): Promise<SavedScheme> {
  const res = await fetch(`${API_BASE_URL}/farmers/me/saved-schemes`, {
    method: "POST",
    headers: authHeaders(accessToken),
    body: JSON.stringify(payload),
  });
  if (!res.ok) throw new Error("Failed to save scheme.");
  return res.json();
}

export async function apiDeleteSavedScheme(
  accessToken: string,
  schemeId: string
): Promise<void> {
  await fetch(`${API_BASE_URL}/farmers/me/saved-schemes/${schemeId}`, {
    method: "DELETE",
    headers: authHeaders(accessToken),
  });
}

export async function apiGetSearchHistory(
  accessToken: string,
  limit = 10
): Promise<SearchHistoryEntry[]> {
  const res = await fetch(
    `${API_BASE_URL}/farmers/me/search-history?limit=${limit}`,
    { headers: authHeaders(accessToken) }
  );
  if (!res.ok) return [];
  return res.json();
}
