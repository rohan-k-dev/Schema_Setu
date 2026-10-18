"""
Lifecycle-safe database connection management.

The pool is NOT created at import time. It is created during FastAPI lifespan
startup, so the application can start even if DATABASE_URL is missing.
Services that need the DB will receive a clear error at request time.
"""

import asyncio
import sys
from typing import Optional, AsyncGenerator
from contextlib import asynccontextmanager

from psycopg_pool import AsyncConnectionPool
from psycopg import AsyncConnection

from app.core.config import settings
from app.core.logging import get_logger
from app.core.exceptions import DatabaseError, ConfigurationError

logger = get_logger(__name__)


def use_selector_event_loop_on_windows() -> None:
    """
    Async psycopg cannot run on Windows' default ProactorEventLoop
    (Phase 8 clean-setup finding). Must run before the event loop is created;
    scripts get it on import, the server via `python -m app` (app/__main__.py).
    """
    if sys.platform == "win32" and not isinstance(
        asyncio.get_event_loop_policy(), asyncio.WindowsSelectorEventLoopPolicy
    ):
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())


use_selector_event_loop_on_windows()

# Module-level pool reference — initialized during lifespan, not at import
_pool: Optional[AsyncConnectionPool] = None


async def init_db() -> None:
    """
    Open the database connection pool during application startup.
    Uses settings.effective_database_url which prefers DATABASE_URL
    and falls back to NEON_DATABASE_URL for backward compatibility.
    """
    global _pool

    db_url = settings.effective_database_url
    if not db_url:
        logger.warning(
            "No DATABASE_URL or NEON_DATABASE_URL configured. "
            "Database features will be unavailable. "
            "Set DATABASE_URL in .env to enable database functionality."
        )
        return

    try:
        _pool = AsyncConnectionPool(
            conninfo=db_url,
            open=False,
            min_size=settings.DB_MIN_SIZE,
            max_size=settings.DB_MAX_SIZE,
            timeout=settings.DB_TIMEOUT,
        )
        await _pool.open()
        logger.info("Database connection pool opened successfully.")
    except Exception as e:
        logger.error(f"Failed to open database connection pool: {e}")
        _pool = None


async def close_db() -> None:
    """Close the database connection pool during application shutdown."""
    global _pool

    if _pool is not None:
        await _pool.close()
        _pool = None
        logger.info("Database connection pool closed.")


def is_db_available() -> bool:
    """Check if the database pool has been initialized."""
    return _pool is not None


@asynccontextmanager
async def get_db_connection() -> AsyncGenerator[AsyncConnection, None]:
    """
    Yield an async database connection from the pool.

    Raises ConfigurationError if the pool is not initialized (missing URL).
    Raises DatabaseError if the connection cannot be acquired.
    """
    if _pool is None:
        raise ConfigurationError(
            "Database is not configured. Set DATABASE_URL in your .env file."
        )

    try:
        async with _pool.connection() as conn:
            yield conn
    except ConfigurationError:
        raise
    except Exception as e:
        logger.error(f"Failed to acquire database connection: {e}")
        raise DatabaseError(f"Could not connect to database: {e}")
