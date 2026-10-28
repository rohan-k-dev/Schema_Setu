# Chat History

Every signed-in account keeps its conversations with the assistant. The farmer can open **Chat history**
(`/history`, also linked from the chat page and the dashboard) at any time to read a past conversation,
continue it, or delete it. Conversations of visitors who are not signed in are not saved.

## What is saved

| | Saved | Not saved |
|---|---|---|
| Question | As typed, or the transcript of a voice question (English, from the speech service) | The voice recording |
| Reply | As shown to the farmer, in the reply language | — |
| Per message | language, text / voice, reply status, the schemes shown (id, name, section, eligibility) | full scheme cards, live-check details |
| Conversation | title (first question, 120 characters), message count, created / last active | — |

Storage: migration **0012** reuses the `sessions` and `messages` tables created in 0001 (they were never
written to before) and adds `sessions.farmer_id` (ON DELETE CASCADE), `title`, `message_count`,
`messages.language / input_mode / status / schemes`, and `farmers.chat_history_enabled`.

Limits: newest **200** conversations per account, **400** messages per conversation, 8,000 characters per
message (`app/database/repositories/chat_history_repository.py`).

## Using it

- **List / open:** newest first, 20 at a time ("Load more"); a conversation shows each question and reply with
  time, a 🎙️ mark for voice questions and the schemes shown.
- **Continue:** "Continue this chat" opens it in the chat (`/?thread=<id>`): earlier messages come back, new
  messages are added to the same conversation, the reply language is restored. If the server restarted (the
  assistant's working memory is in-process), the last 10 saved messages are given back to the assistant as
  context.
- **Delete** one conversation or all of them (also on the Privacy page). The assistant's in-memory copy is
  dropped too.
- **Turn off:** "Save my conversations" — new conversations aren't saved; existing ones stay until deleted.

## Security

- Every call is scoped to the signed-in session (`chat_history:own`, all roles); another account's
  conversation returns **404**, the same as a missing one.
- The chat never continues another account's conversation: a thread id that belongs to someone else (or any
  saved conversation, for a signed-out visitor) is replaced by a fresh one before the assistant runs — so a
  conversation can't be read or continued by guessing or reusing its id. The repository also refuses to
  append to another account's conversation (`NotYours`).
- Saving never breaks a chat: errors are logged and the reply is returned as usual.

## API

| Method | Path | |
|---|---|---|
| GET | `/farmers/me/conversations?limit=&offset=` | newest first; total in `X-Total-Count` |
| GET | `/farmers/me/conversations/{thread_id}` | with messages |
| DELETE | `/farmers/me/conversations/{thread_id}` | 204 / 404 |
| DELETE | `/farmers/me/conversations` | `{"deleted": n}` |
| GET / PUT | `/farmers/me/chat-history-settings` | `{"enabled": true}` |

## Privacy and retention

Listed in the privacy inventory (`app/core/privacy.py`, docs/PRIVACY.md): included in the data export,
deleted with the account (cascade) or from the Privacy page, and purged **365 days** after a conversation's
last message (`RETENTION_CHAT_DAYS`, daily purge). Questions and replies were already sent to the language
model and translation service while chatting; storing them adds no new external sharing.

## Tests

- `app/tests/test_chat_history.py` (13): saving, anonymous not saved, setting on/off, cross-account read /
  delete / continue refused, thread id validation, continuing with context after a restart, delete one / all
  (and the in-memory copy), a saving failure never breaks the chat.
- `app/tests/test_chat_history_pg.py` (4, PostgreSQL): append / list / open, other accounts refused, caps,
  setting, account deletion cascade, retention purge.
- `app/tests/test_rbac.py`: the six routes in the role matrix.
- `scripts/ui_chat_history_test.py` (12, real browser + real assistant): two questions saved, listed, opened,
  continued, follow-up added to the same conversation, another account sees nothing (also by id and via /chat),
  saving off, delete.
