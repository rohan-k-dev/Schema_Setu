"""Rule Repository — eligibility rule database operations."""

from typing import Dict, List
from app.database.repositories.base import execute_query
from app.models.db import EligibilityRuleRow
from app.core.logging import get_logger

logger = get_logger(__name__)


class RuleRepository:
    """Repository for eligibility rule operations."""

    @staticmethod
    async def list_for_scheme(scheme_db_id: int) -> List[EligibilityRuleRow]:
        """List all eligibility rules for a scheme (by DB id)."""
        rows = await execute_query(
            "SELECT * FROM eligibility_rules WHERE scheme_id = %s ORDER BY rule_order",
            (scheme_db_id,),
        )
        return [EligibilityRuleRow(**r) for r in rows]

    @staticmethod
    async def list_for_scheme_by_sid(scheme_id: str) -> List[EligibilityRuleRow]:
        """List all eligibility rules for a scheme (by scheme_id string)."""
        rows = await execute_query(
            """SELECT er.* FROM eligibility_rules er
               JOIN schemes s ON er.scheme_id = s.id
               WHERE s.scheme_id = %s
               ORDER BY er.rule_order""",
            (scheme_id,),
        )
        return [EligibilityRuleRow(**r) for r in rows]

    @staticmethod
    async def list_for_scheme_ids(scheme_ids: List[str]) -> Dict[str, List[EligibilityRuleRow]]:
        """Rules for many schemes in one query: {scheme_id: [rules in rule_order]}."""
        if not scheme_ids:
            return {}
        rows = await execute_query(
            """SELECT s.scheme_id AS sid, er.* FROM eligibility_rules er
               JOIN schemes s ON er.scheme_id = s.id
               WHERE s.scheme_id = ANY(%s)
               ORDER BY s.scheme_id, er.rule_order""",
            (list(scheme_ids),),
        )
        out: Dict[str, List[EligibilityRuleRow]] = {sid: [] for sid in scheme_ids}
        for r in rows:
            sid = r.pop("sid")
            out.setdefault(sid, []).append(EligibilityRuleRow(**r))
        return out

    @staticmethod
    async def count_all() -> int:
        """Count total eligibility rules in the database."""
        rows = await execute_query("SELECT COUNT(*) as cnt FROM eligibility_rules")
        return rows[0]["cnt"] if rows else 0
