"""
What SchemeSetu collects, why, where it is kept, for how long, and who else processes it
(docs/PRIVACY.md). Served as-is by GET /privacy/policy and shown on the Privacy and Data
Settings page; test_privacy.py fails if a stored profile column is missing from here.

Accuracy rules for this file: never describe external processing as local, and say
"not sent from your saved profile" (not "never shared") for details a farmer may still type
into a chat message, because chat text goes to the LLM provider.
"""

from __future__ import annotations

from typing import Any, Dict, List

from app.core.config import settings

GROQ, TAVILY, SARVAM, SMTP, SMS = "groq", "tavily", "sarvam", "email_provider", "sms_provider"

# ─── fields ───────────────────────────────────────────────────────────────────

ACCOUNT_FIELDS: List[Dict[str, Any]] = [
    {"field": "email", "label": "E-mail address", "required": True,
     "why": "Signing in, verifying the account, password reset, and e-mail alerts if you turn them on.",
     "stored": "Yes — accounts table, until you delete the account.",
     "shared_with": [SMTP], "shared_note": "Only to send you an e-mail (when an e-mail service is set up)."},
    {"field": "password", "label": "Password", "required": True,
     "why": "Signing in.",
     "stored": "Only as an Argon2id hash; the password itself is never stored.",
     "shared_with": [], "shared_note": "Never shared."},
    {"field": "full_name", "label": "Name", "required": False,
     "why": "Greeting you on your dashboard.",
     "stored": "Yes, if you give it.", "shared_with": [], "shared_note": "Not shared."},
    {"field": "phone", "label": "Mobile number", "required": False,
     "why": "SMS alerts about schemes you follow — only after you verify it and agree to SMS.",
     "stored": "Yes, if you add it; removing it turns SMS off.",
     "shared_with": [SMS], "shared_note": "Only to send a verification code or an SMS you opted into."},
]

# Every column a profile save may write (app.database.repositories.profile_repository.PROFILE_COLUMNS)
PROFILE_FIELDS: List[Dict[str, Any]] = [
    {"field": "state", "columns": ["state"], "label": "State", "required": False,
     "why": "State schemes apply only in their state; also narrows the scheme search.",
     "used_for_eligibility": True,
     "shared_with": [GROQ, TAVILY],
     "shared_note": "Sent with your question to the AI model, and in the web-search phrase (not your question)."},
    {"field": "district", "columns": ["district"], "label": "District", "required": False,
     "why": "Narrows the scheme search.", "used_for_eligibility": False,
     "shared_with": [GROQ], "shared_note": "Sent with your question to the AI model."},
    {"field": "land_size", "columns": ["land_size_value", "land_unit", "land_size_acres"],
     "label": "Land size and unit", "required": False,
     "why": "Land rules (e.g. landholding, up to 5 acres); converted to acres for the rules.",
     "used_for_eligibility": True,
     "shared_with": [GROQ], "shared_note": "The size in acres is sent with your question to the AI model."},
    {"field": "primary_crop", "columns": ["primary_crop"], "label": "Main crop", "required": False,
     "why": "Crop-specific schemes and the scheme search.", "used_for_eligibility": True,
     "shared_with": [GROQ, TAVILY],
     "shared_note": "Sent with your question to the AI model, and in the web-search phrase (not your question)."},
    {"field": "other_crops", "columns": ["other_crops"], "label": "Other crops", "required": False,
     "why": "Shown on your profile only.", "used_for_eligibility": False,
     "shared_with": [], "shared_note": "Not sent from your saved profile."},
    {"field": "farming_type", "columns": ["farming_type"], "label": "Farming type", "required": False,
     "why": "Shown on your profile only.", "used_for_eligibility": False,
     "shared_with": [], "shared_note": "Not sent from your saved profile."},
    {"field": "occupation", "columns": ["occupation"], "label": "Occupation", "required": False,
     "why": "Many schemes are only for farmers.", "used_for_eligibility": True,
     "shared_with": [GROQ], "shared_note": "Sent with your question to the AI model."},
    {"field": "age", "columns": ["age"], "label": "Age", "required": False,
     "why": "Age limits (e.g. pension and insurance schemes).", "used_for_eligibility": True,
     "shared_with": [], "shared_note": "Checked on our server only; not sent from your saved profile."},
    {"field": "gender", "columns": ["gender"], "label": "Gender", "required": False,
     "why": "Schemes for women farmers.", "used_for_eligibility": True,
     "shared_with": [], "shared_note": "Checked on our server only; not sent from your saved profile."},
    {"field": "category", "columns": ["category"], "label": "Social category", "required": False,
     "why": "Schemes for SC / ST and other categories.", "used_for_eligibility": True,
     "shared_with": [], "shared_note": "Checked on our server only; not sent from your saved profile."},
    {"field": "income_range", "columns": ["income_range"], "label": "Yearly household income (range)",
     "required": False, "why": "Kept as a range only; no eligibility rule uses it today.",
     "used_for_eligibility": False,
     "shared_with": [], "shared_note": "Not sent from your saved profile. Exact income is never stored."},
    {"field": "residence", "columns": ["residence"], "label": "Rural or urban", "required": False,
     "why": "Rural employment schemes (MGNREGA).", "used_for_eligibility": True,
     "shared_with": [GROQ],
     "shared_note": "Checked on our server; the value can appear in a scheme's matched criteria sent to the AI "
                    "model to word the reply."},
    {"field": "consent", "columns": ["consent_given", "consent_given_at"], "label": "Your consent",
     "required": True, "why": "Required before any profile detail is saved; records when you agreed.",
     "used_for_eligibility": False, "shared_with": [], "shared_note": "Not shared."},
]

