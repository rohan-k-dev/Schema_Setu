import os
import logging
from psycopg_pool import AsyncConnectionPool
from contextlib import asynccontextmanager

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Fetch the connection string injected by Docker/.env
DATABASE_URL = os.getenv("NEON_DATABASE_URL")

if not DATABASE_URL:
    raise ValueError("NEON_DATABASE_URL environment variable is not set.")

# Initialize the async connection pool
# open=False ensures it waits for the FastAPI lifespan to start it
pool = AsyncConnectionPool(conninfo=DATABASE_URL, open=False)

@asynccontextmanager
async def get_db_connection():
    """
    Yields a direct, async PostgreSQL connection from the pool.
    Use this as a FastAPI Dependency.
    """
    async with pool.connection() as conn:
        yield conn

async def init_db():
    """Open the connection pool on application startup."""
    await pool.open()

async def close_db():
    """Close the connection pool on application shutdown."""
    await pool.close()