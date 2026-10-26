"""
Eligible schemes and relevant alternatives (docs/RECOMMENDATIONS.md).

Section A ("ELIGIBLE") is exactly the eligibility engine's ELIGIBLE results — nothing is added,
relaxed or re-decided here. Section B ("ALTERNATIVE") ranks the other evaluated schemes by a
transparent, deterministic relevance score so farmers also see related support they might
qualify for after checking. Schemes with a known mismatch appear in B only when they serve the
farmer's stated need or the same purpose as an eligible scheme; otherwise they go to
"NOT_MATCHING" (still visible, collapsed, with the reason). Relevance never implies eligibility.

Signals (all from stored scheme records and the farmer's own profile / question):
- assistance categories of each scheme, derived from its stored name, description, benefits and type;
- the farmer's stated need (category words in the question, occupation);
- similarity to the eligible schemes (shared category);
- state- or crop-specific targeting that matches the profile;
- profile signals named in the stored text (small and marginal farmers, women farmers);
- criteria the engine already found satisfied (passed rules).

Tiers (requirement order): 1 = strongly related, eligibility not yet confirmed (more information
needed or no structured rules); 2 = same need / similar purpose (incl. a meaningful known
mismatch); 3 = other useful schemes available in the farmer's state.
"""

from __future__ import annotations

import re
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple

from app.eligibility.models import EligibilityResult, EligibilityStatus

ELIGIBLE, ALTERNATIVE, NOT_MATCHING = "ELIGIBLE", "ALTERNATIVE", "NOT_MATCHING"

# Internal recommendation statuses (mapped from the engine's EligibilityStatus; never upgraded)
CONFIRMED_ELIGIBLE = "CONFIRMED_ELIGIBLE"
ELIGIBILITY_UNCONFIRMED = "ELIGIBILITY_UNCONFIRMED"            # relevant; no structured rules to check
ADDITIONAL_INFORMATION_REQUIRED = "ADDITIONAL_INFORMATION_REQUIRED"
KNOWN_MISMATCH = "KNOWN_MISMATCH"
SCHEME_INFORMATION_INCOMPLETE = "SCHEME_INFORMATION_INCOMPLETE"  # rule conflict / record not reviewed

# Assistance categories: label, and words matched (whole-word prefix) in stored scheme text and questions
CATEGORIES: Dict[str, Tuple[str, Tuple[str, ...]]] = {
    "crop_insurance": ("Crop insurance", ("crop insurance", "fasal bima", "crop loss", "weather based", "crop damage")),
    "life_insurance": ("Life / accident insurance", ("life insurance", "accident insurance", "jeevan jyoti",
                                                     "suraksha bima", "accidental death", "life cover")),
    "credit": ("Credit and loans", ("credit", "loan", "interest subvention", "financing", "finance facility")),
    "irrigation": ("Irrigation and water", ("irrigation", "sinchayee", "drip", "sprinkler", "water use", "per drop",
                                            "watershed")),
    "machinery": ("Farm machinery", ("machinery", "mechanization", "mechanisation", "equipment", "tractor",
                                     "implements", "custom hiring", "drone")),
    "solar_energy": ("Solar pumps and energy", ("solar", "urja")),
    "inputs": ("Seeds, fertiliser and soil", ("seed", "fertiliser", "fertilizer", "soil", "nutrient", "inputs")),
    "organic": ("Organic and natural farming", ("organic", "natural farming", "paramparagat")),
    "horticulture": ("Horticulture", ("horticulture", "fruit", "vegetable", "bamboo", "flower", "spice", "plantation")),
    "livestock": ("Livestock and dairy", ("livestock", "dairy", "cattle", "milk", "animal husbandry", "poultry", "goat",
                                         "sheep", "piggery", "bovine")),
    "fisheries": ("Fisheries", ("fish", "fisheries", "aquaculture", "matsya")),
    "income_support": ("Income support", ("income support", "samman nidhi", "sanman nidhi", "mahasanman",
                                          "investment support", "direct benefit", "financial assistance to farmers")),
    "pension": ("Pension and social security", ("pension", "maandhan", "old age", "social security")),
    "market": ("Markets and prices", ("market", "mandi", "prices", "price discovery", "procurement")),
    "infrastructure": ("Storage and infrastructure", ("infrastructure", "warehouse", "storage", "cold chain",
                                                      "post-harvest", "post harvest")),
    "training": ("Training and extension", ("training", "extension", "capacity building", "skill", "demonstration")),
    "livelihood": ("Livelihood and employment", ("employment", "livelihood", "self-help", "self help", "enterprise",
                                                 "wage")),
    "housing": ("Housing", ("housing", "awaas", "pucca house")),
    "fpo": ("Farmer producer organisations", ("farmer producer", "fpo", "collective")),
    "crop_production": ("Crop production", ("food security", "oilseed", "oil palm", "pulses", "productivity",
                                            "crop production")),
}
_BENEFIT_TYPE_CATEGORY = {"loan": "credit", "training": "training", "infrastructure": "infrastructure",
                          "input_support": "inputs"}
