"""Tests for the plugin Protocol contracts and shared data models."""

from __future__ import annotations

import pytest

from callimachus.sources import (
    DiscoverySource,
    Provenance,
    ResolvedFile,
    Resolver,
    SourceKind,
    SourceUnavailable,
    WorkCandidate,
    WorkKind,
)


def test_work_candidate_id_prefers_doi() -> None:
    c = WorkCandidate(
        title="x",
        source_url="https://example.org/x",
        provenance=Provenance(source_name="test", query="q"),
        doi="10.1234/foo",
        arxiv_id="2006.11239",
    )
    assert c.candidate_id == "doi:10.1234/foo"


def test_work_candidate_id_falls_back_to_arxiv() -> None:
    c = WorkCandidate(
        title="x",
        source_url="https://example.org/x",
        provenance=Provenance(source_name="test", query="q"),
        arxiv_id="2006.11239",
    )
    assert c.candidate_id == "arxiv:2006.11239"


def test_work_candidate_id_falls_back_to_url() -> None:
    c = WorkCandidate(
        title="x",
        source_url="https://example.org/x",
        provenance=Provenance(source_name="test", query="q"),
    )
    assert c.candidate_id == "url:https://example.org/x"


def test_resolved_file_roundtrips() -> None:
    rf = ResolvedFile(
        candidate_id="doi:10.1/foo",
        bytes_=b"%PDF-1.4 stub",
        content_type="application/pdf",
        source_url="https://example.org/x.pdf",
        resolved_by="test_resolver",
    )
    dumped = rf.model_dump()
    assert dumped["bytes_"] == b"%PDF-1.4 stub"
    again = ResolvedFile.model_validate(dumped)
    assert again == rf


def test_source_unavailable_is_an_exception() -> None:
    with pytest.raises(SourceUnavailable, match="rate limited"):
        raise SourceUnavailable("rate limited")


# Structural conformance — these classes deliberately have nothing to do with
# our bundled plugins, but should still satisfy the Protocol via duck typing.


class _MinimalSource:
    name: str = "minimal"
    kind: SourceKind = "bibliographic"
    enabled: bool = True

    async def search(
        self,
        query: str,
        *,
        limit: int = 50,
        year_from: int | None = None,
        year_to: int | None = None,
        kinds: list[WorkKind] | None = None,
    ) -> list[WorkCandidate]:
        del query, limit, year_from, year_to, kinds
        return []


class _MinimalResolver:
    name: str = "minimal"
    enabled: bool = True

    async def confidence(self, candidate: WorkCandidate) -> float:
        del candidate
        return 0.0

    async def resolve(self, candidate: WorkCandidate) -> ResolvedFile:
        del candidate
        raise SourceUnavailable("stub")


def test_minimal_source_satisfies_discovery_protocol() -> None:
    instance = _MinimalSource()
    assert isinstance(instance, DiscoverySource)


def test_minimal_resolver_satisfies_resolver_protocol() -> None:
    instance = _MinimalResolver()
    assert isinstance(instance, Resolver)
