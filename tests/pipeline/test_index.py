"""Tests for the index stage — Work + Chunks + vec_chunks DB writes."""

from __future__ import annotations

import math
import random
from pathlib import Path

import pytest
from sqlalchemy.engine import Engine
from sqlmodel import select

from callimachus.pipeline.chunk import MarkdownChunk
from callimachus.pipeline.embed import EMBEDDING_DIM
from callimachus.pipeline.enrich import Enrichment
from callimachus.pipeline.index import index_work
from callimachus.sources import Provenance, WorkCandidate
from callimachus.storage import (
    Chunk,
    Work,
    init_db,
    make_engine,
    make_session,
    search_chunks,
)


def _unit_vector(seed: int) -> list[float]:
    rng = random.Random(seed)
    raw = [rng.gauss(0, 1) for _ in range(EMBEDDING_DIM)]
    norm = math.sqrt(sum(x * x for x in raw))
    return [x / norm for x in raw]


def _candidate() -> WorkCandidate:
    return WorkCandidate(
        title="DDPM",
        source_url="https://arxiv.org/abs/2006.11239",
        provenance=Provenance(source_name="arxiv", query="diffusion"),
        arxiv_id="2006.11239",
        kind="paper",
    )


def _enrichment() -> Enrichment:
    return Enrichment(
        title="Denoising Diffusion Probabilistic Models",
        authors=["Jonathan Ho", "Ajay Jain", "Pieter Abbeel"],
        year=2020,
        venue="NeurIPS",
        summary=(
            "DDPM trains diffusion probabilistic models with a weighted "
            "variational bound that connects to denoising score matching."
        ),
        key_claims=["The variational bound is the right objective."],
        methods=["denoising diffusion"],
        datasets=["CIFAR-10", "LSUN"],
        keywords=["diffusion models", "score matching"],
    )


def _make_chunks_and_embeddings(n: int) -> tuple[list[MarkdownChunk], list[list[float]]]:
    chunks = [
        MarkdownChunk(ord=i, text=f"Chunk {i} body text.", section=f"Section {i}") for i in range(n)
    ]
    embeddings = [_unit_vector(i + 1) for i in range(n)]
    return chunks, embeddings


@pytest.fixture
def engine(tmp_path: Path) -> Engine:
    db = tmp_path / "lib.db"
    eng = make_engine(f"sqlite:///{db}")
    init_db(eng)
    return eng


# ---------- happy path ----------


def test_index_work_inserts_work_chunks_and_embeddings(tmp_path: Path, engine: Engine) -> None:
    chunks, embeddings = _make_chunks_and_embeddings(3)

    with make_session(engine) as session:
        work = index_work(
            work_id="ho-2020-ddpm",
            candidate=_candidate(),
            enrichment=_enrichment(),
            chunks=chunks,
            embeddings=embeddings,
            library_root=tmp_path,
            session=session,
        )

    # Work row written with merged candidate + enrichment fields
    assert work.id == "ho-2020-ddpm"
    assert work.title == "Denoising Diffusion Probabilistic Models"
    assert work.arxiv_id == "2006.11239"
    assert work.year == 2020
    assert work.authors == [
        {"name": "Jonathan Ho"},
        {"name": "Ajay Jain"},
        {"name": "Pieter Abbeel"},
    ]
    assert work.summary is not None and work.summary.startswith("DDPM")
    assert work.datasets == ["CIFAR-10", "LSUN"]
    assert work.markdown_path == "works/ho-2020-ddpm/paper.md"

    # Chunks written
    with make_session(engine) as session:
        rows = list(session.exec(select(Chunk).where(Chunk.work_id == "ho-2020-ddpm")).all())
    assert len(rows) == 3
    by_ord = {r.ord: r for r in rows}
    assert by_ord[0].text == "Chunk 0 body text."
    assert by_ord[0].section == "Section 0"


