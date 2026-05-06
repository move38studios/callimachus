"""Index stage — write Work + Chunks + vec_chunks rows to the library DB.

Composes inputs from earlier stages (candidate from discovery, enrichment
from M1.3c, chunks from M1.3d's chunker, embeddings from the embedder)
into a single delete-and-rewrite operation per work.

Idempotent: re-running on the same work_id replaces the existing Work
row's mutable fields and fully replaces the chunks + embeddings.
"""

from __future__ import annotations

import logging
from pathlib import Path

from sqlalchemy import text
from sqlmodel import Session, select

from callimachus.pipeline.chunk import MarkdownChunk
from callimachus.pipeline.enrich import Enrichment
from callimachus.pipeline.paths import markdown_path, original_path
from callimachus.sources import WorkCandidate
from callimachus.storage import Chunk, Work, insert_chunk_embedding

log = logging.getLogger(__name__)


def _relpath_or_none(path: Path | None, library_root: Path) -> str | None:
    """Return `path` relative to `library_root`, or None if path is None
    or doesn't sit beneath the library root."""
    if path is None:
        return None
    try:
        return str(path.resolve().relative_to(library_root.resolve()))
    except ValueError:
        return None


def index_work(
    *,
    work_id: str,
    candidate: WorkCandidate,
    enrichment: Enrichment,
    chunks: list[MarkdownChunk],
    embeddings: list[list[float]],
    library_root: Path,
    artifact_path: Path | None = None,
    session: Session,
) -> Work:
    """Upsert a Work row + replace its Chunks + vec_chunks entries.

    Args:
        work_id: Canonical slug for the work.
        candidate: The discovery-time candidate (provides DOI, arXiv ID,
            source URL, kind).
        enrichment: Enrichment-stage output (title, authors, summary, …).
        chunks: Per-chunk text from the chunker.
        embeddings: Same length as `chunks`, each a 768-d list of floats.
        library_root: Library root path (used to compute relative paths).
        artifact_path: Path to the originally-resolved artifact (PDF or
            tar.gz). Stored as `pdf_path` if set, else None.
        session: SQLModel session.

    Returns:
        The persisted `Work` row.

    Raises:
        ValueError if `chunks` and `embeddings` have different lengths.
    """
    if len(chunks) != len(embeddings):
        msg = (
            f"index_work: chunks ({len(chunks)}) and embeddings ({len(embeddings)}) length mismatch"
        )
        raise ValueError(msg)

    md_relpath = _relpath_or_none(markdown_path(library_root, work_id), library_root)
    pdf_relpath: str | None = None
    if artifact_path is not None:
        pdf_relpath = _relpath_or_none(artifact_path, library_root)
    elif candidate.kind == "paper":
        # Best-effort default: assume the original is a PDF if present
        candidate_pdf = original_path(library_root, work_id, "application/pdf")
        if candidate_pdf.is_file():
            pdf_relpath = _relpath_or_none(candidate_pdf, library_root)

    authors_json = [{"name": name} for name in enrichment.authors]

    existing = session.get(Work, work_id)
    if existing is None:
        work = Work(
            id=work_id,
            kind=candidate.kind,
            doi=candidate.doi,
            arxiv_id=candidate.arxiv_id,
            title=enrichment.title,
            authors=authors_json,
            year=enrichment.year,
            venue=enrichment.venue,
            abstract=candidate.abstract,
            summary=enrichment.summary,
            key_claims=enrichment.key_claims,
            methods=enrichment.methods,
            datasets=enrichment.datasets,
            source_url=candidate.source_url,
            pdf_path=pdf_relpath,
            markdown_path=md_relpath,
        )
        session.add(work)
    else:
        existing.kind = candidate.kind
        existing.doi = candidate.doi
        existing.arxiv_id = candidate.arxiv_id
        existing.title = enrichment.title
        existing.authors = authors_json
        existing.year = enrichment.year
        existing.venue = enrichment.venue
        existing.abstract = candidate.abstract
        existing.summary = enrichment.summary
        existing.key_claims = enrichment.key_claims
        existing.methods = enrichment.methods
        existing.datasets = enrichment.datasets
        existing.source_url = candidate.source_url
        existing.pdf_path = pdf_relpath
        existing.markdown_path = md_relpath
        work = existing
    session.flush()

    # Delete existing chunks + their embeddings
    existing_chunks = list(session.exec(select(Chunk).where(Chunk.work_id == work_id)).all())
    if existing_chunks:
        chunk_ids = [c.id for c in existing_chunks if c.id is not None]
        if chunk_ids:
            placeholders = ",".join(":id_" + str(i) for i in range(len(chunk_ids)))
            params = {f"id_{i}": cid for i, cid in enumerate(chunk_ids)}
            session.connection().execute(
                text(f"DELETE FROM vec_chunks WHERE chunk_id IN ({placeholders})"),
                params,
            )
        for chunk in existing_chunks:
            session.delete(chunk)
        session.flush()

    # Insert new chunks + embeddings
    for md_chunk, embedding in zip(chunks, embeddings, strict=True):
        new_chunk = Chunk(
            work_id=work_id,
            ord=md_chunk.ord,
            text=md_chunk.text,
            section=md_chunk.section,
        )
        session.add(new_chunk)
        session.flush()
        if new_chunk.id is None:
            msg = "index_work: chunk insert didn't return an id"
            raise RuntimeError(msg)
        insert_chunk_embedding(session, new_chunk.id, embedding)

    log.debug("index_work: indexed work %r with %d chunks", work_id, len(chunks))
    return work
