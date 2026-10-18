"""
Scheme Repository — database operations for government schemes.

Provides typed search/retrieval using the new normalized schema.
Returns SchemeRow/SchemeDetail domain models, never raw tuples.
"""

from typing import List, Optional, Dict, Any

from app.database.repositories.base import execute_query, execute_query_one, health_check
from app.models.db import (
    SchemeRow, SchemeDetail, SchemeAliasRow, SchemeStateRow,
    SchemeCropRow, SchemeBeneficiaryRow, SchemeBenefitRow,
    EligibilityRuleRow, SchemeDocumentRow, ApplicationStepRow,
    SchemeSourceRow, SchemeDistrictRow,
)
from app.core.logging import get_logger

logger = get_logger(__name__)


def _row_to_scheme(row: Dict[str, Any]) -> SchemeRow:
    """Map a dict row to a SchemeRow model."""
    return SchemeRow(**row)


class SchemeRepository:
    """Repository for government scheme database operations (Phase 2)."""

    # ─── Single scheme retrieval ─────────────────────────────

    @staticmethod
    async def get_by_id(db_id: int) -> Optional[SchemeRow]:
        """Get a scheme by its internal database ID."""
        row = await execute_query_one(
            "SELECT * FROM schemes WHERE id = %s", (db_id,)
        )
        return _row_to_scheme(row) if row else None

    @staticmethod
    async def get_by_scheme_id(scheme_id: str) -> Optional[SchemeRow]:
        """Get a scheme by its stable canonical scheme_id."""
        row = await execute_query_one(
            "SELECT * FROM schemes WHERE scheme_id = %s", (scheme_id,)
        )
        return _row_to_scheme(row) if row else None

    # ─── Search methods ──────────────────────────────────────

    @staticmethod
    async def list_active() -> List[SchemeRow]:
        """List all active schemes."""
        rows = await execute_query(
            "SELECT * FROM schemes WHERE status = 'ACTIVE' ORDER BY name"
        )
        return [_row_to_scheme(r) for r in rows]

    @staticmethod
    async def search_by_name(query: str) -> List[SchemeRow]:
        """Search schemes by name (case-insensitive partial match)."""
        rows = await execute_query(
            "SELECT * FROM schemes WHERE LOWER(name) LIKE LOWER(%s) ORDER BY name",
            (f"%{query}%",),
        )
        return [_row_to_scheme(r) for r in rows]

    @staticmethod
    async def search_by_alias(query: str) -> List[SchemeRow]:
        """Search schemes by alias (case-insensitive partial match)."""
        rows = await execute_query(
            """SELECT DISTINCT s.* FROM schemes s
               JOIN scheme_aliases sa ON s.id = sa.scheme_id
               WHERE LOWER(sa.normalized_alias) LIKE LOWER(%s)
               ORDER BY s.name""",
            (f"%{query}%",),
        )
        return [_row_to_scheme(r) for r in rows]

    @staticmethod
    async def search_by_state(state: str) -> List[SchemeRow]:
        """
        Search schemes applicable to a state.
        Returns schemes explicitly listing the state AND central schemes
        with no state restriction (no rows in scheme_states).
        """
        rows = await execute_query(
            """SELECT DISTINCT s.* FROM schemes s
               LEFT JOIN scheme_states ss ON s.id = ss.scheme_id
               WHERE s.status = 'ACTIVE'
                 AND (
                   ss.state = %s
                   OR ss.scheme_id IS NULL
                 )
               ORDER BY s.name""",
            (state,),
        )
        return [_row_to_scheme(r) for r in rows]

    @staticmethod
    async def search_by_crop(crop: str) -> List[SchemeRow]:
        """
        Search schemes applicable to a crop.
        Returns schemes explicitly listing the crop AND schemes
        with no crop restriction (no rows in scheme_crops).
        """
        rows = await execute_query(
            """SELECT DISTINCT s.* FROM schemes s
               LEFT JOIN scheme_crops sc ON s.id = sc.scheme_id
               WHERE s.status = 'ACTIVE'
                 AND (
                   sc.normalized_crop = LOWER(%s)
                   OR sc.scheme_id IS NULL
                 )
               ORDER BY s.name""",
            (crop,),
        )
        return [_row_to_scheme(r) for r in rows]

    @staticmethod
    async def search_by_state_and_crop(state: str, crop: str) -> List[SchemeRow]:
        """
        Search schemes applicable to a state AND crop.
        Central schemes with no state/crop restriction are included.
        """
        rows = await execute_query(
            """SELECT DISTINCT s.* FROM schemes s
               LEFT JOIN scheme_states ss ON s.id = ss.scheme_id
               LEFT JOIN scheme_crops sc ON s.id = sc.scheme_id
               WHERE s.status = 'ACTIVE'
                 AND (ss.state = %s OR ss.scheme_id IS NULL
                      OR NOT EXISTS (SELECT 1 FROM scheme_states WHERE scheme_id = s.id))
                 AND (sc.normalized_crop = LOWER(%s) OR sc.scheme_id IS NULL
                      OR NOT EXISTS (SELECT 1 FROM scheme_crops WHERE scheme_id = s.id))
               ORDER BY s.name""",
            (state, crop),
        )
        return [_row_to_scheme(r) for r in rows]

    # ─── Complete scheme detail ──────────────────────────────

    @staticmethod
    async def get_with_details(scheme_id: str) -> Optional[SchemeDetail]:
        """
        Get a complete scheme with all child records.
        Uses batched queries per table (acceptable for small corpus).
        """
        scheme_row = await execute_query_one(
            "SELECT * FROM schemes WHERE scheme_id = %s", (scheme_id,)
        )
        if not scheme_row:
            return None

        db_id = scheme_row["id"]
        scheme = _row_to_scheme(scheme_row)

        # Fetch all child records in parallel-ish batches
        aliases_rows = await execute_query(
            "SELECT * FROM scheme_aliases WHERE scheme_id = %s ORDER BY alias", (db_id,)
        )
        states_rows = await execute_query(
            "SELECT * FROM scheme_states WHERE scheme_id = %s ORDER BY state", (db_id,)
        )
        districts_rows = await execute_query(
            "SELECT * FROM scheme_districts WHERE scheme_id = %s", (db_id,)
        )
        crops_rows = await execute_query(
            "SELECT * FROM scheme_crops WHERE scheme_id = %s ORDER BY crop", (db_id,)
        )
        beneficiaries_rows = await execute_query(
            "SELECT * FROM scheme_beneficiaries WHERE scheme_id = %s", (db_id,)
        )
        benefits_rows = await execute_query(
            "SELECT * FROM scheme_benefits WHERE scheme_id = %s ORDER BY benefit_order", (db_id,)
        )
        rules_rows = await execute_query(
            "SELECT * FROM eligibility_rules WHERE scheme_id = %s ORDER BY rule_order", (db_id,)
        )
        docs_rows = await execute_query(
            "SELECT * FROM scheme_documents WHERE scheme_id = %s ORDER BY document_order", (db_id,)
        )
        steps_rows = await execute_query(
            "SELECT * FROM application_steps WHERE scheme_id = %s ORDER BY step_number", (db_id,)
        )
        sources_rows = await execute_query(
            "SELECT * FROM scheme_sources WHERE scheme_id = %s", (db_id,)
        )

        return SchemeDetail(
            scheme=scheme,
            aliases=[r["alias"] for r in aliases_rows],
            states=[r["state"] for r in states_rows],
            districts=[SchemeDistrictRow(**r) for r in districts_rows],
            crops=[r["crop"] for r in crops_rows],
            beneficiaries=[r["beneficiary_type"] for r in beneficiaries_rows],
            benefits=[SchemeBenefitRow(**r) for r in benefits_rows],
            eligibility_rules=[EligibilityRuleRow(**r) for r in rules_rows],
            documents=[SchemeDocumentRow(**r) for r in docs_rows],
            application_steps=[ApplicationStepRow(**r) for r in steps_rows],
            sources=[SchemeSourceRow(**r) for r in sources_rows],
        )

    @staticmethod
    async def get_details_for_scheme_ids(scheme_ids: List[str]) -> Dict[str, Dict[str, Any]]:
        """
        Batch-load targeting and display details for many schemes (5 queries total).

        Returns {scheme_id: {"states", "crops", "documents", "application_steps", "benefits"}}.
        Used by retrieval to rank state/crop-targeted schemes before truncation and to
        fill scheme cards (Phase 7 BUG-006 / BUG-012).
        """
        if not scheme_ids:
            return {}
        ids = list(scheme_ids)
        out: Dict[str, Dict[str, Any]] = {
            sid: {"states": [], "crops": [], "documents": [], "application_steps": [], "benefits": []}
            for sid in ids
        }
        queries = {
            "states": ("SELECT s.scheme_id AS sid, ss.state FROM scheme_states ss "
                       "JOIN schemes s ON s.id = ss.scheme_id WHERE s.scheme_id = ANY(%s) ORDER BY ss.state"),
            "crops": ("SELECT s.scheme_id AS sid, sc.normalized_crop FROM scheme_crops sc "
                      "JOIN schemes s ON s.id = sc.scheme_id WHERE s.scheme_id = ANY(%s) ORDER BY sc.crop"),
            "documents": ("SELECT s.scheme_id AS sid, d.* FROM scheme_documents d "
                          "JOIN schemes s ON s.id = d.scheme_id WHERE s.scheme_id = ANY(%s) "
                          "ORDER BY d.document_order"),
            "application_steps": ("SELECT s.scheme_id AS sid, a.* FROM application_steps a "
                                  "JOIN schemes s ON s.id = a.scheme_id WHERE s.scheme_id = ANY(%s) "
                                  "ORDER BY a.step_number"),
            "benefits": ("SELECT s.scheme_id AS sid, b.* FROM scheme_benefits b "
                         "JOIN schemes s ON s.id = b.scheme_id WHERE s.scheme_id = ANY(%s) "
                         "ORDER BY b.benefit_order"),
        }
        row_models = {"documents": SchemeDocumentRow, "application_steps": ApplicationStepRow,
                      "benefits": SchemeBenefitRow}
        for key, sql in queries.items():
            for r in await execute_query(sql, (ids,)):
                sid = r.pop("sid")
                if sid not in out:
                    continue
                if key == "states":
                    out[sid]["states"].append(r["state"])
                elif key == "crops":
                    out[sid]["crops"].append(r["normalized_crop"])
                else:
                    out[sid][key].append(row_models[key](**r))
        return out

    # ─── Backward compatibility for health endpoint ──────────

    @staticmethod
    async def health_check() -> bool:
        """Verify database connectivity."""
        return await health_check()

    # ─── Legacy compatibility adapter ────────────────────────

    @staticmethod
    async def search_legacy(state_name: str, crop: str) -> List[Dict[str, Any]]:
        """
        Legacy-compatible search that returns dicts matching the old schema.
        Maps new normalized fields to old column names for existing code.
        """
        schemes = await SchemeRepository.search_by_state_and_crop(state_name, crop)
        results = []
        for s in schemes:
            results.append({
                "scheme_id": s.scheme_id,
                "title": s.name,
                "ministry": s.ministry or "",
                "benefits_details": "",  # Now in scheme_benefits table
                "eligibility_criteria_raw": s.eligibility_summary or "",
                "state_specific": "",  # Now in scheme_states table
                "application_link": s.application_url or s.official_url or "",
            })
        return results
