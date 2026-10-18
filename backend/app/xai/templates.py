"""
XAI deterministic templates — fallback explanations (§58, §193).

Template-based explanations that work without any LLM.
Every template is grounded in structured evidence.
"""

from typing import List, Dict, Any

from app.eligibility.models import EligibilityStatus, RuleStatus

# ─── Field display names ─────────────────────────────────────

FIELD_LABELS = {
    "state": "State",
    "district": "District",
    "primary_crop": "Crop",
    "land_size_acres": "Land size",
    "annual_income": "Annual income",
    "category": "Category",
    "gender": "Gender",
    "occupation": "Occupation",
    "has_aadhaar": "Aadhaar status",
    "age": "Age",
    "has_land": "Land holding",
    "residence": "Residence",
}


def display_value(value: Any) -> str:
    """Human-readable value: 2.0 → "2", True → "Yes", ["sc", "st"] → "sc, st", "tamil nadu" → "Tamil Nadu"."""
    if isinstance(value, bool):
        return "Yes" if value else "No"
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    if isinstance(value, list):
        return ", ".join(display_value(v) for v in value)
    if isinstance(value, str) and value.islower() and len(value) > 3:
        return value.title()
    return "" if value is None else str(value)


def _field_label(field: str) -> str:
    """Get human-readable field label."""
    return FIELD_LABELS.get(field, field.replace("_", " ").title())


# ─── Status summaries (§193) ─────────────────────────────────

STATUS_SUMMARIES = {
    EligibilityStatus.ELIGIBLE:
        "Your profile matches the available eligibility criteria.",
    EligibilityStatus.NOT_ELIGIBLE:
        "One or more published criteria do not match the current profile.",
    EligibilityStatus.NEEDS_MORE_INFORMATION:
        "More information is needed to complete the assessment.",
    EligibilityStatus.UNVERIFIABLE:
        "The available structured criteria are insufficient to make a reliable assessment.",
}


def generate_summary(status: EligibilityStatus) -> str:
    """Generate status summary text (§193)."""
    return STATUS_SUMMARIES.get(status, "Eligibility could not be determined.")


def format_matched_criteria(matched: List[Dict[str, Any]]) -> List[str]:
    """Format matched criteria for display (§124)."""
    items = []
    for m in matched:
        field = _field_label(m.get("field", ""))
        user_val = display_value(m.get("user_value", ""))
        items.append(f"✓ {field}: {user_val}")
    return items


def format_failed_criteria(failed: List[Dict[str, Any]]) -> List[str]:
    """Format failed criteria for display (§125)."""
    items = []
    for f in failed:
        field = _field_label(f.get("field", ""))
        user_val = display_value(f.get("user_value", ""))
        req_val = display_value(f.get("required_value", ""))
        source = f.get("source_text", "")

        text = f"✗ {field}: Profile has {user_val}"
        if req_val:
            text += f", required: {req_val}"
        if source:
            text += f" ({source})"
        items.append(text)
    return items


def format_missing_criteria(missing: List[Dict[str, Any]]) -> List[str]:
    """Format missing criteria for display (§126)."""
    items = []
    for m in missing:
        field = _field_label(m.get("field", ""))
        req_val = display_value(m.get("required_value", ""))
        text = f"○ {field}"
        if req_val:
            text += f" (required: {req_val})"
        items.append(text)
    return items


def generate_template_explanation(
    status: EligibilityStatus,
    matched: List[Dict[str, Any]],
    failed: List[Dict[str, Any]],
    missing: List[Dict[str, Any]],
    scheme_name: str = "",
) -> str:
    """
    Generate a complete deterministic explanation (§58).

    No LLM required — pure template-based.
    """
    parts = []

    # Summary
    parts.append(generate_summary(status))

    # Scheme name
    if scheme_name:
        parts.append(f"\nScheme: {scheme_name}")

    # Matched criteria
    if matched:
        parts.append("\nMatched criteria:")
        parts.extend(format_matched_criteria(matched))

    if status == EligibilityStatus.ELIGIBLE:
        # A scheme can be ELIGIBLE while some rules failed or are unknown, but
        # only when those rules were OR-alternatives or optional. Say so
        # instead of "Does not match", which would contradict the status.
        if failed:
            parts.append("\nOther options (not needed, another matching option was found):")
            parts.extend("– " + line[2:] for line in format_failed_criteria(failed))
        if missing:
            parts.append("\nOptional details not provided:")
            parts.extend(format_missing_criteria(missing))
        return "\n".join(parts)

    # Failed criteria
    if failed:
        parts.append("\nDoes not match:")
        parts.extend(format_failed_criteria(failed))

    # Missing information
    if missing:
        parts.append("\nMore information needed:")
        parts.extend(format_missing_criteria(missing))

    return "\n".join(parts)
