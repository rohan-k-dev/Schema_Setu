"""Document Repository — required document database operations."""

from typing import List
from app.database.repositories.base import execute_query
from app.models.db import SchemeDocumentRow
from app.core.logging import get_logger

logger = get_logger(__name__)


class DocumentRepository:
    """Repository for scheme required document operations."""

    @staticmethod
    async def list_for_scheme(scheme_db_id: int) -> List[SchemeDocumentRow]:
        """List all required documents for a scheme."""
        rows = await execute_query(
            "SELECT * FROM scheme_documents WHERE scheme_id = %s ORDER BY document_order",
            (scheme_db_id,),
        )
        return [SchemeDocumentRow(**r) for r in rows]

    @staticmethod
    async def count_all() -> int:
        """Count total documents."""
        rows = await execute_query("SELECT COUNT(*) as cnt FROM scheme_documents")
        return rows[0]["cnt"] if rows else 0
