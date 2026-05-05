"""Storage smoke test — round-trip a Work + Chunks + vector search."""

from __future__ import annotations

import math
from pathlib import Path

import pytest

from callimachus.storage import (
    Chunk,
    Work,
    init_db,
    insert_chunk_embedding,
    make_engine,
    make_session,
    search_chunks,
)
from callimachus.storage.models import EMBEDDING_DIM


def _unit_vector(seed: int) -> list[float]:
    """Deterministic unit vector for a given seed — easy to reason about."""
    import random

    rng = random.Random(seed)
    raw = [rng.gauss(0, 1) for _ in range(EMBEDDING_DIM)]
    norm = math.sqrt(sum(x * x for x in raw))
    return [x / norm for x in raw]


def test_init_db_creates_tables_and_vec_index(tmp_path: Path) -> None:
    db = tmp_path / "lib.db"
    engine = make_engine(f"sqlite:///{db}")
    init_db(engine)

    # All standard tables present
    with make_session(engine) as session:
        from typing import cast

        from sqlalchemy import text

        result = session.connection().execute(
            text("SELECT name FROM sqlite_master WHERE type IN ('table','view') ORDER BY name")
        )
        rows = cast("list[tuple[str]]", result.all())
        names: set[str] = {r[0] for r in rows}
    assert {"works", "chunks", "collections", "work_collections", "runs"} <= names
    # vec_chunks is a virtual table; sqlite-vec creates auxiliary tables too
    assert any(n.startswith("vec_chunks") for n in names)


def test_roundtrip_work_and_chunks_with_vector_search(tmp_path: Path) -> None:
    db = tmp_path / "lib.db"
    engine = make_engine(f"sqlite:///{db}")
    init_db(engine)

    with make_session(engine) as session:
        # Insert one Work and three Chunks with distinct embeddings
        work = Work(
            id="ho-2020-denoising-diffusion",
            kind="paper",
            title="Denoising Diffusion Probabilistic Models",
            authors=[{"name": "Jonathan Ho"}, {"name": "Ajay Jain"}, {"name": "Pieter Abbeel"}],
            year=2020,
            venue="NeurIPS",
            source_url="https://arxiv.org/abs/2006.11239",
        )
        session.add(work)
        session.flush()

        chunks_data = [
            (0, "Diffusion probabilistic models are a class of latent variable models...", 1),
            (1, "We present a weighted variational bound designed according to a connection...", 2),
            (2, "On the unconditional CIFAR10 dataset, we obtain an Inception score of 9.46.", 3),
        ]
        chunk_ids: list[int] = []
        for ord_, text_, seed in chunks_data:
            ch = Chunk(work_id=work.id, ord=ord_, text=text_)
            session.add(ch)
            session.flush()
            assert ch.id is not None
            chunk_ids.append(ch.id)
            insert_chunk_embedding(session, ch.id, _unit_vector(seed))

    # Query: search for the embedding closest to seed=2 (the second chunk)
    with make_session(engine) as session:
        hits = search_chunks(session, _unit_vector(2), k=3)

    assert len(hits) == 3
    # Closest hit should be the chunk with the matching seed
    assert hits[0].chunk.id == chunk_ids[1]
    assert hits[0].chunk.ord == 1
    assert hits[0].work.id == "ho-2020-denoising-diffusion"
    assert hits[0].work.title.startswith("Denoising Diffusion")
    # Distances are non-negative and ordered
    distances = [h.distance for h in hits]
    assert all(d >= 0 for d in distances)
    assert distances == sorted(distances)


def test_archived_works_excluded_from_search(tmp_path: Path) -> None:
    from datetime import UTC, datetime

    db = tmp_path / "lib.db"
    engine = make_engine(f"sqlite:///{db}")
    init_db(engine)

    with make_session(engine) as session:
        work = Work(
            id="archived-paper",
            title="Some archived paper",
            source_url="https://example.org/x",
            archived_at=datetime.now(UTC),
        )
        session.add(work)
        session.flush()
        ch = Chunk(work_id=work.id, ord=0, text="archived content")
        session.add(ch)
        session.flush()
        assert ch.id is not None
        insert_chunk_embedding(session, ch.id, _unit_vector(99))

    with make_session(engine) as session:
        hits = search_chunks(session, _unit_vector(99), k=5)
        hits_with_archived = search_chunks(session, _unit_vector(99), k=5, include_archived=True)

    assert hits == []
    assert len(hits_with_archived) == 1
    assert hits_with_archived[0].work.id == "archived-paper"


def test_embedding_dimension_validation(tmp_path: Path) -> None:
    db = tmp_path / "lib.db"
    engine = make_engine(f"sqlite:///{db}")
    init_db(engine)

    with make_session(engine) as session:
        work = Work(id="x", title="X", source_url="https://example.org/x")
        session.add(work)
        session.flush()
        ch = Chunk(work_id="x", ord=0, text="t")
        session.add(ch)
        session.flush()
        assert ch.id is not None
        with pytest.raises(ValueError, match="Expected 768-d embedding"):
            insert_chunk_embedding(session, ch.id, [0.1, 0.2, 0.3])
