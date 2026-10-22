from __future__ import annotations

from logging.config import fileConfig
import os
from pathlib import Path
import sys

from alembic import context
from sqlalchemy import engine_from_config, pool


BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app import models  # noqa: E402,F401
from app.config import database_connect_args, load_database_settings  # noqa: E402
from app.database import Base  # noqa: E402


config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name, disable_existing_loggers=False)

migration_environment = dict(os.environ)
migration_url = migration_environment.get("MIGRATION_DATABASE_URL", "").strip()
if migration_url:
    migration_environment["DATABASE_URL"] = migration_url
settings = load_database_settings(migration_environment)
config.set_main_option(
    "sqlalchemy.url",
    settings.url.replace("%", "%%"),
)
target_metadata = Base.metadata


def run_migrations_offline() -> None:
    context.configure(
        url=settings.url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        compare_server_default=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
        pool_pre_ping=True,
        connect_args=database_connect_args(settings),
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
            compare_server_default=True,
        )
        with context.begin_transaction():
            context.run_migrations()
    connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