NOT_COLLECTED = [
    "Aadhaar number (never asked for; Aadhaar appears only as a document a scheme requires)",
    "Aadhaar status, bank account, PAN",
    "Exact income (only a range)",
    "Your location from the device",
]

CHAT_NOTE = ("Anything you type or say in the chat is sent to the AI model provider (and, for languages other "
             "than English or for voice, to the translation and speech provider) — including personal details "
             "you choose to write. Please don't type ID numbers or bank details.")

# ─── other records ────────────────────────────────────────────────────────────

RECORDS: List[Dict[str, Any]] = [
    {"record": "search_history", "label": "Recent searches",
     "what": "Your chat or voice question text, number of results, language, time.",
     "when": "Only while you have agreed to keep your details.",
     "retention": "Newest 50, at most 90 days; deleted with your profile or account.", "you_can": "view, delete, export"},
    {"record": "saved_schemes", "label": "Saved schemes and checklists",
     "what": "Schemes you saved, your notes, checklist ticks, application reference.",
     "when": "When you save a scheme.", "retention": "Until you remove them or delete the account.",
     "you_can": "view, edit, delete, export"},
    {"record": "notifications", "label": "Notification settings, followed schemes and messages",
     "what": "Channel choices, SMS consent time, schemes you follow, in-app messages and their delivery status.",
     "when": "When you change settings or a followed scheme is updated.",
     "retention": "Messages: 365 days. Settings: until you delete them or the account.",
     "you_can": "view, change, delete, export"},
    {"record": "review_cases", "label": "Checks by our team",
     "what": "When a result needed a person to check it: the scheme, the reason, your question (contact details "
             "masked) and only the profile details those rules use.",
     "when": "When your search raised a check.",
     "retention": "Unlinked from you and your question and details removed when you delete the account; "
                  "anonymised 365 days after the check is closed. The check itself is kept as a quality record.",
     "you_can": "view (status and outcome), export"},
    {"record": "sessions", "label": "Sign-in sessions",
     "what": "When you signed in, last activity, IP address, a hash of your browser identifier.",
     "when": "Each sign-in.", "retention": "Removed 30 days after the session ends.",
     "you_can": "sign out everywhere (Security page), export"},
    {"record": "chat", "label": "Chat conversation",
     "what": "Messages of the current conversation and the details found in them.",
     "when": "While you chat.",
     "retention": "Server memory only (never written to the database); the oldest are dropped after "
                  f"{settings.MAX_SESSIONS} conversations and all are lost when the server restarts.",
     "you_can": "start a new conversation; deleting the account also clears conversations linked to your checks"},
    {"record": "voice", "label": "Voice recordings",
     "what": "Audio you record in the chat.", "when": "When you use voice.",
     "retention": "Not stored by SchemeSetu; sent to the speech provider for transcription.", "you_can": "—"},
    {"record": "audit", "label": "Security record (audit log)",
     "what": "Security-relevant actions on your account (e.g. consent to SMS, data export, account deletion), with "
             "the account id; staff actions also keep the staff e-mail.",
     "when": "When those actions happen.",
     "retention": "Kept; see the exceptions below.", "you_can": "—"},
]

# ─── third-party processing ───────────────────────────────────────────────────