def test_index_work_writes_searchable_embeddings(tmp_path: Path, engine: Engine) -> None:
    chunks, embeddings = _make_chunks_and_embeddings(3)
    with make_session(engine) as session:
        index_work(
            work_id="x",
            candidate=_candidate(),
            enrichment=_enrichment(),
            chunks=chunks,
            embeddings=embeddings,
            library_root=tmp_path,
            session=session,
        )

    # Searching for embedding[1] should put chunk 1 first
    with make_session(engine) as session:
        hits = search_chunks(session, embeddings[1], k=3)

    assert len(hits) == 3
    assert hits[0].chunk.ord == 1
    assert hits[0].work.id == "x"


# ---------- idempotency ----------


def test_re_indexing_replaces_existing_chunks(tmp_path: Path, engine: Engine) -> None:
    """Running index_work twice replaces the chunks rather than stacking."""
    chunks_v1, emb_v1 = _make_chunks_and_embeddings(3)
    with make_session(engine) as session:
        index_work(
            work_id="x",
            candidate=_candidate(),
            enrichment=_enrichment(),
            chunks=chunks_v1,
            embeddings=emb_v1,
            library_root=tmp_path,
            session=session,
        )

    chunks_v2 = [
        MarkdownChunk(ord=0, text="Brand new chunk content.", section="A"),
    ]
    emb_v2 = [_unit_vector(99)]
    with make_session(engine) as session:
        index_work(
            work_id="x",
            candidate=_candidate(),
            enrichment=_enrichment(),
            chunks=chunks_v2,
            embeddings=emb_v2,
            library_root=tmp_path,
            session=session,
        )

    with make_session(engine) as session:
        rows = list(session.exec(select(Chunk).where(Chunk.work_id == "x")).all())
    assert len(rows) == 1
    assert rows[0].text == "Brand new chunk content."

    # Vector search confirms the old vectors are gone too
    with make_session(engine) as session:
        hits_for_v1 = search_chunks(session, emb_v1[0], k=5)
        hits_for_v2 = search_chunks(session, emb_v2[0], k=5)
    # The v1 vector's nearest hit should now be the only chunk (v2)
    assert hits_for_v2[0].chunk.text == "Brand new chunk content."
    assert all(h.chunk.text == "Brand new chunk content." for h in hits_for_v1)


def test_re_indexing_updates_work_fields(tmp_path: Path, engine: Engine) -> None:
    chunks, embeddings = _make_chunks_and_embeddings(1)

    with make_session(engine) as session:
        first = _enrichment()
        index_work(
            work_id="x",
            candidate=_candidate(),
            enrichment=first,
            chunks=chunks,
            embeddings=embeddings,
            library_root=tmp_path,
            session=session,
        )

    second = first.model_copy(update={"summary": "An updated summary that is long enough."})
    with make_session(engine) as session:
        index_work(
            work_id="x",
            candidate=_candidate(),
            enrichment=second,
            chunks=chunks,
            embeddings=embeddings,
            library_root=tmp_path,
            session=session,
        )

    with make_session(engine) as session:
        work = session.get(Work, "x")
    assert work is not None
    assert work.summary == "An updated summary that is long enough."


# ---------- guards ----------


def test_index_work_raises_on_chunks_embeddings_length_mismatch(
    tmp_path: Path, engine: Engine
) -> None:
    chunks = [MarkdownChunk(ord=0, text="x", section=None)]
    embeddings = [_unit_vector(1), _unit_vector(2)]  # 2 embeddings, 1 chunk
    with make_session(engine) as session, pytest.raises(ValueError, match="length mismatch"):
        index_work(
            work_id="x",
            candidate=_candidate(),
            enrichment=_enrichment(),
            chunks=chunks,
            embeddings=embeddings,
            library_root=tmp_path,
            session=session,
        )


def test_index_work_with_no_chunks_writes_only_the_work_row(tmp_path: Path, engine: Engine) -> None:
    """Edge case: an empty paper. We still want the Work row indexed."""
    with make_session(engine) as session:
        work = index_work(
            work_id="x",
            candidate=_candidate(),
            enrichment=_enrichment(),
            chunks=[],
            embeddings=[],
            library_root=tmp_path,
            session=session,
        )
    assert work.id == "x"
    with make_session(engine) as session:
        rows = list(session.exec(select(Chunk).where(Chunk.work_id == "x")).all())
    assert rows == []
