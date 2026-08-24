import sys
from logging.config import fileConfig
from pathlib import Path

from sqlalchemy import engine_from_config, pool

from alembic import context

# Make `app` importable regardless of the current working directory the migration
# runner was invoked from (e.g. `uv run --project backend alembic ...` from the repo
# root does not chdir into backend/, unlike `cd backend && uv run alembic ...`).
BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.config import settings  # noqa: E402
from app.db import Base  # noqa: E402

# Import every model module so they register on Base.metadata before autogenerate runs.
from app.models import (  # noqa: E402, F401
    AuditLog,
    Classification,
    EvalExample,
    Extraction,
    Record,
    RoutingDecision,
    Rule,
    Source,
)

# this is the Alembic Config object, which provides
# access to the values within the .ini file in use.
config = context.config

# Interpret the config file for Python logging, if it declares logging sections —
# a minimal delegating ini (e.g. a repo-root one that just points script_location
# here) may not, and that's fine, it just skips log configuration.
if config.config_file_name is not None and config.file_config.has_section("loggers"):
    fileConfig(config.config_file_name)

target_metadata = Base.metadata

# The app runs on the async asyncpg driver; Alembic's migration runner is sync.
# Swap the driver here rather than maintaining two URLs in .env.
sync_database_url = settings.database_url.replace("postgresql+asyncpg://", "postgresql+psycopg://")
config.set_main_option("sqlalchemy.url", sync_database_url)


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode.

    This configures the context with just a URL
    and not an Engine, though an Engine is acceptable
    here as well.  By skipping the Engine creation
    we don't even need a DBAPI to be available.

    Calls to context.execute() here emit the given string to the
    script output.

    """
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode.

    In this scenario we need to create an Engine
    and associate a connection with the context.

    """
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
