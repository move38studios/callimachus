"""Tests for the SourceRegistry — entry-point + local-file plugin loading."""

from __future__ import annotations

from pathlib import Path

import pytest

from callimachus.sources import (
    Provenance,
    ResolvedFile,
    SourceRegistry,
    SourceUnavailable,
    WorkCandidate,
    default_registry,
)
from callimachus.sources.bundled.local_pdfs import LocalPdfsPlugin


def _make_candidate(
    *,
    title: str = "x",
    doi: str | None = None,
    arxiv_id: str | None = None,
) -> WorkCandidate:
    return WorkCandidate(
        title=title,
        source_url="https://example.org/x",
        provenance=Provenance(source_name="test", query="q"),
        doi=doi,
        arxiv_id=arxiv_id,
    )


# ----- entry points -----


def test_default_registry_loads_local_pdfs_via_entry_point() -> None:
    """The bundled local_pdfs plugin must be discoverable by entry-point."""
    registry = default_registry(library_root=Path("/tmp/_callimachus_no_such_path"))
    discovery = registry.get_discovery("local_pdfs")
    resolver = registry.get_resolver("local_pdfs")
    assert discovery is not None
    assert resolver is not None
    # Same instance because LocalPdfsPlugin is both
    assert discovery is resolver


# ----- local-file loading -----


def test_local_directory_plugin_is_discovered(tmp_path: Path) -> None:
    plugin_code = """
from callimachus.sources import Provenance, SourceKind, WorkCandidate, WorkKind

class MyTestSource:
    name: str = "my_test_source"
    kind: SourceKind = "web"
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
        return [WorkCandidate(
            title=f"local test result for {query}",
            source_url="https://example.org/local",
            provenance=Provenance(source_name=self.name, query=query),
        )]
"""
    plugins_dir = tmp_path / "plugins"
    plugins_dir.mkdir()
    (plugins_dir / "my_test_source.py").write_text(plugin_code)

    registry = SourceRegistry()
    registry.load_local_directory(plugins_dir)
    plugin = registry.get_discovery("my_test_source")
    assert plugin is not None
    assert plugin.kind == "web"


def test_underscore_prefixed_files_are_skipped(tmp_path: Path) -> None:
    (tmp_path / "_helper.py").write_text("class Helper:\n    pass\n")
    registry = SourceRegistry()
    registry.load_local_directory(tmp_path)
    assert registry.discovery_sources() == []
    assert registry.resolvers() == []


def test_broken_local_plugin_does_not_crash_registry(tmp_path: Path) -> None:
    (tmp_path / "broken.py").write_text("this is not valid python !!!")
    registry = SourceRegistry()
    # Should log a warning but not raise
    registry.load_local_directory(tmp_path)
    assert registry.discovery_sources() == []


# ----- enabled filtering -----


def test_enabled_filter() -> None:
    plugin = LocalPdfsPlugin()
    plugin.enabled = False
    registry = SourceRegistry()
    registry.register_discovery(plugin)

    assert registry.discovery_sources(enabled_only=True) == []
    assert registry.discovery_sources(enabled_only=False) == [plugin]


# ----- resolve loop -----


class _FixedConfidenceResolver:
    def __init__(self, name: str, confidence_value: float, *, fail: bool = False) -> None:
        self.name = name
        self.enabled = True
        self._confidence = confidence_value
        self._fail = fail

    async def confidence(self, candidate: WorkCandidate) -> float:
        del candidate
        return self._confidence

    async def resolve(self, candidate: WorkCandidate) -> ResolvedFile:
        if self._fail:
            raise SourceUnavailable(f"{self.name} deliberately failed")
        return ResolvedFile(
            candidate_id=candidate.candidate_id,
            bytes_=b"%PDF stub from " + self.name.encode(),
            content_type="application/pdf",
            source_url=candidate.source_url,
            resolved_by=self.name,
        )


async def test_registry_resolve_picks_highest_confidence() -> None:
    registry = SourceRegistry()
    registry.register_resolver(_FixedConfidenceResolver("low", 0.3))
    registry.register_resolver(_FixedConfidenceResolver("high", 0.9))
    registry.register_resolver(_FixedConfidenceResolver("zero", 0.0))

    rf = await registry.resolve(_make_candidate(doi="10.1/foo"))
    assert rf.resolved_by == "high"


async def test_registry_resolve_falls_through_to_next_on_failure() -> None:
    registry = SourceRegistry()
    registry.register_resolver(_FixedConfidenceResolver("preferred", 0.9, fail=True))
    registry.register_resolver(_FixedConfidenceResolver("backup", 0.5))

    rf = await registry.resolve(_make_candidate(doi="10.1/foo"))
    assert rf.resolved_by == "backup"


async def test_registry_resolve_raises_when_no_resolvers_claim_confidence() -> None:
    registry = SourceRegistry()
    registry.register_resolver(_FixedConfidenceResolver("unhelpful", 0.0))
    with pytest.raises(SourceUnavailable, match="no enabled resolver"):
        await registry.resolve(_make_candidate())


async def test_registry_resolve_raises_when_all_resolvers_fail() -> None:
    registry = SourceRegistry()
    registry.register_resolver(_FixedConfidenceResolver("a", 0.5, fail=True))
    registry.register_resolver(_FixedConfidenceResolver("b", 0.4, fail=True))
    with pytest.raises(SourceUnavailable, match="all resolvers failed"):
        await registry.resolve(_make_candidate())


# ----- lifecycle -----


class _LifecyclePlugin:
    name: str = "lifecycle"
    enabled: bool = True
    started: bool = False
    closed: bool = False

    async def confidence(self, candidate: WorkCandidate) -> float:
        del candidate
        return 0.0

    async def resolve(self, candidate: WorkCandidate) -> ResolvedFile:
        del candidate
        raise SourceUnavailable("stub")

    async def start(self) -> None:
        self.started = True

    async def close(self) -> None:
        self.closed = True


async def test_lifecycle_callbacks_fire_when_present() -> None:
    plugin = _LifecyclePlugin()
    registry = SourceRegistry()
    registry.register_resolver(plugin)
    await registry.start_all()
    assert plugin.started is True
    await registry.close_all()
    assert plugin.closed is True
