"""Tests for the ingest orchestrator."""

from __future__ import annotations

import io
import math
import random
import tarfile
from pathlib import Path
from typing import cast

import pytest
from sqlalchemy.engine import Engine
from sqlmodel import select

from callimachus.pipeline.embed import EMBEDDING_DIM, Embedder
from callimachus.pipeline.enrich import Enrichment
from callimachus.pipeline.ingest import IngestResult, ingest_one, make_work_id
from callimachus.pipeline.ocr import OcrImage, OcrResult
from callimachus.pipeline.ocr.protocols import OcrProvider
from callimachus.pipeline.paths import work_dir
from callimachus.sources import (
    Provenance,
    ResolvedFile,
    Resolver,
    SourceRegistry,
    SourceUnavailable,
    WorkCandidate,
)
from callimachus.storage import Chunk, init_db, make_engine, make_session, search_chunks

# ---------- fixtures ----------


@pytest.fixture
def engine(tmp_path: Path) -> Engine:
    db = tmp_path / "lib.db"
    eng = make_engine(f"sqlite:///{db}")
    init_db(eng)
    return eng


def _unit_vector(seed: int) -> list[float]:
    rng = random.Random(seed)
    raw = [rng.gauss(0, 1) for _ in range(EMBEDDING_DIM)]
    norm = math.sqrt(sum(x * x for x in raw))
    return [x / norm for x in raw]


def _arxiv_candidate(arxiv_id: str = "2006.11239") -> WorkCandidate:
    return WorkCandidate(
        title="DDPM (candidate-side title)",
        source_url=f"https://arxiv.org/abs/{arxiv_id}",
        provenance=Provenance(source_name="arxiv", query="diffusion"),
        arxiv_id=arxiv_id,
        kind="paper",
    )


def _doi_candidate() -> WorkCandidate:
    return WorkCandidate(
        title="Some Paper",
        source_url="https://example.org/paper",
        provenance=Provenance(source_name="crossref", query="x"),
        doi="10.1234/foo.bar.baz",
        kind="paper",
    )


def _make_latex_targz_bytes() -> bytes:
    """A minimal LaTeX archive — enough for the extract stage to produce text."""
    latex = (
        r"\documentclass{article}"
        "\n"
        r"\title{Denoising Diffusion Probabilistic Models}"
        "\n"
        r"\begin{document}"
        "\n"
        r"\section{Introduction}"
        "\n"
        "Deep generative models. "
        * 50  # padding so chunks > 1
        + "\n"
        + r"\section{Method}"
        "\n"
        "Variational bound details. " * 50 + "\n" + r"\end{document}" + "\n"
    )
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tf:
        data = latex.encode("utf-8")
        info = tarfile.TarInfo("main.tex")
        info.size = len(data)
        tf.addfile(info, io.BytesIO(data))
    return buf.getvalue()


# ---------- stubs ----------


class _StubResolver:
    """Always returns a canned ResolvedFile, ignoring the candidate."""

    def __init__(
        self,
        *,
        bytes_: bytes,
        content_type: str = "application/x-eprint-tar",
    ) -> None:
        self.name = "stub_resolver"
        self.enabled = True
        self._bytes = bytes_
        self._content_type = content_type
        self.resolve_calls: list[WorkCandidate] = []

    async def confidence(self, candidate: WorkCandidate) -> float:
        del candidate
        return 1.0

    async def resolve(self, candidate: WorkCandidate) -> ResolvedFile:
        self.resolve_calls.append(candidate)
        return ResolvedFile(
            candidate_id=candidate.candidate_id,
            bytes_=self._bytes,
            content_type=self._content_type,
            source_url=candidate.source_url,
            resolved_by=self.name,
        )


class _FailingResolver:
    """A resolver that always raises SourceUnavailable."""

    name: str = "broken"
    enabled: bool = True

    async def confidence(self, candidate: WorkCandidate) -> float:
        del candidate
        return 1.0

    async def resolve(self, candidate: WorkCandidate) -> ResolvedFile:
        del candidate
        raise SourceUnavailable("stub failure")


