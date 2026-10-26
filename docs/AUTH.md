# Accounts and Sign-in

Signing in is optional: the assistant works without an account. An account lets a
farmer save their profile, bookmark schemes and see their search history.

## How it works

| Part | What we do |
|---|---|
| Passwords | Hashed with **Argon2id** (argon2-cffi; 19 MiB memory, 2 passes). Never stored in plain text. Old bcrypt hashes still work and are upgraded to Argon2id at the next sign-in. |
| Sessions | Server-side. After sign-in the browser gets a random 256-bit token in a cookie that is **HttpOnly** (JavaScript can't read it), **SameSite=Lax**, and **Secure** in production. The database stores only its SHA-256 hash. |
| Session end | After 12 h without activity, 7 days after sign-in, on sign-out, on "sign out of all devices", and on every password reset or change. **Staff (REVIEWER / ADMIN) sessions are shorter:** 30 minutes idle, 12 hours in total (`STAFF_SESSION_IDLE_MINUTES`, `STAFF_SESSION_ABSOLUTE_HOURS`). They also end when a role changes, a reviewer's approval is revoked, or the account is deactivated. |
| Reauthentication | Sensitive staff actions need a sign-in or a password confirmation within `REAUTH_WINDOW_MINUTES` (default 10). These are final review decisions, dismissals, case assignments and grants, and reviewer approval. Otherwise the server answers 403 `REAUTH_REQUIRED`; the page asks for the password (`POST /auth/reauthenticate`) and retries. Five wrong passwords end the session. Both outcomes are audited. See [HUMAN_REVIEW.md](HUMAN_REVIEW.md). |
| Stolen-cookie protection | A session only works in the browser it was created in (User-Agent check). Used from another browser, it is rejected and revoked. Every sign-in creates a new session id, which prevents session fixation. |
| CSRF | Every state-changing request made with the cookie must send the session's CSRF token in the `X-CSRF-Token` header. The token is derived from the session with HMAC, kept in memory by the frontend, and returned by `/auth/login` and `/auth/session`. Account POSTs from origins not in `CORS_ORIGINS` are refused. |
| E-mail verification | New accounts must open the e-mailed link (valid 24 h, single use) before they can sign in. |
| Password reset | The link is random (256-bit), stored hashed, single use, valid **30 minutes**, and replaced by any newer request. A reset signs the account out everywhere. |
| No account enumeration | Registration, resend-verification and forgot-password give the same answer whether or not the e-mail exists. Unknown e-mails cost the same password-hash time. |
| Brute force | After 5 wrong passwords the account is locked for 15 minutes. Every account endpoint is rate-limited per IP and per e-mail (HTTP 429 with `Retry-After`). |

## Endpoints (`/auth`)

| Method | Path | Notes |
|---|---|---|
| POST | `/register` | `{email, password, full_name?, phone?}` → 202, generic message; e-mails a verification link |
| POST | `/verify-email` | `{token}` → 200, or 400 if invalid/expired/used |
| POST | `/resend-verification` | `{email}` → 202, generic |
| POST | `/login` | `{email, password}` → 200 `{user, csrf_token, session_expires_at}` + cookie; 401 generic; 403 `EMAIL_NOT_VERIFIED`; 429 |
| GET | `/session` | 200 `{user, csrf_token, ...}` or 401 |
| POST | `/logout` | 204, clears the cookie (CSRF required when signed in) |
| POST | `/logout-all` | Ends every session of the account (CSRF) |
| POST | `/forgot-password` | `{email}` → 202, generic; e-mails a reset link |
| POST | `/reset-password` | `{token, new_password}` → 200, or 400 |
| POST | `/change-password` | `{current_password, new_password}` (CSRF) → new session; other sessions ended |
| POST | `/reauthenticate` | `{password}` (CSRF) → confirms the password for sensitive actions for `REAUTH_WINDOW_MINUTES`; 5 wrong passwords end the session |

Passwords: 8–128 characters, with at least one letter and one number.
The `/farmers/me/*` routes require a session (plus CSRF for PUT/POST/DELETE).
Chat and voice work signed out. Signed in, they use the saved profile only when the
CSRF header is present, so another site cannot act as the user.

## E-mail

Set `SMTP_*` in `backend/.env` to send real e-mail. Without it, for local use, each
e-mail and its link is printed in the backend log:

```
docker compose logs backend | grep -A3 "DEV E-MAIL"
```

In production without SMTP, nothing is sent and the link is never logged.

## Database

Migration `0003` adds `auth_sessions`, `auth_tokens` and lockout columns on
`farmers`. It doesn't drop anything. Old reset tokens are cleared and old refresh
tokens revoked, because the previous version exposed reset tokens in an API response.

## Tests

- `backend/app/tests/test_auth_security.py`: all account flows through the API, including session-hijacking attempts.
- `backend/app/tests/test_auth_repository_pg.py`: the real SQL and the migration, against PostgreSQL. Opt-in:
  `TEST_DATABASE_URL=postgresql://schemesetu:schemesetu@localhost:5432/schemesetu_auth_test`
- `scripts/ui_auth_test.py`: the same flows in a real browser (Playwright) against `docker compose up`.

## Known limitations

- Rate limits are kept in memory per backend process: fine for one instance, but several instances would need a shared store.
- The User-Agent check stops simple cookie replay, not an attacker who copies the exact User-Agent.
- No two-factor authentication, and no check against breached-password lists.
