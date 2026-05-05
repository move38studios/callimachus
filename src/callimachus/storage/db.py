"""Database connection — SQLite + sqlite-vec extension auto-loading.

The vec extension must be loaded on every connection (SQLite extensions
don't persist), so we hook the SQLAlchemy `connect` event.
"""

from __future__ import annotations

from collections.abc import Generator
from contextlib import contextmanager
from typing import Any

import sqlite_vec
from sqlalchemy import event, text
from sqlalchemy.engine import Engine
from sqlmodel import Session, SQLModel, create_engine

from callimachus.storage.models import EMBEDDING_DIM


def _attach_sqlite_vec(dbapi_conn: Any) -> None:
    """SQLAlchemy `connect` listener — load sqlite-vec on every new connection."""
    dbapi_conn.enable_load_extension(True)
    sqlite_vec.load(dbapi_conn)
    dbapi_conn.enable_load_extension(False)


def _on_engine_connect(dbapi_conn: Any, _rec: Any) -> None:
    _attach_sqlite_vec(dbapi_conn)


def make_engine(database_url: str = "sqlite:///library.db") -> Engine:
    """Create a SQLAlchemy engine with sqlite-vec auto-loaded on connect."""
    engine = create_engine(database_url, connect_args={"check_same_thread": False})
    event.listen(engine, "connect", _on_engine_connect)
    return engine


@contextmanager
def make_session(
    engine: Engine, *, expire_on_commit: bool = False
) -> Generator[Session, None, None]:
    """Yield a SQLModel session bound to `engine`, committing on clean exit.

    `expire_on_commit=False` by default (the SQLModel/FastAPI ergonomic
    default): objects remain usable after commit, so callers can read
    fields outside the session context. Pass `expire_on_commit=True`
    only if you specifically want SQLAlchemy's default expire-on-commit
    behaviour.
    """
    with Session(engine, expire_on_commit=expire_on_commit) as session:
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise


def init_db(engine: Engine) -> None:
    """Create all tables and the `vec_chunks` virtual table.

    Idempotent — safe to call on an existing database. For real schema
    evolution, use Alembic migrations rather than relying on this.
    """
    SQLModel.metadata.create_all(engine)
    with engine.begin() as conn:
        conn.execute(
            text(
                f"CREATE VIRTUAL TABLE IF NOT EXISTS vec_chunks USING vec0("
                f"  chunk_id INTEGER PRIMARY KEY,"
                f"  embedding FLOAT[{EMBEDDING_DIM}]"
                f")"
            )
        )
