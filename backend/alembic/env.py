"""
Alembic environment configuration for SchemeSetu.

Uses psycopg (async driver) with synchronous migration execution.
Reads DATABASE_URL from the project's settings module.
"""

import os
import sys
from logging.config import fileConfig
from alembic import context

# Add backend to path so we can import app modules
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from app.core.config import settings

# Alembic Config object
config = context.config

# Set up logging
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Override sqlalchemy.url from our settings
db_url = settings.effective_database_url
if db_url:
    # The project installs psycopg 3 only; SQLAlchemy maps a bare "postgresql://"
    # URL to psycopg2, so select the psycopg 3 dialect explicitly (Phase 8 fix).
    for prefix in ("postgresql://", "postgres://"):
        if db_url.startswith(prefix):
            db_url = "postgresql+psycopg://" + db_url[len(prefix):]
            break
    # ConfigParser treats "%" as interpolation; escape it for URL-encoded passwords
    config.set_main_option("sqlalchemy.url", db_url.replace("%", "%%"))


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode — generates SQL without connecting."""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=None,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode — connects to the database."""
    from sqlalchemy import create_engine

    url = config.get_main_option("sqlalchemy.url")
    if not url:
        raise RuntimeError(
            "DATABASE_URL or NEON_DATABASE_URL must be set to run migrations. "
            "Set it in .env or as an environment variable."
        )

    connectable = create_engine(url)

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=None,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