# Question / occupation words that state a need without naming a category word
_NEED_SYNONYMS = {"insurance": ("crop_insurance",), "pump": ("solar_energy", "irrigation"),
                  "subsidy": (), "help": (), "cow": ("livestock",), "buffalo": ("livestock",),
                  "tube well": ("irrigation",), "borewell": ("irrigation",), "warehouse": ("infrastructure",),
                  "women": (), "pension": ("pension",), "money": ("income_support",)}

_SMALL_FARMER = re.compile(r"small and marginal|small & marginal|marginal farmer|small farmer", re.I)
_WOMEN = re.compile(r"(?<![a-z])(women|woman|mahila)(?![a-z])", re.I)
SMALL_MARGINAL_ACRES = 4.94          # 2 hectares — the usual small + marginal holding limit


def _has(text: str, word: str) -> bool:
    return re.search(r"(?<![a-z])" + re.escape(word), text) is not None


def categories_of_text(text: str) -> List[str]:
    low = (text or "").lower()
    return [c for c, (_, words) in CATEGORIES.items() if any(_has(low, w) for w in words)]


def scheme_categories(candidate: Dict[str, Any]) -> List[str]:
    """Assistance categories from the stored record (name, description, benefits, type)."""
    meta = candidate.get("scheme_meta") or {}
    text = " ".join(str(x or "") for x in (candidate.get("name"), candidate.get("description"),
                                           candidate.get("benefit_summary"), meta.get("scheme_type")))
    cats = categories_of_text(text)
    for bt in meta.get("benefit_types") or []:
        c = _BENEFIT_TYPE_CATEGORY.get(bt)
        if c and c not in cats:
            cats.append(c)
    return cats


def primary_categories(candidate: Dict[str, Any]) -> List[str]:
    """The scheme's main purpose: categories named in its title / type / benefit type (else its first two)."""
    meta = candidate.get("scheme_meta") or {}
    cats = categories_of_text(f"{candidate.get('name') or ''} {meta.get('scheme_type') or ''}")
    for bt in meta.get("benefit_types") or []:
        c = _BENEFIT_TYPE_CATEGORY.get(bt)
        if c and c not in cats:
            cats.append(c)
    return cats or scheme_categories(candidate)[:2]


def stated_needs(question: str, profile: Dict[str, Any]) -> List[str]:
    """Categories the farmer asked about (question) or works in (occupation). Order kept, no duplicates."""
    text = f"{question or ''} {profile.get('occupation') or ''}".lower()
    needs = categories_of_text(text)
    for word, cats in _NEED_SYNONYMS.items():
        if _has(text, word):
            needs.extend(c for c in cats if c not in needs)
    return list(dict.fromkeys(needs))


def recommendation_status(result: EligibilityResult, meta: Dict[str, Any]) -> str:
    s = result.status
    if s == EligibilityStatus.ELIGIBLE:
        return CONFIRMED_ELIGIBLE
    if s == EligibilityStatus.NOT_ELIGIBLE:
        return KNOWN_MISMATCH
    if s == EligibilityStatus.NEEDS_MORE_INFORMATION:
        return ADDITIONAL_INFORMATION_REQUIRED
    # UNVERIFIABLE: no structured rules (relevant, can't be checked) vs conflicting rules / unreviewed record
    if result.rule_results or meta.get("needs_review"):
        return SCHEME_INFORMATION_INCOMPLETE
    return ELIGIBILITY_UNCONFIRMED


