"""Vector search helpers over the `vec_chunks` virtual table.

sqlite-vec stores embeddings as packed float32 bytes. We expose a small
typed API so callers don't deal with serialization or raw SQL `MATCH`.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass
from typing import cast

from sqlalchemy import text
from sqlmodel import Session

from callimachus.storage.models import EMBEDDING_DIM, Chunk, Work, WorkCollection


def _pack_embedding(embedding: list[float]) -> bytes:
    """Pack a Python list of floats into the float32 byte format vec0 expects."""
    if len(embedding) != EMBEDDING_DIM:
        raise ValueError(
            f"Expected {EMBEDDING_DIM}-d embedding, got {len(embedding)}-d. "
            f"If you changed the embedding model, you must rebuild vec_chunks."
        )
    return struct.pack(f"{EMBEDDING_DIM}f", *embedding)


def insert_chunk_embedding(session: Session, chunk_id: int, embedding: list[float]) -> None:
    """Insert (or replace) an embedding for an existing Chunk row.

    Uses the underlying SQLAlchemy connection for raw SQL — SQLModel's
    `session.execute()` is deprecated in favour of `session.exec()`, but
    `exec()` is typed for ORM queries, not raw text statements.
    """
    session.connection().execute(
        text(
            "INSERT OR REPLACE INTO vec_chunks (chunk_id, embedding) VALUES (:chunk_id, :embedding)"
        ),
        {"chunk_id": chunk_id, "embedding": _pack_embedding(embedding)},
    )


@dataclass(slots=True)
class SearchHit:
    """One result from a vector search."""

    work: Work
    chunk: Chunk
    distance: float


def search_chunks(
    session: Session,
    query_embedding: list[float],
    *,
    k: int = 10,
    collection_id: str | None = None,
    include_archived: bool = False,
) -> list[SearchHit]:
    """k-NN search over chunk embeddings.

    Returns hits ordered by ascending distance (closest first). Each hit
    carries the matched chunk and its parent work, fully hydrated.

    Args:
        session: A SQLModel session.
        query_embedding: Length-EMBEDDING_DIM list of floats.
        k: Top-k. Default 10.
        collection_id: If given, restrict to works in this collection.
        include_archived: If False (default), skip soft-deleted works.
    """
    result = session.connection().execute(
        text(
            "SELECT v.chunk_id, v.distance "
            "FROM vec_chunks v "
            "WHERE v.embedding MATCH :query_emb AND k = :k "
            "ORDER BY v.distance"
        ),
        {"query_emb": _pack_embedding(query_embedding), "k": k},
    )
    rows = cast("list[tuple[int, float]]", result.all())

    hits: list[SearchHit] = []
    for chunk_id, distance in rows:
        chunk = session.get(Chunk, chunk_id)
        if chunk is None:
            continue
        work = session.get(Work, chunk.work_id)
        if work is None:
            continue
        if not include_archived and work.archived_at is not None:
            continue
        if collection_id is not None:
            membership = session.get(WorkCollection, (work.id, collection_id))
            if membership is None:
                continue
        hits.append(SearchHit(work=work, chunk=chunk, distance=float(distance)))
    return hits
