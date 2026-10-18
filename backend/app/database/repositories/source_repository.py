"""Source Repository — scheme source/provenance database operations."""

from typing import List, Optional
from app.database.repositories.base import execute_query, execute_query_one
from app.models.db import SchemeSourceRow
from app.core.logging import get_logger

logger = get_logger(__name__)


class SourceRepository:
    """Repository for scheme source provenance operations."""

    @staticmethod
    async def list_for_scheme(scheme_db_id: int) -> List[SchemeSourceRow]:
        """List all sources for a scheme."""
        rows = await execute_query(
            "SELECT * FROM scheme_sources WHERE scheme_id = %s ORDER BY is_primary DESC, source_type",
            (scheme_db_id,),
        )
        return [SchemeSourceRow(**r) for r in rows]

    @staticmethod
    async def get_primary_source(scheme_db_id: int) -> Optional[SchemeSourceRow]:
        """Get the primary source for a scheme."""
        row = await execute_query_one(
            """SELECT * FROM scheme_sources
               WHERE scheme_id = %s AND is_primary = true
               LIMIT 1""",
            (scheme_db_id,),
        )
        if row:
            return SchemeSourceRow(**row)
        # Fallback: get the first official source
        row = await execute_query_one(
            """SELECT * FROM scheme_sources
               WHERE scheme_id = %s AND source_type LIKE 'OFFICIAL%%'
               ORDER BY source_type LIMIT 1""",
            (scheme_db_id,),
        )
        return SchemeSourceRow(**row) if row else None

    @staticmethod
    async def count_all() -> int:
        """Count total sources."""
        rows = await execute_query("SELECT COUNT(*) as cnt FROM scheme_sources")
        return rows[0]["cnt"] if rows else 0
