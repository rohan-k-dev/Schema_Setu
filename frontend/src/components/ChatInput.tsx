"use client";

import React from "react";
import { Send, Mic, MicOff, Loader2 } from "lucide-react";

/**
 * Voice state machine (§24):
 * IDLE → RECORDING → UPLOADING → TRANSCRIBING → PROCESSING → IDLE
 */
export type VoiceState =
  | "idle"
  | "recording"
  | "uploading"
  | "transcribing"
  | "processing"
  | "error";

interface ChatInputProps {
  input: string;
  setInput: (val: string) => void;
  onSend: () => void;
  onVoiceToggle: () => void;
  isRecording: boolean;
  loading: boolean;
  voiceState?: VoiceState;
}

/** Voice status label for screen readers and visual feedback (§49). */
function getVoiceLabel(state: VoiceState): string {
  switch (state) {
    case "recording":
      return "Recording… Tap to stop";
    case "uploading":
      return "Uploading audio…";
    case "transcribing":
      return "Transcribing…";
    case "processing":
      return "Processing…";
    case "error":
      return "Voice error. Try again.";
    default:
      return "Press to speak";
  }
}

export default function ChatInput({
  input,
  setInput,
  onSend,
  onVoiceToggle,
  isRecording,
  loading,
  voiceState = "idle",
}: ChatInputProps) {
  const isVoiceBusy =
    voiceState === "uploading" ||
    voiceState === "transcribing" ||
    voiceState === "processing";
  const isDisabled = loading || isVoiceBusy;

  return (
    <div className="p-3 sm:p-4 border-t border-slate-200 bg-white">
      {/* Voice status indicator (§49) */}
      {voiceState !== "idle" && voiceState !== "error" && (
        <div
          className="flex items-center gap-2 mb-2 px-2 py-1 text-xs text-slate-500"
          role="status"
          aria-live="polite"
        >
          {isRecording && (
            <span className="h-2 w-2 rounded-full bg-red-500 animate-pulse" />
          )}
          {isVoiceBusy && <Loader2 className="h-3 w-3 animate-spin" />}
          <span>{getVoiceLabel(voiceState)}</span>
        </div>
      )}

      <div className="flex items-center space-x-2">
        {/* Voice button — 44px minimum touch target (§42) */}
        <button
          onClick={onVoiceToggle}
          disabled={isDisabled && !isRecording}
          className={`p-3 rounded-xl flex items-center justify-center transition-all min-w-[44px] min-h-[44px] ${
            isRecording
              ? "bg-red-500 text-white animate-pulse shadow-[0_0_15px_rgba(239,68,68,0.5)]"
              : isVoiceBusy
              ? "bg-amber-100 text-amber-600 cursor-wait"
              : "bg-slate-100 text-slate-600 hover:bg-slate-200 disabled:opacity-50"
          }`}
          aria-label={getVoiceLabel(voiceState)}
          title={getVoiceLabel(voiceState)}
          id="voice-toggle-btn"
        >
          {isRecording ? (
            <MicOff className="h-5 w-5" />
          ) : isVoiceBusy ? (
            <Loader2 className="h-5 w-5 animate-spin" />
          ) : (
            <Mic className="h-5 w-5" />
          )}
        </button>

        {/* Text input — always available even during voice (§107) */}
        <input
          type="text"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && !isDisabled && onSend()}
          placeholder="e.g., I am from Karnataka, growing maize on 2.5 acres..."
          className="flex-1 bg-slate-100 border-0 focus:ring-2 focus:ring-emerald-600 rounded-xl px-4 py-3 text-sm text-slate-800 placeholder-slate-400 outline-none min-h-[44px]"
          disabled={isDisabled}
          aria-label="Type your message"
          id="chat-text-input"
        />

        {/* Send button — 44px minimum touch target (§42) */}
        <button
          onClick={onSend}
          disabled={isDisabled || !input.trim()}
          className="bg-emerald-600 hover:bg-emerald-700 disabled:opacity-50 text-white p-3 rounded-xl flex items-center justify-center transition-colors min-w-[44px] min-h-[44px]"
          aria-label="Send message"
          id="send-message-btn"
        >
          <Send className="h-5 w-5" />
        </button>
      </div>
    </div>
  );
}
