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
    <div className="history-page">
      <header className="history-header">
        <div className="history-header-inner">
          <Link href="/" className="history-brand" aria-label="SchemeSetu home">
            <span className="history-brand-icon">🌾</span>
            <span>SchemeSetu</span>
          </Link>
          <nav className="history-nav" aria-label="Main navigation">
            <button onClick={() => router.push("/")} className="history-nav-btn">💬 AI Chat</button>
            <button onClick={() => router.push("/dashboard")} className="history-nav-btn">🏠 Dashboard</button>
            <button onClick={() => router.push("/privacy")} className="history-nav-btn">🛡️ Privacy &amp; data</button>
          </nav>
        </div>
      </header>

      <main className="history-main">
        <div className="history-heading">
          <span className="history-eyebrow">YOUR ACCOUNT</span>
          <h1>Chat history</h1>
          <p>
          Your conversations with the assistant, saved to your account. Open one to read it or continue where you left off.
          </p>
        </div>

        {isLoading ? (
          <div className="history-state" role="status"><span className="history-spinner" /> Loading your account…</div>
        ) : !isAuthenticated ? (
          <div className="history-state history-state--notice">
            <span className="history-state-icon">🔐</span>
            <div><strong>Sign in to view your conversations</strong><p>Saved conversations are private to your account.</p>
              <Link href="/auth" className="history-primary-link">Sign in</Link></div>
          </div>
        ) : (
          <>
            <div className="history-toolbar">
              <label className="history-save-toggle">
                <input type="checkbox" checked={enabled ?? false}
                       disabled={enabled === null} onChange={(e) => toggle(e.target.checked)} />
                <span className="history-toggle-copy"><strong>Save my conversations</strong>
                  <small>{enabled ? "New conversations will appear here." : "New conversations won't be saved to your account."}</small></span>
              </label>
              {items.length > 0 && (confirming === "all" ? (
                <span className="history-actions">
                  <button onClick={removeAll} className="history-button history-button--danger">Delete all conversations</button>
                  <button onClick={() => setConfirming(null)} className="history-button">Cancel</button>
                </span>
              ) : (
                <button onClick={() => setConfirming("all")} className="history-button history-button--danger-quiet">
                  Delete all
                </button>
              ))}
            </div>

            {error && <p role="alert" className="history-alert history-alert--error">{error}</p>}
            {notice && <p role="status" className="history-alert history-alert--success">{notice}</p>}

            <div className="history-layout">
              <section aria-label="Your conversations" className="history-list-panel">
                <div className="history-list-heading">
                  <h2>Conversations</h2>
                  <span>{loading ? "Loading…" : `${total} ${total === 1 ? "chat" : "chats"}`}</span>
                </div>
                {loading && items.length === 0 && (
                  <div className="history-state history-state--compact" role="status">
                    <span className="history-spinner history-spinner--dark" /> Loading conversations…
                  </div>
                )}
                {!loading && items.length === 0 && (
                  <div className="history-empty" data-testid="history-empty">
                    <span className="history-empty-icon" aria-hidden="true">💬</span>
                    <strong>No saved conversations yet</strong>
                    <p>Start a chat and your conversations will show up here.</p>
                    <Link href="/" className="history-primary-link">Start a chat <span aria-hidden="true">→</span></Link>
                  </div>
                )}
                {items.map((c) => (
                  <article key={c.thread_id} data-testid="conversation"
                           className={`history-item ${open?.thread_id === c.thread_id ? "history-item--active" : ""}`}>
                    <button onClick={() => openConversation(c.thread_id)} className="history-item-open"
                            aria-current={open?.thread_id === c.thread_id ? "true" : undefined}>
                      <span className="history-item-icon" aria-hidden="true">💬</span>
                      <span className="history-item-copy">
                        <strong title={c.title || "Conversation"}>{c.title || "Conversation"}</strong>
                        <small>{when(c.last_activity_at)}</small>
                        <small>{c.message_count} messages{c.language ? ` · ${LANGUAGE_NAME[c.language] ?? c.language}` : ""}</small>
                      </span>
                    </button>
                    <div className="history-item-actions">
                      <button onClick={() => router.push(`/?thread=${encodeURIComponent(c.thread_id)}`)}
                              className="history-text-button">
                        Continue <span aria-hidden="true">→</span>
                      </button>
                      {confirming === c.thread_id ? (
                        <>
                          <button onClick={() => remove(c.thread_id)} className="history-text-button history-text-button--danger">Yes, delete</button>
                          <button onClick={() => setConfirming(null)} className="history-text-button">Cancel</button>
                        </>
                      ) : (
                        <button onClick={() => setConfirming(c.thread_id)} className="history-text-button history-text-button--danger">Delete</button>
                      )}
                    </div>
                  </article>
                ))}
                {items.length < total && (
                  <button onClick={() => load(items.length)} disabled={loading}
                          className="history-load-more">
                    {loading ? "Loading…" : `Load ${Math.min(PAGE, total - items.length)} more conversations`}
                  </button>
                )}
              </section>

              <section aria-label="Conversation" className="history-view" data-testid="conversation-view">
                {!open ? (
                  <div className="history-view-empty">
                    <span aria-hidden="true">📖</span>
                    <strong>Select a conversation</strong>
                    <p>Choose a chat from the list to read the conversation.</p>
                  </div>
                ) : (
                  <>
                    <div className="history-view-heading">
                      <div className="history-view-title">
                        <span className="history-view-icon" aria-hidden="true">💬</span>
                        <div>
                          <h2>{open.title || "Conversation"}</h2>
                          <p>Started {when(open.created_at)} · {open.messages.length} messages</p>
                        </div>
                      </div>
                      <button onClick={() => router.push(`/?thread=${encodeURIComponent(open.thread_id)}`)}
                              className="history-continue-button">
                        Continue this chat <span aria-hidden="true">→</span>
                      </button>
                    </div>
                    <ol className="history-messages">
                      {open.messages.map((m, i) => (
                        <li key={i} className={`history-message-row ${m.role === "USER" ? "history-message-row--user" : ""}`}>
                          <div className={`history-message ${m.role === "USER" ? "history-message--user" : "history-message--assistant"}`}>
                            <span className="sr-only">{m.role === "USER" ? "You:" : "Assistant:"}</span>
                            {m.role === "USER" && m.input_mode === "voice" && <span aria-label="voice">🎙️ </span>}
                            {m.content}
                            {m.schemes && m.schemes.length > 0 && (
                              <span className="history-schemes">
                                Schemes shown: {m.schemes.slice(0, 8).map((s) => s.name || s.scheme_id).join(", ")}
                                {m.schemes.length > 8 ? ` and ${m.schemes.length - 8} more` : ""}
                              </span>
                            )}
                            <span className="history-message-time">
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
      <style>{`
        .history-page { min-height: 100vh; background: #f0fdf4; color: #17211d; font-family: var(--font-geist-sans, Arial, sans-serif); }
        .history-header { position: sticky; top: 0; z-index: 20; background: linear-gradient(120deg, #064e3b, #047857); color: white; box-shadow: 0 3px 14px rgba(6, 78, 59, .2); }
        .history-header-inner { max-width: 1280px; min-height: 68px; margin: auto; padding: .7rem 1.5rem; display: flex; align-items: center; justify-content: space-between; gap: 1.25rem; }
        .history-brand { display: inline-flex; align-items: center; gap: .55rem; color: white; text-decoration: none; font-size: 1.15rem; font-weight: 800; white-space: nowrap; }
        .history-brand-icon { font-size: 1.45rem; }
        .history-nav { display: flex; align-items: center; justify-content: flex-end; gap: .5rem; flex-wrap: wrap; }
        .history-nav-btn { min-height: 42px; padding: .45rem .8rem; color: white; background: rgba(255,255,255,.1); border: 1px solid rgba(255,255,255,.2); border-radius: .6rem; font: inherit; font-size: .85rem; font-weight: 600; cursor: pointer; transition: background .15s, transform .15s; }
        .history-nav-btn:hover { background: rgba(255,255,255,.2); transform: translateY(-1px); }
        .history-main { max-width: 1280px; margin: 0 auto; padding: 2rem 1.5rem 3rem; }
        .history-heading { margin: 0 0 1.4rem; }
        .history-eyebrow { color: #047857; font-size: .72rem; font-weight: 800; letter-spacing: .12em; }
        .history-heading h1 { margin: .25rem 0 .35rem; color: #12392d; font-size: clamp(1.7rem, 3vw, 2.15rem); line-height: 1.2; letter-spacing: -.035em; }
        .history-heading p { max-width: 700px; margin: 0; color: #52635b; font-size: .95rem; line-height: 1.6; }
        .history-toolbar { min-height: 72px; margin: 0 0 1rem; padding: .8rem 1rem; display: flex; align-items: center; justify-content: space-between; gap: 1rem; background: white; border: 1px solid #dce8df; border-radius: .9rem; box-shadow: 0 2px 8px rgba(22, 56, 38, .04); }
        .history-save-toggle { display: flex; align-items: center; gap: .8rem; cursor: pointer; }
        .history-save-toggle input { width: 1.15rem; height: 1.15rem; accent-color: #059669; }
        .history-toggle-copy { display: grid; gap: .12rem; }
        .history-toggle-copy strong { color: #1f3329; font-size: .92rem; }
        .history-toggle-copy small { color: #68786e; font-size: .78rem; }
        .history-actions { display: inline-flex; align-items: center; gap: .5rem; }
        .history-button { min-height: 40px; padding: .45rem .8rem; border: 1px solid #d9e3dc; border-radius: .6rem; background: white; color: #42534a; font: inherit; font-size: .82rem; font-weight: 650; cursor: pointer; }
        .history-button:hover { background: #f8faf8; }
        .history-button--danger-quiet { color: #b42318; border-color: #f1d3d0; }
        .history-button--danger-quiet:hover { background: #fff6f5; }
        .history-button--danger { color: white; border-color: #b42318; background: #b42318; }
        .history-button--danger:hover { background: #912018; }
        .history-alert { margin: 0 0 1rem; padding: .75rem .9rem; border-radius: .65rem; font-size: .87rem; }
        .history-alert--error { color: #8f1d16; background: #fff1f0; border: 1px solid #f4c7c3; }
        .history-alert--success { color: #17613c; background: #edfbf2; border: 1px solid #b8e4c8; }
        .history-layout { display: grid; grid-template-columns: minmax(290px, .82fr) minmax(0, 1.5fr); align-items: start; gap: 1rem; }
        .history-list-panel, .history-view { min-width: 0; overflow: hidden; background: white; border: 1px solid #dce8df; border-radius: .95rem; box-shadow: 0 3px 14px rgba(22, 56, 38, .055); }
        .history-list-panel { padding: .85rem; }
        .history-list-heading { display: flex; align-items: center; justify-content: space-between; gap: .75rem; padding: .35rem .35rem .75rem; }
        .history-list-heading h2 { margin: 0; color: #18392c; font-size: 1rem; font-weight: 750; }
        .history-list-heading span { color: #718078; font-size: .78rem; }
        .history-item { margin: 0 0 .55rem; padding: .65rem .7rem; border: 1px solid #e3ebe5; border-radius: .7rem; background: #fff; transition: border-color .15s, background .15s, box-shadow .15s; }
        .history-item:hover { border-color: #a9d8bd; background: #fbfefc; }
        .history-item--active { border-color: #34a66f; background: #f0fbf4; box-shadow: 0 0 0 2px rgba(52, 166, 111, .1); }
        .history-item-open { width: 100%; min-height: 58px; padding: .15rem 0; display: flex; align-items: flex-start; gap: .65rem; text-align: left; border: 0; background: transparent; cursor: pointer; }
        .history-item-icon { flex: 0 0 34px; width: 34px; height: 34px; display: grid; place-items: center; border-radius: .55rem; background: #eaf7ee; font-size: 1rem; }
        .history-item-copy { min-width: 0; display: grid; gap: .18rem; }
        .history-item-copy strong { overflow: hidden; color: #20362a; font-size: .86rem; font-weight: 700; text-overflow: ellipsis; white-space: nowrap; }
        .history-item-copy small { color: #748078; font-size: .73rem; }
        .history-item-actions { margin: .35rem 0 0 2.65rem; display: flex; flex-wrap: wrap; align-items: center; gap: .8rem; }
        .history-text-button { min-height: 30px; padding: .15rem 0; border: 0; background: transparent; color: #087443; font: inherit; font-size: .76rem; font-weight: 700; cursor: pointer; }
        .history-text-button:hover { text-decoration: underline; }
        .history-text-button--danger { color: #b42318; }
        .history-load-more { width: 100%; min-height: 42px; margin-top: .2rem; padding: .5rem; border: 1px solid #d9e3dc; border-radius: .6rem; background: white; color: #365447; font: inherit; font-size: .8rem; font-weight: 650; cursor: pointer; }
        .history-load-more:hover { background: #f4faf6; }
        .history-load-more:disabled { opacity: .6; cursor: wait; }
        .history-view { min-height: 430px; }
        .history-view-empty { min-height: 430px; padding: 2rem; display: flex; flex-direction: column; align-items: center; justify-content: center; text-align: center; color: #66776e; }
        .history-view-empty > span { width: 58px; height: 58px; margin-bottom: .85rem; display: grid; place-items: center; border-radius: 1rem; background: #eff8f1; font-size: 1.5rem; }
        .history-view-empty strong { color: #284537; font-size: 1rem; }
        .history-view-empty p { margin: .4rem 0 0; font-size: .85rem; }
        .history-view-heading { position: sticky; top: 68px; z-index: 1; padding: 1rem 1.15rem; display: flex; align-items: center; justify-content: space-between; gap: 1rem; border-bottom: 1px solid #e6eee8; background: rgba(255,255,255,.97); }
        .history-view-title { min-width: 0; display: flex; align-items: center; gap: .7rem; }
        .history-view-icon { flex: 0 0 38px; width: 38px; height: 38px; display: grid; place-items: center; border-radius: .65rem; background: #eaf7ee; }
        .history-view-title h2 { overflow: hidden; margin: 0 0 .2rem; color: #1c382a; font-size: .98rem; text-overflow: ellipsis; white-space: nowrap; }
        .history-view-title p { margin: 0; color: #728078; font-size: .75rem; }
        .history-continue-button, .history-primary-link { min-height: 40px; padding: .55rem .8rem; display: inline-flex; align-items: center; justify-content: center; gap: .4rem; border: 0; border-radius: .6rem; background: #07834f; color: white; text-decoration: none; font: inherit; font-size: .8rem; font-weight: 700; white-space: nowrap; cursor: pointer; }
        .history-continue-button:hover, .history-primary-link:hover { background: #066a41; }
        .history-messages { max-height: min(68vh, 760px); min-height: 350px; overflow-y: auto; margin: 0; padding: 1.25rem; display: flex; flex-direction: column; gap: .9rem; list-style: none; background: #fbfdfb; }
        .history-message-row { display: flex; justify-content: flex-start; }
        .history-message-row--user { justify-content: flex-end; }
        .history-message { max-width: min(85%, 680px); padding: .7rem .9rem .55rem; border-radius: 1rem 1rem 1rem .25rem; color: #24352b; background: #edf2ee; font-size: .88rem; line-height: 1.55; white-space: pre-wrap; overflow-wrap: anywhere; box-shadow: 0 1px 2px rgba(20, 45, 28, .04); }
        .history-message--user { border-radius: 1rem 1rem .25rem 1rem; color: white; background: #07834f; }
        .history-schemes { display: block; margin-top: .6rem; padding-top: .5rem; border-top: 1px solid rgba(100, 120, 108, .2); color: inherit; font-size: .74rem; opacity: .85; }
        .history-message-time { display: block; margin-top: .35rem; color: inherit; font-size: .66rem; opacity: .65; text-align: right; }
        .history-empty, .history-state { min-height: 240px; padding: 1.5rem; display: flex; flex-direction: column; align-items: center; justify-content: center; text-align: center; color: #66776e; }
        .history-empty { min-height: 300px; }
        .history-empty-icon { width: 58px; height: 58px; margin-bottom: .85rem; display: grid; place-items: center; border-radius: 1rem; background: #eff8f1; font-size: 1.55rem; }
        .history-empty strong, .history-state--notice strong { color: #284537; font-size: .98rem; }
        .history-empty p, .history-state--notice p { margin: .4rem 0 1rem; font-size: .84rem; line-height: 1.5; }
        .history-empty .history-primary-link { min-height: 38px; }
        .history-state { flex-direction: row; gap: .7rem; }
        .history-state--compact { min-height: 140px; font-size: .84rem; }
        .history-state--notice { flex-direction: row; align-items: flex-start; justify-content: flex-start; max-width: 620px; min-height: unset; padding: 1.25rem; text-align: left; background: white; border: 1px solid #dce8df; border-radius: .9rem; }
        .history-state--notice p { margin-bottom: .75rem; }
        .history-state-icon { font-size: 1.5rem; }
        .history-spinner { width: 20px; height: 20px; border: 2px solid #cfe7d7; border-top-color: #07834f; border-radius: 50%; animation: history-spin .7s linear infinite; }
        .history-spinner--dark { border-color: #dce8df; border-top-color: #07834f; }
        @keyframes history-spin { to { transform: rotate(360deg); } }
        .history-page button:focus-visible, .history-page a:focus-visible, .history-page input:focus-visible { outline: 3px solid #fbbf24; outline-offset: 3px; }
        @media (max-width: 760px) {
          .history-header-inner { align-items: flex-start; flex-direction: column; gap: .65rem; padding: .8rem 1rem; }
          .history-nav { width: 100%; justify-content: flex-start; }
          .history-nav-btn { font-size: .78rem; }
          .history-main { padding: 1.35rem 1rem 2rem; }
          .history-layout { grid-template-columns: minmax(0, 1fr); }
          .history-list-panel { order: 1; }
          .history-view { order: 2; min-height: 300px; }
          .history-view-empty { min-height: 300px; }
          .history-messages { max-height: 65vh; min-height: 260px; padding: .9rem; }
          .history-view-heading { top: 104px; padding: .8rem; }
        }
        @media (max-width: 480px) {
          .history-toolbar { align-items: flex-start; flex-direction: column; }
          .history-actions { width: 100%; }
          .history-button { flex: 1; }
          .history-nav { gap: .35rem; }
          .history-nav-btn { min-height: 40px; padding: .35rem .55rem; }
          .history-view-heading { align-items: flex-start; flex-direction: column; }
          .history-continue-button { width: 100%; }
          .history-message { max-width: 94%; }
        }
        @media (prefers-reduced-motion: reduce) {
          .history-page *, .history-page *::before, .history-page *::after { animation-duration: .01ms !important; scroll-behavior: auto !important; transition-duration: .01ms !important; }
        }
      `}</style>
    </div>
  );
}
