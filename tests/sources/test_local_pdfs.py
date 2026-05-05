"""Tests for the bundled local_pdfs plugin."""

from __future__ import annotations

from pathlib import Path

import pytest

from callimachus.sources import (
    DiscoverySource,
    Provenance,
    Resolver,
    SourceUnavailable,
    WorkCandidate,
)
from callimachus.sources.bundled.local_pdfs import LocalPdfsPlugin

# A 1KB stub that's at least syntactically a PDF; not parseable as a real one
# but local_pdfs doesn't care — it just returns bytes.
STUB_PDF = b"%PDF-1.4\n" + b"\x00" * 1000 + b"\n%%EOF"


@pytest.fixture
def pdf_dir(tmp_path: Path) -> Path:
    """A directory with three fixture PDFs."""
    (tmp_path / "ho-2020-denoising-diffusion-probabilistic-models.pdf").write_bytes(STUB_PDF)
    (tmp_path / "song-2021-score-based-sde.pdf").write_bytes(STUB_PDF)
    (tmp_path / "rombach-2022-latent-diffusion.pdf").write_bytes(STUB_PDF)
    # A non-PDF that should be ignored
    (tmp_path / "notes.txt").write_text("ignore me")
    return tmp_path


def test_satisfies_both_protocols() -> None:
    plugin = LocalPdfsPlugin()
    assert isinstance(plugin, DiscoverySource)
    assert isinstance(plugin, Resolver)


async def test_search_returns_matches_for_query(pdf_dir: Path) -> None:
    plugin = LocalPdfsPlugin(paths=[pdf_dir])
    results = await plugin.search("denoising")
    assert len(results) == 1
    assert "denoising" in results[0].title.lower()
    assert results[0].provenance.source_name == "local_pdfs"
    local_path = results[0].extras.get("local_path")
    assert isinstance(local_path, str) and local_path.endswith(".pdf")


async def test_search_returns_all_when_query_empty(pdf_dir: Path) -> None:
    plugin = LocalPdfsPlugin(paths=[pdf_dir])
    results = await plugin.search("")
    titles = {r.title.lower() for r in results}
    assert len(results) == 3
    assert any("denoising" in t for t in titles)
    assert any("score" in t for t in titles)
    assert any("latent" in t for t in titles)


async def test_search_respects_limit(pdf_dir: Path) -> None:
    plugin = LocalPdfsPlugin(paths=[pdf_dir])
    results = await plugin.search("", limit=2)
    assert len(results) == 2


async def test_search_returns_nothing_for_unknown_query(pdf_dir: Path) -> None:
    plugin = LocalPdfsPlugin(paths=[pdf_dir])
    results = await plugin.search("quantum")
    assert results == []


async def test_search_handles_missing_path(tmp_path: Path) -> None:
    # paths includes a nonexistent dir; should silently skip
    plugin = LocalPdfsPlugin(paths=[tmp_path / "does_not_exist"])
    assert await plugin.search("anything") == []


async def test_confidence_is_one_when_local_path_set(pdf_dir: Path) -> None:
    plugin = LocalPdfsPlugin(paths=[pdf_dir])
    found = await plugin.search("ho")
    assert len(found) == 1
    assert await plugin.confidence(found[0]) == 1.0


async def test_confidence_is_one_via_title_match(pdf_dir: Path) -> None:
    plugin = LocalPdfsPlugin(paths=[pdf_dir])
    candidate = WorkCandidate(
        title="ho 2020 denoising diffusion probabilistic models",
        source_url="https://arxiv.org/abs/2006.11239",
        provenance=Provenance(source_name="someone_else", query="diffusion"),
    )
    assert await plugin.confidence(candidate) == 1.0


async def test_confidence_is_zero_when_no_match(pdf_dir: Path) -> None:
    plugin = LocalPdfsPlugin(paths=[pdf_dir])
    candidate = WorkCandidate(
        title="quantum entanglement and Bell's theorem",
        source_url="https://example.org/x",
        provenance=Provenance(source_name="test", query="q"),
    )
    assert await plugin.confidence(candidate) == 0.0


async def test_resolve_returns_bytes(pdf_dir: Path) -> None:
    plugin = LocalPdfsPlugin(paths=[pdf_dir])
    found = await plugin.search("score")
    assert len(found) == 1
    rf = await plugin.resolve(found[0])
    assert rf.bytes_ == STUB_PDF
    assert rf.content_type == "application/pdf"
    assert rf.resolved_by == "local_pdfs"
    assert rf.candidate_id == found[0].candidate_id


async def test_resolve_raises_source_unavailable_on_no_match(pdf_dir: Path) -> None:
    plugin = LocalPdfsPlugin(paths=[pdf_dir])
    candidate = WorkCandidate(
        title="quantum entanglement",
        source_url="https://example.org/x",
        provenance=Provenance(source_name="test", query="q"),
    )
    with pytest.raises(SourceUnavailable, match="local_pdfs"):
        await plugin.resolve(candidate)


async def test_disabled_plugin_can_be_set() -> None:
    plugin = LocalPdfsPlugin()
    plugin.enabled = False
    assert plugin.enabled is False
