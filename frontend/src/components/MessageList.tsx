"use client";

import React, { useEffect, useRef } from "react";
import type { Message } from "@/lib/types";
import { Sparkles } from "lucide-react";

interface MessageListProps {
  messages: Message[];
  loading: boolean;
}

/**
 * Render **bold** as <strong> and *italic* as <em> without using innerHTML (replies may
 * contain web-derived text, so nothing is ever parsed as HTML). Leftover markdown heading
 * marks (#) at line starts are dropped.
 */
function renderText(text: string): React.ReactNode[] {
  const clean = text.replace(/^#{1,6}\s+/gm, "");
  return clean.split(/(\*\*[^*]+\*\*|\*[^*\s][^*\n]*?\*)/g).map((part, i) => {
    if (part.startsWith("**") && part.endsWith("**") && part.length > 4)
      return <strong key={i}>{part.slice(2, -2)}</strong>;
    if (part.startsWith("*") && part.endsWith("*") && part.length > 2)
      return <em key={i}>{part.slice(1, -1)}</em>;
    return <React.Fragment key={i}>{part}</React.Fragment>;
  });
}

export default function MessageList({ messages, loading }: MessageListProps) {
  const listRef = useRef<HTMLDivElement | null>(null);

  // Keep the newest message in view (the latest reply used to be cut off).
  // Only the message list scrolls — never the whole page.
  useEffect(() => {
    const el = listRef.current;
    if (el) el.scrollTo({ top: el.scrollHeight, behavior: "smooth" });
  }, [messages.length, loading]);

  return (
    <div
      ref={listRef}
      className="flex-1 p-4 overflow-y-auto space-y-4"
      role="log"
      aria-live="polite"
      aria-label="Conversation messages"
    >
      {messages.map((msg, idx) => (
        <div
          key={idx}
          className={`flex ${msg.sender === "user" ? "justify-end" : "justify-start"}`}
        >
          <div
            className={`max-w-[85%] rounded-2xl px-4 py-3 text-sm leading-relaxed whitespace-pre-line break-words ${
              msg.sender === "user"
                ? "bg-emerald-600 text-white rounded-br-none"
                : "bg-slate-100 text-slate-800 border border-slate-200 rounded-bl-none"
            }`}
          >
            <span className="sr-only">{msg.sender === "user" ? "You said: " : "Assistant: "}</span>
            {renderText(msg.text.trim())}
          </div>
        </div>
      ))}
      {loading && (
        <div className="flex justify-start">
          <div className="bg-slate-100 border border-slate-200 rounded-2xl px-4 py-3 text-sm text-slate-500 flex items-center space-x-2">
            <Sparkles className="h-4 w-4 text-emerald-600 animate-spin" aria-hidden="true" />
            <span>Checking schemes and eligibility…</span>
          </div>
        </div>
      )}
    </div>
  );
}