PROCESSORS: List[Dict[str, Any]] = [
    {"id": GROQ, "name": "Groq (AI language model)", "purpose":
        "Understands your chat messages (finds profile details in them), rewrites search queries and words replies. "
        "It never decides eligibility.",
     "receives": "The recent messages of your conversation (full text), and from your profile only state, district, "
                 "land size in acres, main crop and occupation. Scheme cards (matched / failed criteria) are sent "
                 "with your age, gender, social category and income values masked; other criterion values, such "
                 "as rural / urban, can appear.",
     "when": "Every chat or voice turn, when the service is configured.",
     "configured": bool(settings.GROQ_API_KEY)},
    {"id": TAVILY, "name": "Tavily (web search)", "purpose": "Finds official scheme pages on the web.",
     "receives": "A search phrase made of your state, your main crop, fixed topic words picked from a fixed list "
                 "when your question mentions them (e.g. \"insurance\", \"loan\") and fixed words — e.g. \"crop "
                 "insurance Karnataka ragi farmer government scheme eligibility benefits\". Never your question "
                 "text, age, category, income or other details. Official government pages it finds are then read "
                 "by SchemeSetu's server; those websites see only the server, never your data.",
     "when": "Scheme searches, when the service is configured.", "configured": bool(settings.TAVILY_API_KEY)},
    {"id": SARVAM, "name": "Sarvam AI (translation and speech)", "purpose":
        "Translates messages and replies for Indian languages; turns your voice into text and replies into speech.",
     "receives": "The full text of your messages and of the replies (languages other than English), your voice "
                 "recordings, and reply text for speech.",
     "when": "When you chat in another language or use voice, when the service is configured.",
     "configured": bool(settings.SARVAM_API_KEY)},
    {"id": SMTP, "name": "E-mail service (SMTP)", "purpose": "Sends verification, password-reset and opted-in "
                                                             "notification e-mails.",
     "receives": "Your e-mail address and the e-mail content.", "when": "When an e-mail is sent.",
     "configured": bool(settings.SMTP_HOST)},
    {"id": SMS, "name": "SMS provider", "purpose": "Sends phone verification codes and SMS alerts you opted into.",
     "receives": "Your mobile number and the message.", "when": "Only after you verified the number and agreed to SMS.",
     "configured": bool(settings.SMS_PROVIDER)},
]

PROCESSOR_NOTE = ("These are external services: what they receive leaves SchemeSetu's server and is handled under "
                  "their own terms and retention. Deleting your data here does not delete copies those services may "
                  "keep. When a service isn't configured, the feature that needs it is unavailable or falls back to "
                  "a simpler local method (for example, replies are then built without the AI model).")

# ─── deletion and retention exceptions ────────────────────────────────────────

EXCEPTIONS: List[Dict[str, str]] = [
    {"what": "Security record (audit log)",
     "why": "It is append-only and hash-chained so tampering can be detected; removing entries would break that. "
            "Entries you caused keep your account id, and for staff actions the staff e-mail.",
     "how_long": "Kept without a time limit today (no automatic purge)."},
    {"what": "Review history written by staff",
     "why": "Reviewers' names on decisions are kept for accountability, also after a reviewer's account is deleted.",
     "how_long": "With the case."},
    {"what": "Checks by our team (review cases)",
     "why": "Kept as an anonymous quality record: on account deletion they are unlinked from you and your question "
            "and profile details are removed.",
     "how_long": "Anonymised content kept; fully anonymised 365 days after closing in any case."},
    {"what": "Data already sent to external services",
     "why": "Groq, Tavily, Sarvam, the e-mail and SMS services keep data under their own policies.",
     "how_long": "Their retention, not ours."},
    {"what": "Server logs",
     "why": "Operational logs can contain request details; in development without an e-mail service, e-mails "
            "(with the address) are printed to the log.",
     "how_long": "Until the server's log rotation removes them (Docker log settings)."},
    {"what": "Database backups",
     "why": "SchemeSetu itself makes no backups of personal data (its backups contain public scheme data only). "
            "If the operator backs up the database, deleted data stays in those backups.",
     "how_long": "Until the operator's backups expire."},
    {"what": "Chat conversations in server memory",
     "why": "Not linked to your account; cleared for conversations linked to your checks when you delete the "
            "account, otherwise dropped when evicted or on restart.",
     "how_long": f"At most until {settings.MAX_SESSIONS} newer conversations exist or the server restarts."},
    {"what": "Rate-limit counters",
     "why": "Kept in memory against abuse (by IP address and e-mail).",
     "how_long": "At most one hour."},
    {"what": "Last administrator",
     "why": "The last active administrator account can't be deleted (the system would be left without one).",
     "how_long": "Until another administrator exists."},
]


def retention_days() -> Dict[str, int]:
    return {"search_history": 90, "sessions_after_end": settings.RETENTION_SESSION_DAYS,
            "tokens_after_use": settings.RETENTION_TOKEN_DAYS,
            "notifications": settings.RETENTION_NOTIFICATION_DAYS,
            "closed_review_cases_anonymised_after": settings.RETENTION_REVIEW_CASE_DAYS}


def policy() -> Dict[str, Any]:
    """Everything the privacy page shows (no personal data)."""
    return {"account_fields": ACCOUNT_FIELDS, "profile_fields": PROFILE_FIELDS, "not_collected": NOT_COLLECTED,
            "chat_note": CHAT_NOTE, "records": RECORDS, "processors": PROCESSORS, "processor_note": PROCESSOR_NOTE,
            "exceptions": EXCEPTIONS, "retention_days": retention_days(),
            "required_note": "Only an e-mail address and a password are required (to have an account). Every profile "
                             "detail is optional: a missing detail makes a result \"needs more information\", never "
                             "\"not eligible\". Saving any detail needs your consent."}
