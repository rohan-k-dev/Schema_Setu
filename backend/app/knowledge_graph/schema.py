"""
Knowledge Graph Schema — Node types, edge types, and ID generation.

Defines the controlled vocabulary for the SchemeSetu Knowledge Graph.
All node IDs are deterministic and stable across builds.
"""

from enum import Enum
from typing import Optional


# ─── Node Types ──────────────────────────────────────────────

class NodeType(str, Enum):
    """Controlled node types for the Knowledge Graph."""
    SCHEME = "SCHEME"
    STATE = "STATE"
    DISTRICT = "DISTRICT"
    CROP = "CROP"
    BENEFICIARY = "BENEFICIARY"
    CATEGORY = "CATEGORY"
    OCCUPATION = "OCCUPATION"
    GENDER = "GENDER"
    MINISTRY = "MINISTRY"
    DEPARTMENT = "DEPARTMENT"
    BENEFIT = "BENEFIT"
    DOCUMENT = "DOCUMENT"
    ELIGIBILITY_RULE = "ELIGIBILITY_RULE"
    SOURCE = "SOURCE"
    COUNTRY = "COUNTRY"


# ─── Edge Types ──────────────────────────────────────────────

class EdgeType(str, Enum):
    """Controlled edge/relationship types."""
    APPLIES_TO_STATE = "APPLIES_TO_STATE"
    APPLIES_TO_DISTRICT = "APPLIES_TO_DISTRICT"
    TARGETS_CROP = "TARGETS_CROP"
    TARGETS_BENEFICIARY = "TARGETS_BENEFICIARY"
    TARGETS_CATEGORY = "TARGETS_CATEGORY"
    TARGETS_OCCUPATION = "TARGETS_OCCUPATION"
    TARGETS_GENDER = "TARGETS_GENDER"
    OFFERED_BY_MINISTRY = "OFFERED_BY_MINISTRY"
    BELONGS_TO_DEPARTMENT = "BELONGS_TO_DEPARTMENT"
    PROVIDES_BENEFIT = "PROVIDES_BENEFIT"
    REQUIRES_DOCUMENT = "REQUIRES_DOCUMENT"
    HAS_ELIGIBILITY_RULE = "HAS_ELIGIBILITY_RULE"
    HAS_SOURCE = "HAS_SOURCE"
    LOCATED_IN_STATE = "LOCATED_IN_STATE"  # State → Country
    DISTRICT_OF = "DISTRICT_OF"            # District → State
    PART_OF = "PART_OF"                    # State → Country
    GLOBAL_APPLICABILITY = "GLOBAL_APPLICABILITY"  # Central scheme → Country


# ─── Deterministic Node ID Generation ────────────────────────

def _normalize_for_id(value: str) -> str:
    """Normalize a string for use as a graph node ID component."""
    if not value:
        return ""
    return (
        value.upper()
        .strip()
        .replace(" ", "_")
        .replace("-", "_")
        .replace("(", "")
        .replace(")", "")
        .replace(",", "")
        .replace(".", "")
        .replace("'", "")
        .replace('"', "")
        .replace("/", "_")
        .replace("&", "AND")
    )


def make_node_id(node_type: NodeType, *parts: str) -> str:
    """
    Create a deterministic node ID.

    Examples:
        make_node_id(NodeType.SCHEME, "PM_KISAN") → "SCHEME:PM_KISAN"
        make_node_id(NodeType.STATE, "Karnataka") → "STATE:KARNATAKA"
        make_node_id(NodeType.DISTRICT, "Karnataka", "Mandya") → "DISTRICT:KARNATAKA:MANDYA"
    """
    normalized_parts = [_normalize_for_id(p) for p in parts if p]
    return f"{node_type.value}:{':'.join(normalized_parts)}"


def make_scheme_id(scheme_id: str) -> str:
    """Create scheme node ID from the canonical scheme_id."""
    return f"{NodeType.SCHEME.value}:{scheme_id}"


def make_state_id(state: str) -> str:
    return make_node_id(NodeType.STATE, state)


def make_district_id(state: str, district: str) -> str:
    return make_node_id(NodeType.DISTRICT, state, district)


def make_crop_id(crop: str) -> str:
    return make_node_id(NodeType.CROP, crop)


def make_beneficiary_id(beneficiary: str) -> str:
    return make_node_id(NodeType.BENEFICIARY, beneficiary)


def make_category_id(category: str) -> str:
    return make_node_id(NodeType.CATEGORY, category)


def make_occupation_id(occupation: str) -> str:
    return make_node_id(NodeType.OCCUPATION, occupation)


def make_gender_id(gender: str) -> str:
    return make_node_id(NodeType.GENDER, gender)


def make_ministry_id(ministry: str) -> str:
    return make_node_id(NodeType.MINISTRY, ministry)


def make_department_id(department: str) -> str:
    return make_node_id(NodeType.DEPARTMENT, department)


def make_benefit_id(benefit_type: str) -> str:
    return make_node_id(NodeType.BENEFIT, benefit_type)


def make_document_id(document_name: str) -> str:
    return make_node_id(NodeType.DOCUMENT, document_name)


def make_rule_id(scheme_id: str, rule_index: int, rule_id: Optional[str] = None) -> str:
    """Create rule node ID. Uses rule_id if available, else scheme_id + index."""
    if rule_id:
        return f"{NodeType.ELIGIBILITY_RULE.value}:{rule_id}"
    return f"{NodeType.ELIGIBILITY_RULE.value}:{scheme_id}_{rule_index}"


def make_source_id(source_id: str) -> str:
    return make_node_id(NodeType.SOURCE, source_id)


def make_country_id(country: str = "INDIA") -> str:
    return f"{NodeType.COUNTRY.value}:{country}"


# ─── Validation helpers ──────────────────────────────────────

VALID_NODE_TYPES = {nt.value for nt in NodeType}
VALID_EDGE_TYPES = {et.value for et in EdgeType}


def is_valid_node_type(node_type: str) -> bool:
    return node_type in VALID_NODE_TYPES


def is_valid_edge_type(edge_type: str) -> bool:
    return edge_type in VALID_EDGE_TYPES


# Values to skip (don't create graph nodes for these)
SKIP_VALUES = {"unknown", "none", "null", "", "n/a", "na", "not specified", "not available"}


def should_skip_value(value: str) -> bool:
    """Return True if this value should NOT create a graph node."""
    if not value:
        return True
    return value.strip().lower() in SKIP_VALUES
