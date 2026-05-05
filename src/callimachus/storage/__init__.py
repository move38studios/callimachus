"""Storage layer — SQLite + sqlite-vec, models via SQLModel."""

from __future__ import annotations

from callimachus.storage.db import init_db, make_engine, make_session
from callimachus.storage.models import (
    Chunk,
    Collection,
    Run,
    Work,
    WorkCollection,
)
from callimachus.storage.vec import insert_chunk_embedding, search_chunks

__all__ = [
    "Chunk",
    "Collection",
    "Run",
    "Work",
    "WorkCollection",
    "init_db",
    "insert_chunk_embedding",
    "make_engine",
    "make_session",
    "search_chunks",
]
