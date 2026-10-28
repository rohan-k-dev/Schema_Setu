"use client";

import React, { useState, useRef, useCallback, useEffect } from "react";
import Link from "next/link";

// Centralized types and API client
import type { ChatResponse, FarmerProfile, LiveCheckReport, Scheme, Message } from "@/lib/types";
import { sendChat, sendVoice, generateTTS, apiGetConversation, apiGetProfile, apiGetSavedSchemes, apiSaveScheme } from "@/lib/api";
import { useAuth } from "@/lib/AuthContext";

// Extracted components
import StatusIndicator from "@/components/StatusIndicator";
import MessageList from "@/components/MessageList";
import ChatInput, { type VoiceState } from "@/components/ChatInput";
import ProfilePanel from "@/components/ProfilePanel";
import SchemeList from "@/components/SchemeList";
import LanguageSelector from "@/components/LanguageSelector";

/**
 * One conversation session per browser tab (Phase 7 BUG-031).
 * The backend replaces the placeholder "default_session" with a fresh ID on every
 * request, so a constant here silently started a new session on every message.
 */
function newSessionId(): string {
  if (typeof crypto !== "undefined" && "randomUUID" in crypto) {
    return crypto.randomUUID();
  }
  return `session-${Date.now()}-${Math.random().toString(36).slice(2)}`;
}

const INITIAL_MESSAGE: Message = {
  sender: "agent",
  text: "Namaste! I am your Kisan Assistant. Tell me your state, how much land you have and the crop you grow, and I will check which government schemes match.",
};