class _StubEmbedder:
    """Returns deterministic vectors (one per text)."""

    name: str = "stub_embedder"

    def __init__(self) -> None:
        self.docs_seen: list[list[str]] = []
        self.queries_seen: list[str] = []

    async def embed_documents(self, texts: list[str]) -> list[list[float]]:
        self.docs_seen.append(list(texts))
        return [_unit_vector(i + 1) for i in range(len(texts))]

    async def embed_query(self, text: str) -> list[float]:
        self.queries_seen.append(text)
        return _unit_vector(0)


class _StubOcr:
    """Returns canned OcrResult so we can exercise the PDF path without Mistral."""

    name: str = "stub_ocr"

    def __init__(self, result: OcrResult) -> None:
        self._result = result
        self.calls: int = 0

    async def extract(self, artifact_bytes: bytes, content_type: str) -> OcrResult:
        del artifact_bytes, content_type
        self.calls += 1
        return self._result


def _canned_enrichment(title: str = "Denoising Diffusion Probabilistic Models") -> Enrichment:
    return Enrichment(
        title=title,
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


async def _stub_enricher(text: str) -> Enrichment:
    del text
    return _canned_enrichment()


# ---------- make_work_id ----------


def test_make_work_id_prefers_arxiv_id() -> None:
    assert make_work_id(_arxiv_candidate("2006.11239")) == "arxiv-2006-11239"


def test_make_work_id_handles_old_style_arxiv_id() -> None:
    assert make_work_id(_arxiv_candidate("hep-th/0001234")) == "arxiv-hep-th-0001234"


def test_make_work_id_falls_back_to_doi() -> None:
    assert make_work_id(_doi_candidate()) == "doi-10-1234-foo-bar-baz"


def test_make_work_id_falls_back_to_title_slug() -> None:
    candidate = WorkCandidate(
        title="Hello, World!  This is a Title.",
        source_url="https://example.org/x",
        provenance=Provenance(source_name="t", query="q"),
    )
    assert make_work_id(candidate) == "hello-world-this-is-a-title"


def test_make_work_id_truncates_long_titles() -> None:
    long_title = "a" * 200
    candidate = WorkCandidate(
        title=long_title,
        source_url="https://example.org/x",
        provenance=Provenance(source_name="t", query="q"),
    )
    assert len(make_work_id(candidate)) <= 60


# ---------- happy path ----------


async def test_ingest_one_runs_full_pipeline_for_latex(tmp_path: Path, engine: Engine) -> None:
    candidate = _arxiv_candidate()
    registry = SourceRegistry()
    registry.register_resolver(cast("Resolver", _StubResolver(bytes_=_make_latex_targz_bytes())))
    embedder: Embedder = cast("Embedder", _StubEmbedder())

    with make_session(engine) as session:
        result = await ingest_one(
            candidate,
            library_root=tmp_path,
            session=session,
            registry=registry,
            enricher=_stub_enricher,
            embedder=embedder,
        )

    assert isinstance(result, IngestResult)
    assert result.work_id == "arxiv-2006-11239"
    assert result.chunks_indexed > 0

    # Filesystem artifacts
    wd = work_dir(tmp_path, result.work_id)
    assert (wd / "original.tar.gz").is_file()
    assert (wd / "paper.md").is_file()
    assert (wd / "metadata.yaml").is_file()
    assert (wd / "summary.md").is_file()

    # paper.md has YAML frontmatter from enrichment
    assert (wd / "paper.md").read_text().startswith("---\n")

    # DB has Work + Chunks + vec_chunks
    with make_session(engine) as session:
        rows = list(session.exec(select(Chunk).where(Chunk.work_id == result.work_id)).all())
    assert len(rows) == result.chunks_indexed


async def test_ingest_one_uses_ocr_for_pdf_artifact(tmp_path: Path, engine: Engine) -> None:
    """If the resolver returns a PDF, the OCR provider gets called."""
    candidate = _arxiv_candidate()
    registry = SourceRegistry()
    registry.register_resolver(
        cast(
            "Resolver",
            _StubResolver(bytes_=b"%PDF-1.4 stub", content_type="application/pdf"),
        )
    )
    ocr_result = OcrResult(
        markdown="# Page 1\n\nOCR-extracted body text.\n",
        images=[OcrImage(id="img-0.png", bytes_=b"fake-png", content_type="image/png")],
        pages=1,
        provider="stub_ocr",
    )
    ocr = _StubOcr(ocr_result)
    embedder: Embedder = cast("Embedder", _StubEmbedder())

    with make_session(engine) as session:
        result = await ingest_one(
            candidate,
            library_root=tmp_path,
            session=session,
            registry=registry,
            enricher=_stub_enricher,
            embedder=embedder,
            ocr=cast("OcrProvider", ocr),
        )

    assert ocr.calls == 1
    assert result.chunks_indexed > 0
    # Image saved to images/
    assert (work_dir(tmp_path, result.work_id) / "images" / "img-0.png").read_bytes() == b"fake-png"


async def test_ingest_one_embeddings_are_searchable(tmp_path: Path, engine: Engine) -> None:
    """End-to-end: after ingest, vector search returns this work's chunks."""
    candidate = _arxiv_candidate()
    registry = SourceRegistry()
    registry.register_resolver(cast("Resolver", _StubResolver(bytes_=_make_latex_targz_bytes())))
    embedder = _StubEmbedder()

    with make_session(engine) as session:
        result = await ingest_one(
            candidate,
            library_root=tmp_path,
            session=session,
            registry=registry,
            enricher=_stub_enricher,
            embedder=cast("Embedder", embedder),
        )

    # The embedder returned _unit_vector(1), (2), ... — searching for vector(1) should
    # surface chunk 0 first (or at least put a chunk from this work at the top).
    with make_session(engine) as session:
        hits = await embedder.embed_query("anything")
        results = search_chunks(session, hits, k=5)
    assert results
    assert results[0].work.id == result.work_id


# ---------- failure propagation ----------


async def test_ingest_one_propagates_resolver_failure(tmp_path: Path, engine: Engine) -> None:
    candidate = _arxiv_candidate()
    registry = SourceRegistry()
    registry.register_resolver(cast("Resolver", _FailingResolver()))
    embedder: Embedder = cast("Embedder", _StubEmbedder())

    with make_session(engine) as session, pytest.raises(SourceUnavailable, match="stub failure"):
        await ingest_one(
            candidate,
            library_root=tmp_path,
            session=session,
            registry=registry,
            enricher=_stub_enricher,
            embedder=embedder,
        )


async def test_ingest_one_propagates_enricher_failure(tmp_path: Path, engine: Engine) -> None:
    candidate = _arxiv_candidate()
    registry = SourceRegistry()
    registry.register_resolver(cast("Resolver", _StubResolver(bytes_=_make_latex_targz_bytes())))
    embedder: Embedder = cast("Embedder", _StubEmbedder())

    async def boom(text: str) -> Enrichment:
        del text
        raise RuntimeError("enricher exploded")

    with make_session(engine) as session, pytest.raises(RuntimeError, match="exploded"):
        await ingest_one(
            candidate,
            library_root=tmp_path,
            session=session,
            registry=registry,
            enricher=boom,
            embedder=embedder,
        )


# ---------- idempotency ----------


async def test_ingest_one_re_run_replaces_chunks(tmp_path: Path, engine: Engine) -> None:
    """Running ingest_one twice on the same candidate should not stack chunks."""
    candidate = _arxiv_candidate()
    registry = SourceRegistry()
    registry.register_resolver(cast("Resolver", _StubResolver(bytes_=_make_latex_targz_bytes())))
    embedder: Embedder = cast("Embedder", _StubEmbedder())

    async def run_once() -> int:
        with make_session(engine) as session:
            r = await ingest_one(
                candidate,
                library_root=tmp_path,
                session=session,
                registry=registry,
                enricher=_stub_enricher,
                embedder=embedder,
            )
            return r.chunks_indexed

    n1 = await run_once()
    n2 = await run_once()
    assert n1 == n2

    with make_session(engine) as session:
        rows = list(session.exec(select(Chunk).where(Chunk.work_id == "arxiv-2006-11239")).all())
    assert len(rows) == n2  # not 2*n2 — old rows replaced
