"""
Corpus-backed offline database fixture.

Replaces the PostgreSQL-backed SchemeRepository / RuleRepository with
in-memory implementations built from the canonical validated corpus
(data/validated/schemes.json) — the same file that scripts/import_corpus.py
loads into PostgreSQL.

Each method mirrors the SQL semantics of the real repository:
  - search_by_state:   ss.state = %s (exact match) OR scheme has no state rows
  - search_by_crop:    sc.normalized_crop = LOWER(%s) OR scheme has no crop rows
  - ORDER BY name
so offline evaluation exercises the same candidate sets as a real database.

The fixture can also simulate failure (raise) and latency (sleep) for the
retrieval failure matrix and the parallel-retrieval benchmark.
"""

import asyncio
import contextlib
import json
from typing import Any, Dict, List, Optional

from evaluation import CORPUS_PATH
from app.models.db import (
    SchemeRow, EligibilityRuleRow, SchemeDocumentRow, ApplicationStepRow,
    SchemeBenefitRow,
)


class CorpusDB:
    """In-memory view of the canonical corpus with repository-shaped queries."""

    def __init__(self, corpus_path: str = CORPUS_PATH):
        with open(corpus_path, encoding="utf-8") as f:
            self.raw: List[Dict[str, Any]] = json.load(f)
        self.fail: bool = False
        self.delay_s: float = 0.0
        self.calls: int = 0
        self._schemes: Dict[str, SchemeRow] = {}
        self._rules: Dict[str, List[EligibilityRuleRow]] = {}
        self._docs: Dict[str, List[SchemeDocumentRow]] = {}
        self._steps: Dict[str, List[ApplicationStepRow]] = {}
        self._benefits: Dict[str, List[SchemeBenefitRow]] = {}
        self._build()

    # ─── construction ────────────────────────────────────────

    def _build(self) -> None:
        rule_pk = 1
        for db_id, s in enumerate(self.raw, start=1):
            sid = s["scheme_id"]
            self._schemes[sid] = SchemeRow(
                id=db_id,
                scheme_id=sid,
                name=s["name"],
                short_name=s.get("short_name"),
                description=s.get("description") or "",
                ministry=s.get("ministry"),
                level=s.get("level"),
                status=s.get("status", "ACTIVE"),
                eligibility_summary=s.get("eligibility_summary"),
                official_url=s.get("official_url"),
                application_url=s.get("application_url"),
                application_mode=s.get("application_mode") or None,
                aadhaar_requirement=s.get("aadhaar_requirement"),
                last_verified_at=s.get("last_verified_at"),
                scheme_type=s.get("scheme_type"),
                possible_duplicate=bool(s.get("possible_duplicate")),
                needs_review=bool(s.get("needs_review")),
            )
            rules = []
            for order, r in enumerate(s.get("eligibility_rules", [])):
                rules.append(EligibilityRuleRow(
                    id=rule_pk, scheme_id=db_id, rule_id=r.get("rule_id"),
                    field_name=r["field"], operator=r.get("operator", "UNKNOWN"),
                    value_json=r.get("value"), logical_group=r.get("logical_group", "AND"),
                    required=r.get("required", True), source_text=r.get("source_text"),
                    unit=r.get("unit"), original_value=r.get("original_value"),
                    original_unit=r.get("original_unit"), rule_order=order,
                ))
                rule_pk += 1
            self._rules[sid] = rules
            self._docs[sid] = [
                SchemeDocumentRow(id=i + 1, scheme_id=db_id,
                                  name=d["name"] if isinstance(d, dict) else str(d),
                                  mandatory=d.get("mandatory", True) if isinstance(d, dict) else True,
                                  description=d.get("description") if isinstance(d, dict) else None,
                                  source_text=d.get("source_text") if isinstance(d, dict) else None,
                                  document_order=i)
                for i, d in enumerate(s.get("required_documents", []))
            ]
            self._steps[sid] = [
                ApplicationStepRow(id=i + 1, scheme_id=db_id,
                                   step_number=st.get("step_number", i + 1) if isinstance(st, dict) else i + 1,
                                   description=st.get("description", "") if isinstance(st, dict) else str(st),
                                   mode=st.get("mode") if isinstance(st, dict) else None,
                                   portal_url=st.get("url") if isinstance(st, dict) else None)
                for i, st in enumerate(s.get("application_steps", []))
            ]
            self._benefits[sid] = [
                SchemeBenefitRow(id=i + 1, scheme_id=db_id,
                                 benefit_type=str(b.get("type") or "unknown"),
                                 amount=b.get("amount"), currency=b.get("currency") or "INR",
                                 frequency=b.get("frequency"), condition=b.get("condition"),
                                 description=b.get("description") or "",
                                 source_text=b.get("source_text"), benefit_order=i)
                for i, b in enumerate(s.get("benefits", []))
            ]

    # ─── behaviour switches ──────────────────────────────────

    async def _enter(self) -> None:
        self.calls += 1
        if self.delay_s:
            await asyncio.sleep(self.delay_s)
        if self.fail:
            raise ConnectionError("Simulated database outage (evaluation fixture)")

    # ─── helpers mirroring SQL semantics ─────────────────────

    def _active_sorted(self) -> List[SchemeRow]:
        return sorted((s for s in self._schemes.values() if s.status == "ACTIVE"),
                      key=lambda s: s.name)

    def _states(self, sid: str) -> List[str]:
        return [x for x in (self._raw_by_id(sid).get("applicable_states") or [])]

    def _crops(self, sid: str) -> List[str]:
        return [c.lower().strip() for c in (self._raw_by_id(sid).get("applicable_crops") or [])]

    def _raw_by_id(self, sid: str) -> Dict[str, Any]:
        for s in self.raw:
            if s["scheme_id"] == sid:
                return s
        return {}

    def state_matches(self, sid: str, state: str) -> bool:
        states = self._states(sid)
        return (not states) or (state in states)

    def crop_matches(self, sid: str, crop: str) -> bool:
        crops = self._crops(sid)
        return (not crops) or ((crop or "").lower() in crops)

    def is_state_specific(self, sid: str) -> bool:
        return bool(self._states(sid))

    def is_crop_specific(self, sid: str) -> bool:
        return bool(self._crops(sid))

    # ─── SchemeRepository surface ────────────────────────────

    async def get_by_scheme_id(self, scheme_id: str) -> Optional[SchemeRow]:
        await self._enter()
        return self._schemes.get(scheme_id)

    async def list_active(self) -> List[SchemeRow]:
        await self._enter()
        return self._active_sorted()

    async def search_by_name(self, query: str) -> List[SchemeRow]:
        await self._enter()
        q = (query or "").lower()
        return [s for s in sorted(self._schemes.values(), key=lambda s: s.name)
                if q in s.name.lower()]

    async def search_by_alias(self, query: str) -> List[SchemeRow]:
        await self._enter()
        q = (query or "").lower()
        out = []
        for s in self._active_sorted():
            raw = self._raw_by_id(s.scheme_id)
            aliases = list(raw.get("aliases") or [])
            if raw.get("short_name"):
                aliases.append(raw["short_name"])
            if any(q in a.lower().strip() for a in aliases):
                out.append(s)
        return out

    async def search_by_state(self, state: str) -> List[SchemeRow]:
        await self._enter()
        return [s for s in self._active_sorted() if self.state_matches(s.scheme_id, state)]

    async def search_by_crop(self, crop: str) -> List[SchemeRow]:
        await self._enter()
        return [s for s in self._active_sorted() if self.crop_matches(s.scheme_id, crop)]

    async def search_by_state_and_crop(self, state: str, crop: str) -> List[SchemeRow]:
        await self._enter()
        return [s for s in self._active_sorted()
                if self.state_matches(s.scheme_id, state) and self.crop_matches(s.scheme_id, crop)]

    async def get_details_for_scheme_ids(self, scheme_ids: List[str]) -> Dict[str, Dict[str, Any]]:
        """Batch detail loader (documents, steps, benefits) keyed by scheme_id."""
        await self._enter()
        return {
            sid: {
                "states": self._states(sid),
                "crops": self._crops(sid),
                "documents": list(self._docs.get(sid, [])),
                "application_steps": list(self._steps.get(sid, [])),
                "benefits": list(self._benefits.get(sid, [])),
            }
            for sid in scheme_ids if sid in self._schemes
        }

    async def health_check(self) -> bool:
        return not self.fail

    # ─── RuleRepository surface ──────────────────────────────

    async def list_for_scheme_by_sid(self, scheme_id: str) -> List[EligibilityRuleRow]:
        await self._enter()
        return list(self._rules.get(scheme_id, []))

    async def list_for_scheme_ids(self, scheme_ids: List[str]) -> Dict[str, List[EligibilityRuleRow]]:
        await self._enter()
        return {sid: list(self._rules.get(sid, [])) for sid in scheme_ids}

    # ─── direct (non-async) accessors for runners ────────────

    def rules_for(self, scheme_id: str) -> List[EligibilityRuleRow]:
        return list(self._rules.get(scheme_id, []))

    def scheme_ids(self) -> List[str]:
        return sorted(self._schemes)

    def official_url(self, scheme_id: str) -> Optional[str]:
        row = self._schemes.get(scheme_id)
        return row.official_url if row else None