export default function Home() {
  const [messages, setMessages] = useState<Message[]>([INITIAL_MESSAGE]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [isRecording, setIsRecording] = useState(false);
  const [voiceState, setVoiceState] = useState<VoiceState>("idle");
  const [profile, setProfile] = useState<FarmerProfile | null>(null);
  const [schemes, setSchemes] = useState<Scheme[]>([]);
  const [liveCheck, setLiveCheck] = useState<LiveCheckReport | null>(null);
  const [language, setLanguage] = useState("en");
  const [failedMessage, setFailedMessage] = useState<string | null>(null);
  const [demoMode, setDemoMode] = useState(false);
  const [profileConsentGiven, setProfileConsentGiven] = useState(false);
  const [consentToSaveProfile, setConsentToSaveProfile] = useState(false);
  const [profileLoading, setProfileLoading] = useState(false);

  const [isSpeaking, setIsSpeaking] = useState(false);

  const { user, isAuthenticated, isLoading: authLoading, logout } = useAuth();
  const signedInId = user?.farmer_id ?? null;
  const profileFetchedForRef = useRef<string | null>(null);

  // Auto-sync saved farmer profile if user is logged in
  useEffect(() => {
    if (!isAuthenticated || !signedInId) {
      profileFetchedForRef.current = null;
      setProfileConsentGiven(false);
      setConsentToSaveProfile(false);
      return;
    }
    if (profileFetchedForRef.current === signedInId) return;

    profileFetchedForRef.current = signedInId;
    setProfileLoading(true);
    apiGetProfile()
      .then((saved) => {
        setProfileConsentGiven(saved?.consent_given ?? false);
        if (saved) {
          setProfile({
            state: saved.state,
            district: saved.district,
            land_size_acres: saved.land_size_acres,
            primary_crop: saved.primary_crop,
            other_crops: saved.other_crops,
            farming_type: saved.farming_type,
            age: saved.age,
            gender: saved.gender,
            category: saved.category,
            occupation: saved.occupation,
            residence: saved.residence,
          });
        }
      })
      .catch((error: unknown) => {
        console.error("Saved farmer profile could not be loaded:", error);
      })
      .finally(() => setProfileLoading(false));
  }, [isAuthenticated, signedInId]);

  // Saved schemes (signed in): which cards show "Saved", and saving from a card
  const [savedIds, setSavedIds] = useState<Set<string>>(new Set());
  const [savingId, setSavingId] = useState<string | null>(null);
  const [saveError, setSaveError] = useState<{ schemeId: string; message: string } | null>(null);

  useEffect(() => {
    if (!isAuthenticated || !signedInId) {
      setSavedIds(new Set());
      return;
    }
    apiGetSavedSchemes()
      .then((list) => setSavedIds(new Set(list.map((s) => s.scheme_id))))
      .catch(() => { /* cards just show "Save"; saving again is harmless (no duplicates) */ });
  }, [isAuthenticated, signedInId]);

  const handleSaveScheme = useCallback(async (scheme: Scheme) => {
    const id = scheme.scheme_id;
    if (!id) return;
    setSavingId(id);
    setSaveError(null);
    try {
      await apiSaveScheme({ scheme_id: id, eligibility_status: scheme.eligibility_status ?? null });
      setSavedIds((prev) => new Set(prev).add(id));
    } catch (err) {
      setSaveError({ schemeId: id, message: err instanceof Error ? err.message : "Failed to save scheme." });
    } finally {
      setSavingId(null);
    }
  }, []);

  // Conversation session for this tab
  const threadIdRef = useRef<string>("");
  if (!threadIdRef.current) threadIdRef.current = newSessionId();

  // Continue a saved conversation: /?thread=<id> from Chat history (docs/CHAT_HISTORY.md)
  useEffect(() => {
    if (!isAuthenticated || typeof window === "undefined") return;
    const threadId = new URLSearchParams(window.location.search).get("thread");
    if (!threadId) return;
    apiGetConversation(threadId)
      .then((conv) => {
        threadIdRef.current = conv.thread_id;
        if (conv.language) setLanguage(conv.language);
        setMessages([INITIAL_MESSAGE, ...conv.messages.map((m) => ({
          sender: (m.role === "USER" ? "user" : "agent") as "user" | "agent",
          text: m.role === "USER" && m.input_mode === "voice" ? `🎙️ "${m.content}"` : m.content,
        }))]);
      })
      .catch(() => {
        setMessages((prev) => [...prev, { sender: "agent", text: "That conversation couldn't be opened. You can start a new one here." }]);
      })
      .finally(() => window.history.replaceState(null, "", "/"));
  }, [isAuthenticated]);

  // Currently playing TTS audio (so it can be stopped and released)
  const audioRef = useRef<HTMLAudioElement | null>(null);

  // Screen readers need <html lang> to follow the selected language (§162)
  useEffect(() => {
    document.documentElement.lang = language;
  }, [language]);

  const stopAudio = useCallback(() => {
    if (audioRef.current) {
      audioRef.current.pause();
      audioRef.current.src = "";
      audioRef.current = null;
    }
    setIsSpeaking(false);
  }, []);

  // Release audio when the page unmounts
  useEffect(() => stopAudio, [stopAudio]);

  // Refs for audio recording
  const mediaRecorderRef = useRef<MediaRecorder | null>(null);
  const audioChunksRef = useRef<BlobPart[]>([]);
  const isProcessingRef = useRef(false);

  /**
   * Language change handler (§12).
   * Profile data is NOT affected by language switch (§161).
   */
  const handleLanguageChange = useCallback((newLang: string) => {
    setLanguage(newLang);
    // Only presentation language changes, NOT profile data (§161)
  }, []);

  /**
   * Play TTS audio response in the user's selected language.
   * Errors are caught silently — TTS is best-effort (§33).
   */
  const playAudioResponse = useCallback(async (textToSpeak: string, replyLanguage?: string) => {
    try {
      // Speak in the reply's language (detected from what the farmer said or typed), else the picker's
      const lang = replyLanguage || language;
      const langCode = `${lang}-IN`;
      const data = await generateTTS(textToSpeak, langCode);
      if (data.audio_base64) {
        stopAudio();
        const audio = new Audio(`data:audio/wav;base64,${data.audio_base64}`);
        audioRef.current = audio;
        audio.onended = () => {
          if (audioRef.current === audio) stopAudio();
        };
        setIsSpeaking(true);
        audio.play().catch((err) => {
          console.warn("Audio playback failed:", err);
          stopAudio();
        });
      }
    } catch (error) {
      console.warn("TTS playback failed (best-effort):", error);
    }
  }, [language, stopAudio]);

  /**
   * Process the chat/voice response data from the backend.
   * Every status shows the assistant's reply; schemes are updated whenever
   * present (partial_results, scheme_details, ... used to show nothing).
   */
  const handleResponseData = useCallback(
    (data: ChatResponse) => {
      // Follow the language the farmer is using: the picker switches to it (shown + used next time)
      if (data.language) setLanguage(data.language);
      const currentProfile = data.current_profile;
      if (currentProfile) {
        setProfile((previous) => {
          const updates = Object.fromEntries(
            Object.entries(currentProfile).filter(([, value]) => value != null)
          );
          return { ...(previous ?? {}), ...updates };
        });
      }
      if (data.profile_saved) {
        setProfileConsentGiven(true);
        setConsentToSaveProfile(false);
      }
      if (data.schemes && data.schemes.length > 0) {
        setSchemes(data.schemes);
        setLiveCheck(data.live_check ?? null);
      } else if (data.status === "no_results") {
        setSchemes([]);
        setLiveCheck(null);
      }

      const fallback =
        data.status === "error"
          ? "Sorry, I had trouble processing that. Could you try again?"
          : data.status === "no_results"
          ? "I could not find matching schemes in the available sources."
          : "";
      const reply = data.reply || fallback;
      if (reply) {
        setMessages((prev) => [...prev, { sender: "agent", text: reply }]);
        if (data.status !== "error") playAudioResponse(reply, data.language ?? undefined);
      }
      if (data.review?.needs_review && isAuthenticated) {
        setMessages((prev) => [...prev, { sender: "agent", text:
          "You can follow this check under \"Checks by our team\" on your dashboard. We'll show the outcome there." }]);
      }
      if (data.profile_save_error) {
        setMessages((prev) => [...prev, { sender: "agent", text: data.profile_save_error! }]);
      }
    },
    [playAudioResponse, isAuthenticated]
  );

  /**
   * Send text message to the backend with language (§5 — same pipeline).
   */
  const sendText = async (userMsg: string) => {
    setFailedMessage(null);
    setLoading(true);
    try {
      const data = await sendChat(
        userMsg,
        threadIdRef.current,
        language,
        profileConsentGiven || consentToSaveProfile
      );
      handleResponseData(data);
    } catch (error) {
      console.error("API Error:", error);
      setFailedMessage(userMsg);
      setMessages((prev) => [
        ...prev,
        { sender: "agent", text: "I could not reach the server. Check your connection and press Retry." },
      ]);
    } finally {
      setLoading(false);
    }
  };

  const handleSend = async () => {
    if (!input.trim() || loading || profileLoading) return;
    const userMsg = input;
    setInput("");
    setMessages((prev) => [...prev, { sender: "user", text: userMsg }]);
    await sendText(userMsg);
  };

  const handleRetry = async () => {
    if (failedMessage && !loading) await sendText(failedMessage);
  };

  /**
   * Start a fresh conversation: new session ID, cleared profile and results.
   * The previous session stays isolated on the server and is evicted later.
   */
  const handleNewConversation = () => {
    stopAudio();
    threadIdRef.current = newSessionId();
    setMessages([INITIAL_MESSAGE]);
    setProfile(null);
    setSchemes([]);
    setLiveCheck(null);
    setFailedMessage(null);
    setInput("");
  };

  /**
   * Send recorded audio to the backend with language (§19).
   */
  const sendAudioToBackend = async (audioBlob: Blob, mimeType: string) => {
    if (isProcessingRef.current) return;
    isProcessingRef.current = true;

    setLoading(true);
    setVoiceState("uploading");
    setMessages((prev) => [...prev, { sender: "user", text: "🎙️ (Voice Audio Sent)" }]);

    const extension = mimeType.includes("webm") ? ".webm" : mimeType.includes("ogg") ? ".ogg" : ".wav";
    const filename = `recording${extension}`;

    try {
      setVoiceState("transcribing");
      const data = await sendVoice(
        audioBlob,
        filename,
        threadIdRef.current,
        language,
        profileConsentGiven || consentToSaveProfile
      );

      // Update the voice message with the actual transcript
      if (data.user_transcript) {
        setMessages((prev) => {
          const newMsgs = [...prev];
          const lastIdx = newMsgs.length - 1;
          if (lastIdx >= 0 && newMsgs[lastIdx].sender === "user") {
            newMsgs[lastIdx] = { ...newMsgs[lastIdx], text: `🎙️ "${data.user_transcript}"` };
          }
          return newMsgs;
        });
      }

      setVoiceState("processing");
      handleResponseData(data);
    } catch (error) {
      console.error("Voice API Error:", error);
      setVoiceState("error");
      setMessages((prev) => [
        ...prev,
        { sender: "agent", text: "Failed to process voice input. Please try again or use text." },
      ]);
    } finally {
      setLoading(false);
      setVoiceState("idle");
      isProcessingRef.current = false;
    }
  };

  /**
   * Toggle microphone recording (§20).
   * Uses browser's actual MIME type — never labels WebM as WAV.
   * Graceful fallback if MediaRecorder not supported (§116, §117).
   */
  const handleVoiceToggle = async () => {
    if (loading || profileLoading) return;

    if (isRecording) {
      // Stop Recording
      mediaRecorderRef.current?.stop();
      setIsRecording(false);
      setVoiceState("uploading");
    } else {
      // Start Recording
      try {
        // Check MediaRecorder support (§116)
        if (!navigator.mediaDevices || !window.MediaRecorder) {
          setMessages((prev) => [
            ...prev,
            { sender: "agent", text: "Your browser doesn't support voice recording. Please use text input instead." },
          ]);
          return;
        }

        stopAudio(); // never record while the assistant is speaking
        const stream = await navigator.mediaDevices.getUserMedia({ audio: true });

        // Detect the actual supported MIME type (§117)
        const mimeType = MediaRecorder.isTypeSupported("audio/webm;codecs=opus")
          ? "audio/webm;codecs=opus"
          : MediaRecorder.isTypeSupported("audio/webm")
          ? "audio/webm"
          : MediaRecorder.isTypeSupported("audio/ogg;codecs=opus")
          ? "audio/ogg;codecs=opus"
          : "";

        const options: MediaRecorderOptions = mimeType ? { mimeType } : {};
        const mediaRecorder = new MediaRecorder(stream, options);
        const actualMimeType = mediaRecorder.mimeType;

        mediaRecorderRef.current = mediaRecorder;
        audioChunksRef.current = [];

        mediaRecorder.ondataavailable = (event) => {
          if (event.data.size > 0) {
            audioChunksRef.current.push(event.data);
          }
        };

        mediaRecorder.onstop = async () => {
          const audioBlob = new Blob(audioChunksRef.current, { type: actualMimeType });
          // Release mic (§106 resource cleanup)
          stream.getTracks().forEach((track) => track.stop());

          if (audioBlob.size > 0) {
            await sendAudioToBackend(audioBlob, actualMimeType);
          }
        };

        mediaRecorder.start();
        setIsRecording(true);
        setVoiceState("recording");
      } catch (err) {
        console.error("Microphone access denied:", err);
        setVoiceState("error");
        // §160 — mic denied, text remains available
        setMessages((prev) => [
          ...prev,
          { sender: "agent", text: "Microphone access is required for voice input. Please allow microphone access or use text input." },
        ]);
        setTimeout(() => setVoiceState("idle"), 2000);
      }
    }
  };

  return (
    <div className="min-h-screen bg-slate-50 flex flex-col font-sans lg:h-dvh lg:min-h-0 lg:overflow-hidden">
      {/* Header with language selector */}
      <header className="bg-gradient-to-r from-emerald-700 to-emerald-600 text-white px-4 py-3 shadow-md">
        <div className="max-w-7xl w-full mx-auto flex items-center justify-between">
          <div className="flex items-center gap-3">
            <h1 className="text-lg sm:text-xl font-bold tracking-tight">
              🌾 SchemeSetu
            </h1>
            <span className="hidden sm:inline text-xs text-emerald-200 font-medium">
              AI-Powered Scheme Discovery
            </span>
          </div>
          <div className="flex items-center gap-2 sm:gap-3 flex-wrap justify-end">
            {isSpeaking && (
              <button
                onClick={stopAudio}
                className="px-3 min-h-[44px] rounded-lg bg-white/15 hover:bg-white/25 text-white text-xs font-semibold focus:outline-none focus-visible:ring-2 focus-visible:ring-white"
                aria-label="Stop reading the answer aloud"
              >
                Stop audio
              </button>
            )}
            <LanguageSelector
              selectedLanguage={language}
              onLanguageChange={handleLanguageChange}
            />
            <button
              onClick={handleNewConversation}
              className="px-3 min-h-[44px] rounded-lg bg-white/10 hover:bg-white/20 text-white text-xs font-semibold focus:outline-none focus-visible:ring-2 focus-visible:ring-white"
              aria-label="Start a new conversation"
            >
              New chat
            </button>
            <StatusIndicator onDemoMode={setDemoMode} />

            {/* Farmer Auth Navigation */}
            {isAuthenticated ? (
              <div className="flex items-center gap-1.5 sm:gap-2 border-l border-emerald-500/40 pl-2 sm:pl-3">
                <Link
                  href="/dashboard"
                  className="px-3 min-h-[44px] inline-flex items-center rounded-lg bg-white text-emerald-800 hover:bg-emerald-50 text-xs font-bold shadow-sm transition-all focus:outline-none focus-visible:ring-2 focus-visible:ring-white"
                  title="Personalized Dashboard"
                >
                  Dashboard
                </Link>
                <Link
                  href="/profile"
                  className="hidden md:inline-flex px-3 min-h-[44px] items-center rounded-lg bg-emerald-800 hover:bg-emerald-900 text-white text-xs font-semibold transition-all focus:outline-none focus-visible:ring-2 focus-visible:ring-white"
                  title="Saved Farmer Profile"
                >
                  Profile
                </Link>
                <button
                  onClick={logout}
                  className="px-2 min-h-[44px] text-xs text-emerald-200 hover:text-white hover:underline focus:outline-none"
                  aria-label="Sign out"
                >
                  Logout
                </button>
              </div>
            ) : (
              <div className="border-l border-emerald-500/40 pl-2 sm:pl-3">
                <Link
                  href="/auth"
                  className="px-3.5 min-h-[44px] inline-flex items-center rounded-lg bg-white text-emerald-800 hover:bg-emerald-50 text-xs font-bold shadow-sm transition-all focus:outline-none focus-visible:ring-2 focus-visible:ring-white"
                >
                  Sign In
                </Link>
              </div>
            )}
          </div>
        </div>
      </header>

      {/* Main Layout — responsive (§115) */}
      {demoMode && (
        <div className="bg-amber-100 text-amber-900 text-xs text-center px-4 py-2" role="note">
          Demo mode: scheme data, eligibility and explanations are real; speech, translation and
          language understanding are simulated for a fixed demo script, and live web search is off.
        </div>
      )}

      <main className="flex-1 max-w-7xl w-full mx-auto p-3 sm:p-4 md:p-6 grid grid-cols-1 lg:grid-cols-3 gap-4 sm:gap-6 lg:min-h-0 lg:grid-rows-1">
        {/* Left: Chat & Voice Interaction */}
        <div
          className="lg:col-span-2 bg-white rounded-xl shadow-sm border border-slate-200 flex flex-col overflow-hidden h-[600px] sm:h-[700px] lg:h-auto lg:min-h-0"
          role="region"
          aria-label="Chat conversation"
        >
          <div className="p-3 sm:p-4 bg-slate-100 border-b border-slate-200 font-semibold text-slate-700 flex items-center justify-between">
            <span className="text-sm">Kisan Recommendation Assistant</span>
            <span className="text-[10px] sm:text-xs text-slate-500">
              Multilingual Voice & Text
            </span>
          </div>

          {/* Messages */}
          <MessageList messages={messages} loading={loading} />

          {/* Input — always usable (§107) */}
          {failedMessage && !loading && (
            <div className="px-4 pb-2">
              <button
                onClick={handleRetry}
                className="w-full min-h-[44px] rounded-lg border border-amber-300 bg-amber-50 text-amber-900 text-sm font-medium hover:bg-amber-100 focus:outline-none focus-visible:ring-2 focus-visible:ring-amber-500"
              >
                Retry sending: “{failedMessage.length > 40 ? failedMessage.slice(0, 40) + "…" : failedMessage}”
              </button>
            </div>
          )}

          <ChatInput
            input={input}
            setInput={setInput}
            onSend={handleSend}
            onVoiceToggle={handleVoiceToggle}
            isRecording={isRecording}
            loading={loading || profileLoading}
            voiceState={voiceState}
          />
        </div>

        {/* Right: Profile & Schemes */}
        <div className="space-y-4 sm:space-y-6 flex flex-col lg:h-auto lg:min-h-0 overflow-y-auto overscroll-contain pr-1">
          {isAuthenticated && (
            <div className="bg-emerald-50 border border-emerald-200 rounded-xl p-3 flex items-center justify-between text-xs">
              <span className="text-emerald-900 font-medium truncate">
                🌾 {user?.full_name || "Farmer"} (Account Linked)
              </span>
              <div className="flex items-center gap-2 flex-shrink-0">
                <Link
                  href="/history"
                  className="text-emerald-700 hover:text-emerald-900 font-bold hover:underline"
                >
                  Chat history
                </Link>
                <Link
                  href="/dashboard"
                  className="text-emerald-700 hover:text-emerald-900 font-bold hover:underline"
                >
                  Dashboard →
                </Link>
              </div>
            </div>
          )}
          {isAuthenticated && !authLoading && !profileLoading && !profileConsentGiven && (
            <label className="flex items-start gap-2 rounded-xl border border-slate-200 bg-white p-3 text-xs text-slate-600">
              <input
                id="consent-to-save-profile"
                type="checkbox"
                checked={consentToSaveProfile}
                onChange={(event) => setConsentToSaveProfile(event.target.checked)}
                className="mt-0.5 accent-emerald-600"
              />
              <span>
                Save details I share in chat to my farmer profile. I can change or remove them from
                the Profile page.
              </span>
            </label>
          )}
          <ProfilePanel profile={profile} />
          <SchemeList
            schemes={schemes}
            liveCheck={liveCheck}
            save={isAuthenticated ? { savedIds, savingId, error: saveError, onSave: handleSaveScheme } : undefined}
          />
        </div>
      </main>

      {/* Connection status (§110) */}
      <footer className="text-center text-[10px] text-slate-400 py-2">
        SchemeSetu v1.0.0
      </footer>
    </div>
  );
}