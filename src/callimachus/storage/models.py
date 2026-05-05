"""SQLModel classes for the Callimachus library schema.

The vector index (`vec_chunks` virtual table) is created separately in
`db.init_db` because SQLModel doesn't model virtual tables. See `vec.py`
for the search helpers.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import JSON, Column
from sqlmodel import Field, SQLModel

# Embedding dimension. Matches nomic-embed-text-v1.5 (our local default).
# If we change the embedding model, this must change AND we must rebuild
# the vec_chunks virtual table.
EMBEDDING_DIM = 768


def _utcnow() -> datetime:
    return datetime.now(UTC)


class Collection(SQLModel, table=True):
    """A named subject within a library (e.g. 'diffusion-models')."""

    __tablename__ = "collections"  # type: ignore[assignment]

    id: str = Field(primary_key=True, description="Slug, e.g. 'diffusion-models'.")
    name: str
    keywords: list[str] = Field(default_factory=list, sa_column=Column(JSON))
    notes: str | None = None
    overview_path: str | None = Field(
        default=None, description="Relative path to collections/<slug>/overview.md."
    )
    added_at: datetime = Field(default_factory=_utcnow)
    added_by_run_id: int | None = Field(default=None, foreign_key="runs.id")


class Work(SQLModel, table=True):
    """A research artifact: paper, essay, report, talk, chapter."""

    __tablename__ = "works"  # type: ignore[assignment]

    id: str = Field(
        primary_key=True,
        description="Canonical slug, e.g. 'ho-2020-denoising-diffusion'.",
    )
    kind: str = Field(
        default="paper",
        description="paper | essay | report | talk | chapter",
    )
    doi: str | None = Field(default=None, unique=True, index=True)
    arxiv_id: str | None = Field(default=None, index=True)
    title: str
    authors: list[dict[str, Any]] = Field(
        default_factory=list,
        sa_column=Column(JSON),
        description="[{name, orcid?, affiliation?}, ...]",
    )
    year: int | None = None
    venue: str | None = None
    abstract: str | None = None

    # Enrichment outputs
    summary: str | None = None
    key_claims: list[str] = Field(default_factory=list, sa_column=Column(JSON))
    methods: list[str] = Field(default_factory=list, sa_column=Column(JSON))
    datasets: list[str] = Field(default_factory=list, sa_column=Column(JSON))

    # Sourcing
    source_url: str = Field(description="Where the artifact came from; for rehydration.")
    pdf_path: str | None = Field(
        default=None,
        description="Relative to library root. Null after rehydration removal.",
    )
    markdown_path: str | None = Field(
        default=None,
        description="Relative to library root.",
    )

    # Judge fields (populated in M2+)
    judge_score: float | None = None
    judge_reasoning: str | None = None

    # Run + lifecycle
    added_at: datetime = Field(default_factory=_utcnow)
    admitted_by_run_id: int | None = Field(default=None, foreign_key="runs.id")
    archived_at: datetime | None = Field(
        default=None,
        description="Soft-delete timestamp; null means active.",
    )
    bridge: bool = Field(
        default=False,
        description="Scores high in 2+ collections within the library.",
    )

    # Catch-all
    extra: dict[str, Any] = Field(
        default_factory=dict,
        sa_column=Column(JSON),
        description="Provider-specific metadata not modeled explicitly.",
    )


class WorkCollection(SQLModel, table=True):
    """Many-to-many join between Work and Collection."""

    __tablename__ = "work_collections"  # type: ignore[assignment]

    work_id: str = Field(foreign_key="works.id", primary_key=True)
    collection_id: str = Field(foreign_key="collections.id", primary_key=True)
    score: float = Field(default=0.0, description="0-10 relevance for this collection.")
    is_seed: bool = Field(default=False, description="Was this a seed for snowballing?")


class Chunk(SQLModel, table=True):
    """A passage of a work, ~500 tokens, the unit of vector search."""

    __tablename__ = "chunks"  # type: ignore[assignment]

    id: int | None = Field(default=None, primary_key=True)
    work_id: str = Field(foreign_key="works.id", index=True)
    ord: int = Field(description="Position within the work (0-indexed).")
    text: str
    section: str | None = Field(default=None, description="e.g. 'Introduction', 'Method'.")


class Run(SQLModel, table=True):
    """A single mutating operation on a library."""

    __tablename__ = "runs"  # type: ignore[assignment]

    id: int | None = Field(default=None, primary_key=True)
    kind: str = Field(
        description="build | extend | refresh | prune | rejudge | restore | ingest",
    )
    collection_id: str | None = Field(default=None, foreign_key="collections.id")
    started_at: datetime = Field(default_factory=_utcnow)
    ended_at: datetime | None = None
    config: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
    cost_usd: float = Field(default=0.0)
    works_added: int = Field(default=0)
    works_archived: int = Field(default=0)
    works_retagged: int = Field(default=0)
    notes: str | None = None
