"""Ingest orchestrator — runs the full pipeline for one candidate.

Sequence (each stage idempotent on its own):

    candidate
      → registry.resolve   (sources + resolvers)
      → download           (bytes to disk)
      → extract            (markdown + optional OCR)
      → enrich             (LLM → metadata)
      → chunk              (paragraph-aware splitting)
      → embed              (Contextual Retrieval lite + nomic)
      → index              (Work + Chunks + vec_chunks)

Per-stage checkpointing (state.json + cost.json) lands in M1.5.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from pathlib import Path

from sqlmodel import Session

from callimachus.pipeline.chunk import chunk_markdown
from callimachus.pipeline.download import download_to_library
from callimachus.pipeline.embed import Embedder, apply_contextual_prefix
from callimachus.pipeline.enrich import EnrichFn, Enrichment, enrich_to_files
from callimachus.pipeline.extract import extract_to_markdown
from callimachus.pipeline.index import index_work
from callimachus.pipeline.ocr.protocols import OcrProvider
from callimachus.sources import SourceRegistry, WorkCandidate
from callimachus.storage import Work

log = logging.getLogger(__name__)

_SLUG_NON_ALNUM = re.compile(r"[^a-z0-9]+")
_MAX_TITLE_SLUG = 60


def make_work_id(candidate: WorkCandidate) -> str:
    """Derive a stable work_id from a candidate.

    Preference order: arxiv_id → doi → title slug → 'untitled'.
    """
    if candidate.arxiv_id:
        clean = candidate.arxiv_id.lower().replace("/", "-").replace(".", "-")
        return f"arxiv-{clean}"
    if candidate.doi:
        clean = _SLUG_NON_ALNUM.sub("-", candidate.doi.lower()).strip("-")
        return f"doi-{clean}"
    if candidate.title:
        slug = _SLUG_NON_ALNUM.sub("-", candidate.title.lower()).strip("-")[:_MAX_TITLE_SLUG]
        return slug or "untitled"
    return "untitled"


@dataclass(slots=True)
class IngestResult:
    """Summary returned by `ingest_one` so the caller can report progress."""

    work_id: str
    work: Work
    enrichment: Enrichment
    chunks_indexed: int


async def ingest_one(
    candidate: WorkCandidate,
    *,
    library_root: Path,
    session: Session,
    registry: SourceRegistry,
    enricher: EnrichFn,
    embedder: Embedder,
    ocr: OcrProvider | None = None,
) -> IngestResult:
    """Run the full deterministic pipeline for one candidate.

    Each stage is idempotent on its own — re-running picks up where it
    left off for completed steps and re-does whatever was interrupted.

    Args:
        candidate: The work to ingest. Must already have enough metadata
            for resolution (arxiv_id / doi / source_url).
        library_root: Root of the Callimachus library on disk.
        session: SQLModel session bound to the library DB.
        registry: Plugin registry (for `resolve()`).
        enricher: Function that turns markdown into structured `Enrichment`.
        embedder: Embedder for the chunk → vector step.
        ocr: Optional OCR provider (required for PDF artifacts).

    Returns:
        `IngestResult` with the work_id, persisted Work row, enrichment,
        and number of chunks indexed.
    """
    work_id = make_work_id(candidate)
    log.debug("ingest_one: starting %s (candidate=%s)", work_id, candidate.candidate_id)

    # 1. Resolve to bytes
    resolved = await registry.resolve(candidate)

    # 2. Download to disk
    artifact_path = download_to_library(library_root, work_id, resolved)

    # 3. Extract markdown (LaTeX inline; PDF via OCR)
    md_path = await extract_to_markdown(
        library_root, work_id, artifact_path, resolved.content_type, ocr=ocr
    )

    # 4. Enrich → metadata.yaml + summary.md + paper.md frontmatter
    enrichment = await enrich_to_files(library_root, work_id, enrich_fn=enricher)

    # 5. Chunk the markdown (frontmatter is stripped inside chunk_markdown)
    markdown_text = md_path.read_text()
    chunks = chunk_markdown(markdown_text)

    # 6. Embed with Contextual Retrieval lite (paper title + section per chunk)
    if chunks:
        prefixed = [
            apply_contextual_prefix(c.text, title=enrichment.title, section=c.section)
            for c in chunks
        ]
        embeddings = await embedder.embed_documents(prefixed)
    else:
        embeddings = []

    # 7. Index the Work + Chunks + vec_chunks
    work = index_work(
        work_id=work_id,
        candidate=candidate,
        enrichment=enrichment,
        chunks=chunks,
        embeddings=embeddings,
        library_root=library_root,
        artifact_path=artifact_path,
        session=session,
    )

    log.info(
        "ingest_one: indexed %s — %d chunks, title=%r",
        work_id,
        len(chunks),
        enrichment.title,
    )
    return IngestResult(
        work_id=work_id,
        work=work,
        enrichment=enrichment,
        chunks_indexed=len(chunks),
    )