STATUS_TEXT = {
    CONFIRMED_ELIGIBLE: "Matches all published criteria we hold",
    ELIGIBILITY_UNCONFIRMED: "Eligibility not confirmed — no structured criteria to check; read the official criteria",
    ADDITIONAL_INFORMATION_REQUIRED: "Eligibility not confirmed — more information about you is needed",
    KNOWN_MISMATCH: "Does not match at least one published criterion",
    SCHEME_INFORMATION_INCOMPLETE: "Eligibility not confirmed — the scheme's information is incomplete or under review",
}


def _label(cat: str) -> str:
    return CATEGORIES[cat][0]


def _crit_names(items: Iterable[Dict[str, Any]]) -> List[str]:
    return list(dict.fromkeys(str(i.get("field")).replace("_", " ") for i in items if i.get("field")))


def _norm_name(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", re.sub(r"\(.*?\)", " ", (name or "").lower())).strip()


def build_sections(results: List[EligibilityResult], candidates: List[Dict[str, Any]],
                   profile: Optional[Dict[str, Any]], question: str,
                   rank_order: Optional[List[str]] = None) -> Dict[str, Any]:
    """
    Returns {"by_scheme": {scheme_id: annotation}, "order": [scheme_id...], "summary": {...}}.
    annotation: section, recommendation_status, status_text, relevance {tier, score, rank, reasons,
    categories, similar_to, matched_needs}, conditions_to_verify, missing_information, mismatches.
    """
    profile = dict(profile or {})
    cand = {c.get("scheme_id"): c for c in candidates or [] if isinstance(c, dict)}
    needs = stated_needs(question, profile)
    by_id: Dict[str, Dict[str, Any]] = {}

    # Duplicates: the same scheme under two ids (normalised name or a flagged duplicate) is shown once
    seen_names: Dict[str, str] = {}
    usable: List[EligibilityResult] = []
    duplicates: List[Dict[str, str]] = []
    def keep_first(r):            # the canonical record wins: not flagged, eligible, has rules, then id
        meta = (cand.get(r.scheme_id) or {}).get("scheme_meta") or {}
        return (bool(meta.get("possible_duplicate")), r.status != EligibilityStatus.ELIGIBLE,
                -len(r.rule_results), r.scheme_id)
    for r in sorted(results, key=keep_first):
        meta = (cand.get(r.scheme_id) or {}).get("scheme_meta") or {}
        key = _norm_name((cand.get(r.scheme_id) or {}).get("name") or r.scheme_name)
        if meta.get("possible_duplicate") or (key and key in seen_names):
            duplicates.append({"scheme_id": r.scheme_id, "duplicate_of": seen_names.get(key, "")})
            continue
        seen_names[key] = r.scheme_id
        usable.append(r)

    position = {sid: i for i, sid in enumerate(rank_order or [])}
    eligible = sorted((r for r in usable if r.status == EligibilityStatus.ELIGIBLE),
                      key=lambda r: (position.get(r.scheme_id, len(position)), r.scheme_id))   # ranker order
    eligible_cats: Dict[str, List[str]] = {}
    for r in eligible:
        for c in primary_categories(cand.get(r.scheme_id) or {"name": r.scheme_name}):
            eligible_cats.setdefault(c, []).append((cand.get(r.scheme_id) or {}).get("name") or r.scheme_name)

    for r in eligible:
        d = r.to_response_dict()
        optional_unknown = _crit_names(d["missing_criteria"])
        by_id[r.scheme_id] = {
            "section": ELIGIBLE, "recommendation_status": CONFIRMED_ELIGIBLE,
            "status_text": STATUS_TEXT[CONFIRMED_ELIGIBLE],
            "conditions_to_verify": ([f"Optional criteria not checked: {', '.join(optional_unknown)}"]
                                     if optional_unknown else []) +
                                    ["Exclusions and the final decision rest with the issuing department"],
            "relevance": {"categories": [_label(c) for c in scheme_categories(cand.get(r.scheme_id) or {})]},
        }

    scored = []
    for r in usable:
        if r.status == EligibilityStatus.ELIGIBLE:
            continue
        c = cand.get(r.scheme_id) or {"name": r.scheme_name}
        meta = c.get("scheme_meta") or {}
        cats = scheme_categories(c)
        matched_needs = [n for n in needs if n in cats]
        primary = primary_categories(c)
        similar = sorted({name for cat in primary for name in eligible_cats.get(cat, [])})
        targeting = set(c.get("matched_fields") or [])
        text = " ".join(str(x or "") for x in (c.get("name"), c.get("description"), c.get("eligibility_summary")))
        reasons, score = [], 0.0
        if matched_needs:
            score += 4 * len(matched_needs)
            reasons.append("Matches what you asked about: " + ", ".join(_label(n).lower() for n in matched_needs))
        if similar:
            score += 2
            shared = [cat for cat in primary if cat in eligible_cats][0]
            reasons.append(f"Similar support ({_label(shared).lower()}) to "
                           f"{', '.join(sorted(set(eligible_cats[shared]))[:2])}, which matches your details")
        if "state_targeted" in targeting and profile.get("state"):
            score += 3
            reasons.append(f"A scheme specifically for {profile['state']}")
        if "crop_targeted" in targeting and profile.get("primary_crop"):
            score += 3
            reasons.append(f"Covers your crop ({profile['primary_crop']})")
        land = profile.get("land_size_acres")
        if land is not None and land <= SMALL_MARGINAL_ACRES and _SMALL_FARMER.search(text):
            score += 1
            reasons.append(f"Aimed at small and marginal farmers (you reported {land:g} acres)")
        if str(profile.get("gender") or "").lower() in ("female", "woman", "women") and _WOMEN.search(text):
            score += 1
            reasons.append("Aimed at women farmers")
        if r.passed_rules:
            score += min(r.passed_rules, 3) * 0.5
            reasons.append(f"{r.passed_rules} published criteria already match your details")

        status = recommendation_status(r, meta)
        strongly_related = bool(matched_needs or targeting & {"state_targeted", "crop_targeted"} or r.passed_rules)
        if status == KNOWN_MISMATCH:
            section = ALTERNATIVE if (matched_needs or similar) else NOT_MATCHING
            tier = 2
            score -= 3
        elif strongly_related:
            section, tier = ALTERNATIVE, 1
        elif similar:
            section, tier = ALTERNATIVE, 2
        else:
            section, tier = ALTERNATIVE, 3
            if not reasons:
                reasons.append("Available to farmers in your state" if profile.get("state")
                               else "A farmer scheme that may apply to you")
            if cats:
                reasons.append("Offers " + ", ".join(_label(x).lower() for x in cats[:2]))

        d = r.to_response_dict()
        missing = list(dict.fromkeys((r.missing_information or []) +
                                     [str(m["field"]) for m in d["missing_criteria"] if m.get("field")]))
        mismatches = [f"{str(f.get('field')).replace('_', ' ')}: requires {f.get('required_value')}, "
                      f"you have {f.get('user_value')}" for f in d["failed_criteria"]]
        verify = []
        if status == ELIGIBILITY_UNCONFIRMED:
            verify.append("Eligibility criteria aren't available as checkable rules — read them on the official site")
        if status == SCHEME_INFORMATION_INCOMPLETE:
            verify.append("Scheme details are incomplete or awaiting review — confirm on the official site")
        if missing:
            verify.append("Tell us: " + ", ".join(m.replace("_", " ") for m in missing))
        by_id[r.scheme_id] = {
            "section": section, "recommendation_status": status, "status_text": STATUS_TEXT[status],
            "relevance": {"tier": tier, "score": round(score, 2), "reasons": reasons,
                          "categories": [_label(x) for x in cats], "similar_to": similar[:3],
                          "matched_needs": [_label(n) for n in matched_needs]},
            "missing_information": missing, "mismatches": mismatches, "conditions_to_verify": verify,
        }
        scored.append((section != ALTERNATIVE, tier, -score, r.scheme_id))

    scored.sort()
    alt_order = [sid for _, _, _, sid in scored]
    for i, sid in enumerate(a for a in alt_order if by_id[a]["section"] == ALTERNATIVE):
        by_id[sid]["relevance"]["rank"] = i + 1
    eligible_order = [r.scheme_id for r in eligible]
    return {
        "by_scheme": by_id,
        "order": eligible_order + alt_order,
        "summary": {"eligible": len(eligible),
                    "alternatives": sum(1 for a in by_id.values() if a["section"] == ALTERNATIVE),
                    "not_matching": sum(1 for a in by_id.values() if a["section"] == NOT_MATCHING),
                    "duplicates_hidden": duplicates, "stated_needs": [_label(n) for n in needs]},
    }