_SCHEME_METHODS = [
    "get_by_scheme_id", "list_active", "search_by_name", "search_by_alias",
    "search_by_state", "search_by_crop", "search_by_state_and_crop",
    "get_details_for_scheme_ids", "health_check",
]


@contextlib.contextmanager
def patched_repositories(db: CorpusDB):
    """
    Route SchemeRepository / RuleRepository static methods to the fixture.

    Patches the class attributes so every importer (db_retriever,
    eligibility_agent, api/schemes) sees the fixture.
    """
    from app.database.repositories.scheme_repository import SchemeRepository
    from app.database.repositories.rule_repository import RuleRepository

    saved = []
    for name in _SCHEME_METHODS:
        saved.append((SchemeRepository, name, SchemeRepository.__dict__.get(name)))
        setattr(SchemeRepository, name, staticmethod(getattr(db, name)))
    for name in ("list_for_scheme_by_sid", "list_for_scheme_ids"):
        saved.append((RuleRepository, name, RuleRepository.__dict__.get(name)))
        setattr(RuleRepository, name, staticmethod(getattr(db, name)))
    try:
        yield db
    finally:
        for cls, name, original in saved:
            if original is None:
                with contextlib.suppress(AttributeError):
                    delattr(cls, name)
            else:
                setattr(cls, name, original)
