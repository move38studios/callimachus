"""Alembic environment for Callimachus.

Reads `CALLIMACHUS_DATABASE_URL` from the environment if set, otherwise
falls back to alembic.ini's `sqlalchemy.url`. Targets the SQLModel
metadata so `alembic revision --autogenerate` works.

The `vec_chunks` virtual table is created by `db.init_db`, not by
migrations — sqlite-vec virtual tables don't fit Alembic's autogenerate
model. Migrations cover the standard SQLModel-managed tables only.
"""

from __future__ import annotations

import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool
from sqlmodel import SQLModel

# Import models for the side effect of populating SQLModel.metadata
# with every table; the import looks unused but is intentional.
from callimachus.storage import (
    models as _models,  # noqa: F401  # pyright: ignore[reportUnusedImport]
)

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Allow env override of the DB URL — useful for tests and CI.
_env_url = os.environ.get("CALLIMACHUS_DATABASE_URL")
if _env_url:
    config.set_main_option("sqlalchemy.url", _env_url)

target_metadata = SQLModel.metadata


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        render_as_batch=True,  # SQLite needs batch mode for ALTER ops
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            render_as_batch=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
