"""
Outbound-data minimisation (Phase 7 §114, BUG-022).

Only the profile fields an external LLM actually needs are sent to it.
Income, social category, gender and Aadhaar status are used by the local
deterministic eligibility engine and never leave the server in prompts.
"""

from typing import Any, Dict

LLM_SAFE_PROFILE_FIELDS = ("state", "district", "land_size_acres", "primary_crop", "occupation")


SENSITIVE_PROFILE_FIELDS = ("annual_income", "category", "gender", "has_aadhaar", "age")


def redact_scheme_for_llm(scheme: Dict[str, Any]) -> Dict[str, Any]:
    """
    Copy of a scheme card for the LLM prompt: the user's own values for
    sensitive criteria are replaced by "(provided by user)" and the
    pre-rendered explanation (which repeats them) is dropped. The LLM can still
    say *that* a criterion matched; the user-facing card keeps full evidence.
    """
    out = {k: v for k, v in scheme.items() if k != "xai_explanation"}
    for key in ("matched_criteria", "failed_criteria"):
        crits = []
        for c in scheme.get(key) or []:
            c = dict(c)
            if c.get("field") in SENSITIVE_PROFILE_FIELDS and c.get("user_value") is not None:
                c["user_value"] = "(provided by user)"
            crits.append(c)
        out[key] = crits
    return out


# Only what the LLM needs to word a reply (Phase 8: the full card cost ~500 tokens per
# scheme and exceeded Groq's free-tier tokens-per-minute limit). The validator still
# checks the reply against the full cards.
_LLM_SCHEME_FIELDS = ("scheme_id", "name", "eligibility_status", "benefit_summary", "documents",
                      "application_steps", "official_url", "missing_information")
_LLM_CRITERION_FIELDS = ("field", "user_value", "required_value")


def compact_scheme_for_llm(scheme: Dict[str, Any]) -> Dict[str, Any]:
    """Minimal, redacted view of a scheme card for the reply-wording prompt."""
    redacted = redact_scheme_for_llm(scheme)
    out = {k: redacted[k] for k in _LLM_SCHEME_FIELDS if redacted.get(k) not in (None, [], "")}
    for key in ("matched_criteria", "failed_criteria"):
        crits = [{f: c.get(f) for f in _LLM_CRITERION_FIELDS if c.get(f) is not None}
                 for c in redacted.get(key) or []]
        if crits:
            out[key] = crits
    return out


def llm_safe_profile_summary(profile: Any) -> str:
    """Comma-separated 'field: value' summary restricted to LLM_SAFE_PROFILE_FIELDS."""
    if profile is None:
        data: Dict[str, Any] = {}
    elif hasattr(profile, "model_dump"):
        data = profile.model_dump()
    else:
        data = dict(profile)
    parts = [f"{k}: {data[k]}" for k in LLM_SAFE_PROFILE_FIELDS if data.get(k) is not None]
    return ", ".join(parts)
