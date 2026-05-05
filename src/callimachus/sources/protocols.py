"""Plugin contracts — Protocols, data models, exceptions.

See `docs/PLUGINS.md` for the canonical contract and rationale.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal, Protocol, runtime_checkable

from pydantic import BaseModel, Field

WorkKind = Literal["paper", "essay", "report", "talk", "chapter"]
SourceKind = Literal["bibliographic", "web", "preprint", "vault", "social"]


class Provenance(BaseModel):
    """Where a candidate came from."""

    source_name: str
    query: str
    raw_score: float | None = None
    retrieved_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class WorkCandidate(BaseModel):
    """A pre-acceptance research artifact returned by a discovery source.

    Lightweight, source-agnostic. Promoted to a `Work` (in callimachus.storage)
    at admission time after enrichment.
    """

    title: str
    source_url: str
    provenance: Provenance
    doi: str | None = None
    arxiv_id: str | None = None
    authors: list[str] = Field(default_factory=list)
    year: int | None = None
    abstract: str | None = None
    venue: str | None = None
    pdf_url: str | None = None
    kind: WorkKind = "paper"
    extras: dict[str, object] = Field(default_factory=dict)

    @property
    def candidate_id(self) -> str:
        """A stable identifier for de-duplication: prefer DOI, then arxiv_id, then URL."""
        if self.doi:
            return f"doi:{self.doi}"
        if self.arxiv_id:
            return f"arxiv:{self.arxiv_id}"
        return f"url:{self.source_url}"


class ResolvedFile(BaseModel):
    """Bytes for a candidate, plus metadata about how/where they came from."""

    candidate_id: str
    bytes_: bytes
    content_type: str = Field(description="e.g. 'application/pdf', 'application/x-tex'")
    source_url: str = Field(description="The actual URL these bytes came from.")
    resolved_by: str = Field(description="Plugin name that produced this.")


class SourceUnavailable(Exception):  # noqa: N818
    """Recoverable plugin failure: rate limited, transient outage, no results.

    The agent-boundary wrapper catches this and re-raises as
    `pydantic_ai.ModelRetry` so the orchestrator can recover gracefully
    (try a different source, fall back, explain in synthesis).

    For unrecoverable failures (your code has a bug, dependency fully
    broken, schema invariant violated), raise a regular exception — it
    propagates and surfaces to the user.
    """


@runtime_checkable
class DiscoverySource(Protocol):
    """Turn a topic + filters into a list of `WorkCandidate`s."""

    name: str
    kind: SourceKind
    enabled: bool

    async def search(
        self,
        query: str,
        *,
        limit: int = 50,
        year_from: int | None = None,
        year_to: int | None = None,
        kinds: list[WorkKind] | None = None,
    ) -> list[WorkCandidate]: ...


@runtime_checkable
class CitationGraph(Protocol):
    """Optional capability — sources with reference / citation data implement this."""

    async def get_references(self, candidate: WorkCandidate) -> list[WorkCandidate]: ...
    async def get_citations(self, candidate: WorkCandidate) -> list[WorkCandidate]: ...
    async def get_citation_contexts(self, candidate: WorkCandidate) -> list[dict[str, str]]: ...


@runtime_checkable
class Resolver(Protocol):
    """Turn a known `WorkCandidate` into bytes."""

    name: str
    enabled: bool

    async def confidence(self, candidate: WorkCandidate) -> float:
        """Self-report 0.0-1.0 — how well can this resolver fetch THIS candidate?

        Examples:
        - arxiv resolver returns 1.0 if `candidate.arxiv_id` is set, else 0.0
        - unpaywall returns 0.9 if `candidate.doi` is set, else 0.0
        - local_pdfs returns 1.0 if a matching local file exists, else 0.0

        Confidence is per-call (depends on the candidate). The registry
        sorts resolvers by descending confidence and tries them in order;
        first success wins. Confidence == 0 means "skip me."
        """
        ...

    async def resolve(self, candidate: WorkCandidate) -> ResolvedFile: ...
