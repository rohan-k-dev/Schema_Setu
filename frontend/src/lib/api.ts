/**
 * Centralized API client — Phase 6.
 *
 * All backend requests go through this module.
 * Language parameter added to chat/voice for multilingual support (§12).
 */

import type { ChatResponse, TTSResponse, HealthResponse } from "./types";

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
  language: string = "en"
): Promise<ChatResponse> {
  const response = await fetch(`${API_BASE_URL}/chat`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ message, thread_id: threadId, language }),
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
  language: string = "en"
): Promise<ChatResponse> {
  const formData = new FormData();
  formData.append("file", audioBlob, filename);
  formData.append("thread_id", threadId);
  formData.append("language", language);

  const response = await fetch(`${API_BASE_URL}/voice`, {
    method: "POST",
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
