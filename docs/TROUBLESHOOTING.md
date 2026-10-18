# Troubleshooting

Problems below were all encountered during development or the Phase 8 release check.

## Environment / start-up
| Symptom | Cause | Fix |
|---|---|---|
| `TypeError: Reviver.__init__() got an unexpected keyword argument 'allowed_objects'` on import | A newer `langgraph-checkpoint` / `langgraph-prebuilt` installed over the pinned `langgraph==0.0.31` | Use a fresh virtualenv with `pip install -r backend/requirements.txt`, or `pip uninstall -y langgraph-prebuilt langgraph-checkpoint && pip install --force-reinstall --no-deps langgraph==0.0.31` |
| `alembic upgrade head` → `No module named 'psycopg2'` | Fixed in v1.0.0 (`alembic/env.py` uses psycopg 3). Old checkout? | Update, or use a `postgresql+psycopg://` URL |
| Windows: `Psycopg cannot use the 'ProactorEventLoop'` | Async psycopg needs the selector loop on Windows | Start with `python -m app`. Scripts handle it automatically |
| `/health` → `degraded`, `db_connected:false` | `DATABASE_URL` unset or wrong, or DB down | `docker ps`, `pg_isready`, check the URL, `python scripts/db_check.py` |
| `/health` → `graph_available:false` | `data/graph/current/graph.json` missing | `python scripts/build_knowledge_graph.py`, restart |
| Import fails `violates check constraint "ck_step_mode"` | Old importer with new corpus modes | Fixed in v1.0.0 (`normalize_step_mode`) |
| Next.js warns "multiple lockfiles … inferred workspace root" | A stray `package-lock.json` in a parent folder | Fixed by `turbopack.root` in `next.config.ts`; or delete the stray lockfile |
| Windows: Turbopack "path length … exceeds max length" | Project in a very deep folder | Move the repo to a shorter path (e.g. `C:\dev\Scheme_Setu`) |

## Conversation
| Symptom | Cause | Fix |
|---|---|---|
| Reply "I can't understand free-text answers right now because the language service is unavailable" | No or invalid `GROQ_API_KEY`, or Groq outage / timeout | Set the key; check `/health/ready` → `groq_configured`. For a keyless demo use `scripts/demo_server.py` |
| Assistant forgets earlier answers | Each message sent with a different `thread_id` | Keep one `thread_id` per conversation (the UI uses one per tab; "New chat" starts a new one) |
| Status `partial_results` | One retrieval channel failed (often Tavily with no key) | Expected degradation; see `docs/FAILURE_HANDLING.md` |
| Many schemes "Needs additional verification" | 22/40 corpus schemes have no structured rules | Corpus limitation; such sessions open one UNVERIFIABLE review case |
| A scheme you expected is missing | Restricted to another state/crop, or the crop isn't in the corpus vocabulary (no crop taxonomy) | Check `GET /schemes?state=&crop=` |

## Voice
| Symptom | Cause | Fix |
|---|---|---|
| "Voice service is not configured" | No `SARVAM_API_KEY` | Set the key; text input keeps working |
| `VALIDATION_ERROR` "not a recognised audio recording" | Payload is not WAV/WebM/Ogg/MP3/MP4/FLAC, or doesn't match its MIME type | Record again; don't rename files to `.wav` |
| "Microphone access is required…" | Browser permission denied, or the page is not on HTTPS/localhost | Allow the microphone; serve over HTTPS in production |
| No audio playback | TTS failed (best-effort) or autoplay blocked | Text reply is complete; the "Stop audio" control appears while speaking |

## Review API
| Symptom | Fix |
|---|---|
| 403 "Review API is not configured." | Set `REVIEW_API_KEY` and restart |
| 403 "Unauthorized reviewer access." | Send header `X-Review-Key: <key>` |
| 400 "invalid status transition" | `REQUEST_INFORMATION` first (PENDING → IN_REVIEW), then APPROVE / REJECT / MARK_UNVERIFIABLE |

## Deployment
| Symptom | Fix |
|---|---|
| Browser can't reach the API from the Docker frontend | `NEXT_PUBLIC_API_BASE_URL` is compiled in at build time; rebuild with the public backend URL |
| CORS error in the browser console | Add the exact frontend origin to `CORS_ORIGINS` (JSON list) |
| `init` container fails | `docker compose logs init`: usually the DB isn't reachable or the migration failed |
| Port 5432/8000/3000 in use | Stop the other service or change the published port in `docker-compose.yml` |
| Memory grows with traffic | Each kept conversation is about 300 KB; lower `MAX_SESSIONS` |
