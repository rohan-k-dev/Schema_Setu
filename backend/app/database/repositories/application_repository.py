"""Application Repository — application step database operations."""

from typing import List
from app.database.repositories.base import execute_query
from app.models.db import ApplicationStepRow
from app.core.logging import get_logger

logger = get_logger(__name__)


class ApplicationRepository:
    """Repository for scheme application step operations."""

    @staticmethod
    async def list_for_scheme(scheme_db_id: int) -> List[ApplicationStepRow]:
        """List all application steps for a scheme in order."""
        rows = await execute_query(
            "SELECT * FROM application_steps WHERE scheme_id = %s ORDER BY step_number",
            (scheme_db_id,),
        )
        return [ApplicationStepRow(**r) for r in rows]

    @staticmethod
    async def count_all() -> int:
        """Count total application steps."""
        rows = await execute_query("SELECT COUNT(*) as cnt FROM application_steps")
        return rows[0]["cnt"] if rows else 0
