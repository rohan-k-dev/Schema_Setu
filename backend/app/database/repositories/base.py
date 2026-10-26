"""
Base repository helper — shared execute/fetch logic.

All SQL is parameterized. No raw string formatting of user input.
"""

from typing import List, Dict, Any, Optional
from psycopg import AsyncConnection
from psycopg.rows import dict_row

from app.database.connection import get_db_connection, is_db_available
from app.core.logging import get_logger

logger = get_logger(__name__)


async def execute_query(
    query: str,
    params: tuple = (),
) -> List[Dict[str, Any]]:
    """Execute a SELECT query and return list of dicts."""
    if not is_db_available():
        logger.warning("Database not available, returning empty results.")
        return []
    try:
        async with get_db_connection() as conn:
            async with conn.cursor(row_factory=dict_row) as cur:
                await cur.execute(query, params)
                return await cur.fetchall()
    except Exception as e:
        logger.error(f"Database query failed: {e}")
        return []


async def execute_query_one(
    query: str,
    params: tuple = (),
) -> Optional[Dict[str, Any]]:
    """Execute a SELECT query and return first row or None."""
    rows = await execute_query(query, params)
    return rows[0] if rows else None


async def health_check() -> bool:
    """Verify database connectivity."""
    if not is_db_available():
        return False
    try:
        async with get_db_connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute("SELECT 1;")
                result = await cur.fetchone()
                return result is not None and result[0] == 1
    except Exception as e:
        logger.error(f"Database health check failed: {e}")
        return False
