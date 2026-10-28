"use client";

/**
 * Chat history (docs/CHAT_HISTORY.md).
 *
 * Route: /history. A signed-in farmer's saved conversations, most recent first: open one to read it
 * (questions, replies, the schemes that were shown), continue it in the chat, delete it or all of them,
 * and choose whether new conversations are saved. Everything is scoped to the session on the server.
 */

import React, { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useAuth } from "@/lib/AuthContext";
import {
  apiChatHistorySettings, apiClearConversations, apiDeleteConversation, apiGetConversation, apiListConversations,
  ApiError,
} from "@/lib/api";
import type { Conversation, ConversationSummary } from "@/lib/types";

const PAGE = 20;
const LANGUAGE_NAME: Record<string, string> = {
  en: "English", hi: "हिन्दी", kn: "ಕನ್ನಡ", ta: "தமிழ்", te: "తెలుగు", mr: "मराठी", bn: "বাংলা", gu: "ગુજરાતી",
  od: "ଓଡ଼ିଆ", pa: "ਪੰਜਾਬੀ", ml: "മലയാളം",
};

function when(iso: string | null): string {
  if (!iso) return "";
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });
}

function message(e: unknown, fallback: string): string {
  return e instanceof ApiError ? e.message : fallback;
}

export default function HistoryPage() {
  const router = useRouter();
  const { isAuthenticated, isLoading } = useAuth();
  const [items, setItems] = useState<ConversationSummary[]>([]);
  const [total, setTotal] = useState(0);
  const [open, setOpen] = useState<Conversation | null>(null);
  const [enabled, setEnabled] = useState<boolean | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [confirming, setConfirming] = useState<string | null>(null);

  const load = useCallback(async (offset: number) => {
    setLoading(true);
    setError(null);
    try {
      const page = await apiListConversations(PAGE, offset);
      setItems((prev) => (offset === 0 ? page.items : [...prev, ...page.items]));
      setTotal(page.total);
    } catch (e) {
      setError(message(e, "Couldn't load your chat history."));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (!isAuthenticated) return;
    load(0);
    apiChatHistorySettings().then((s) => setEnabled(s.enabled)).catch(() => setEnabled(null));
  }, [isAuthenticated, load]);

  const openConversation = async (threadId: string) => {
    setError(null);
    try {
      setOpen(await apiGetConversation(threadId));
    } catch (e) {
      setError(message(e, "Couldn't open this conversation."));
    }
  };

  const remove = async (threadId: string) => {
    try {
      await apiDeleteConversation(threadId);
      setItems((prev) => prev.filter((c) => c.thread_id !== threadId));
      setTotal((t) => Math.max(0, t - 1));
      if (open?.thread_id === threadId) setOpen(null);
      setNotice("Conversation deleted.");
    } catch (e) {
      setError(message(e, "Couldn't delete the conversation."));
    } finally {
      setConfirming(null);
    }
  };

  const removeAll = async () => {
    try {
      const n = await apiClearConversations();
      setItems([]);
      setTotal(0);
      setOpen(null);
      setNotice(`${n} conversation(s) deleted.`);
    } catch (e) {
      setError(message(e, "Couldn't delete your chat history."));
    } finally {
      setConfirming(null);
    }
  };

  const toggle = async (value: boolean) => {
    const previous = enabled;
    setEnabled(value);                                   // respond at once; undone if the server refuses
    try {
      setEnabled((await apiChatHistorySettings(value)).enabled);
      setNotice(value ? "New conversations will be saved." : "New conversations won't be saved. Existing ones stay "
        + "until you delete them.");
    } catch (e) {
      setEnabled(previous);
      setError(message(e, "Couldn't change the setting."));
    }
  };

  return (
    <div className="dash-page">
      <header className="dash-header">
        <div className="dash-header-inner">
          <div className="dash-header-brand">
            <span className="dash-header-icon">🌾</span>
            <span className="dash-header-name">SchemeSetu</span>
          </div>
          <nav className="dash-header-nav">
            <button onClick={() => router.push("/")} className="dash-nav-btn min-h-[44px]">💬 AI Chat</button>
            <button onClick={() => router.push("/dashboard")} className="dash-nav-btn min-h-[44px]">🏠 Dashboard</button>
            <button onClick={() => router.push("/privacy")} className="dash-nav-btn min-h-[44px]">🛡️ Privacy &amp; data</button>
          </nav>
        </div>
      </header>

      <main className="dash-main">
        <h1 className="text-xl font-bold text-slate-800 mb-1">Chat history</h1>
        <p className="text-sm text-slate-600 mb-4">
          Your conversations with the assistant, saved to your account. Open one to read it or continue where you left off.
        </p>

        {isLoading ? (
          <p className="text-sm text-slate-500">Loading…</p>
        ) : !isAuthenticated ? (
          <div className="rounded-xl border border-slate-200 bg-white p-4 text-sm text-slate-700">
            <Link href="/auth" className="text-emerald-700 font-semibold underline">Sign in</Link> to see your saved
            conversations. Conversations without signing in are not saved.
          </div>
        ) : (
          <>
            <div className="flex flex-wrap items-center justify-between gap-3 mb-4 rounded-xl border border-slate-200 bg-white p-3">
              <label className="flex items-center gap-2 text-sm text-slate-700">
                <input type="checkbox" className="accent-emerald-600 h-4 w-4" checked={enabled ?? false}
                       disabled={enabled === null} onChange={(e) => toggle(e.target.checked)} />
                Save my conversations
              </label>
              {items.length > 0 && (confirming === "all" ? (
                <span className="flex gap-2">
                  <button onClick={removeAll} className="min-h-[40px] px-3 rounded-lg bg-red-600 text-white text-sm font-semibold">
                    Yes, delete all
                  </button>
                  <button onClick={() => setConfirming(null)} className="min-h-[40px] px-3 rounded-lg border text-sm">Cancel</button>
                </span>
              ) : (
                <button onClick={() => setConfirming("all")}
                        className="min-h-[40px] px-3 rounded-lg border border-red-200 text-red-700 text-sm font-semibold hover:bg-red-50">
                  Delete all
                </button>
              ))}
            </div>

            {error && <p role="alert" className="mb-3 rounded-lg bg-red-50 border border-red-200 p-2 text-sm text-red-800">{error}</p>}
            {notice && <p role="status" className="mb-3 rounded-lg bg-emerald-50 border border-emerald-200 p-2 text-sm text-emerald-900">{notice}</p>}

            <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.4fr)]">
              <section aria-label="Your conversations" className="space-y-2">
                {!loading && items.length === 0 && (
                  <div className="rounded-xl border-2 border-dashed border-slate-200 p-6 text-center text-sm text-slate-500" data-testid="history-empty">
                    No saved conversations yet. <Link href="/" className="text-emerald-700 underline">Start a chat</Link>.
                  </div>
                )}
                {items.map((c) => (
                  <div key={c.thread_id} data-testid="conversation"
                       className={`rounded-xl border bg-white p-3 ${open?.thread_id === c.thread_id ? "border-emerald-400" : "border-slate-200"}`}>
                    <button onClick={() => openConversation(c.thread_id)} className="w-full text-left min-h-[44px]">
                      <span className="block font-semibold text-slate-800 text-sm truncate">{c.title || "Conversation"}</span>
                      <span className="block text-xs text-slate-500">
                        {when(c.last_activity_at)} · {c.message_count} messages
                        {c.language ? ` · ${LANGUAGE_NAME[c.language] ?? c.language}` : ""}
                      </span>
                    </button>
                    <div className="flex gap-2 mt-1">
                      <button onClick={() => router.push(`/?thread=${encodeURIComponent(c.thread_id)}`)}
                              className="text-xs font-semibold text-emerald-700 hover:underline min-h-[32px]">
                        Continue this chat →
                      </button>
                      {confirming === c.thread_id ? (
                        <>
                          <button onClick={() => remove(c.thread_id)} className="text-xs font-semibold text-red-700 min-h-[32px]">Yes, delete</button>
                          <button onClick={() => setConfirming(null)} className="text-xs text-slate-600 min-h-[32px]">Cancel</button>
                        </>
                      ) : (
                        <button onClick={() => setConfirming(c.thread_id)} className="text-xs text-red-700 hover:underline min-h-[32px]">Delete</button>
                      )}
                    </div>
                  </div>
                ))}
                {items.length < total && (
                  <button onClick={() => load(items.length)} disabled={loading}
                          className="w-full min-h-[44px] rounded-lg border border-slate-300 text-sm font-semibold text-slate-700 hover:bg-slate-50">
                    {loading ? "Loading…" : `Load more (${total - items.length} more)`}
                  </button>
                )}
              </section>

              <section aria-label="Conversation" className="rounded-xl border border-slate-200 bg-white p-4 min-h-[200px]" data-testid="conversation-view">
                {!open ? (
                  <p className="text-sm text-slate-500">Select a conversation to read it.</p>
                ) : (
                  <>
                    <div className="flex flex-wrap items-start justify-between gap-2 mb-3">
                      <div>
                        <h2 className="font-bold text-slate-800">{open.title || "Conversation"}</h2>
                        <p className="text-xs text-slate-500">Started {when(open.created_at)}</p>
                      </div>
                      <button onClick={() => router.push(`/?thread=${encodeURIComponent(open.thread_id)}`)}
                              className="min-h-[40px] px-3 rounded-lg bg-emerald-600 text-white text-sm font-semibold hover:bg-emerald-700">
                        Continue this chat
                      </button>
                    </div>
                    <ol className="space-y-3">
                      {open.messages.map((m, i) => (
                        <li key={i} className={m.role === "USER" ? "flex justify-end" : "flex justify-start"}>
                          <div className={`max-w-[85%] rounded-2xl px-3 py-2 text-sm whitespace-pre-wrap ${
                            m.role === "USER" ? "bg-emerald-600 text-white" : "bg-slate-100 text-slate-800"}`}>
                            <span className="sr-only">{m.role === "USER" ? "You:" : "Assistant:"}</span>
                            {m.role === "USER" && m.input_mode === "voice" && <span aria-label="voice">🎙️ </span>}
                            {m.content}
                            {m.schemes && m.schemes.length > 0 && (
                              <span className="block mt-2 text-xs text-slate-600">
                                Schemes shown: {m.schemes.slice(0, 8).map((s) => s.name || s.scheme_id).join(", ")}
                                {m.schemes.length > 8 ? ` and ${m.schemes.length - 8} more` : ""}
                              </span>
                            )}
                            <span className={`block mt-1 text-[10px] ${m.role === "USER" ? "text-emerald-100" : "text-slate-400"}`}>
                              {when(m.created_at)}
                            </span>
                          </div>
                        </li>
                      ))}
                    </ol>
                  </>
                )}
              </section>
            </div>
          </>
        )}
      </main>
    </div>
  );
}
