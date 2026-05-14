"""Tests for the bundled arxiv plugin.

Unit tests run against a fixture XML response (no network). The live
test (real arxiv API) is gated behind `pytest -m live` so default CI
runs offline.
"""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest

from callimachus.sources import (
    DiscoverySource,
    Provenance,
    Resolver,
    SourceUnavailable,
    WorkCandidate,
)
from callimachus.sources.bundled.arxiv import (
    ArxivPlugin,
    extract_arxiv_id,
    parse_atom_response,
)

FIXTURE_DIR = Path(__file__).parent / "fixtures"
ATOM_FIXTURE = (FIXTURE_DIR / "arxiv_atom_response.xml").read_text()


# ---------- extract_arxiv_id ----------


@pytest.mark.parametrize(
    "input_str, expected",
    [
        ("2006.11239", "2006.11239"),
        ("2006.11239v1", "2006.11239"),
        ("2006.11239v22", "2006.11239"),
        ("http://arxiv.org/abs/2006.11239v2", "2006.11239"),
        ("https://arxiv.org/abs/2006.11239", "2006.11239"),
        ("https://arxiv.org/pdf/2006.11239v1.pdf", "2006.11239"),
        ("https://arxiv.org/e-print/2006.11239", "2006.11239"),
        ("https://export.arxiv.org/abs/2006.11239", "2006.11239"),
        ("https://www.arxiv.org/abs/2006.11239", "2006.11239"),
        ("arXiv:2006.11239", "2006.11239"),
        ("hep-th/0001234", "hep-th/0001234"),
        ("http://arxiv.org/abs/hep-th/0001234v3", "hep-th/0001234"),
        ("not an arxiv id at all", None),
        ("", None),
        (None, None),
        # Regression: the previous loose pattern matched [a-z]+/\d+ anywhere,
        # so these all produced false-positive arxiv IDs.
        ("https://doi.org/10.1145/3531146.3533088", None),
        ("https://www.springer.com/article/10.1007/s10462-025-11389-2", None),
        ("https://link.springer.com/chapter/10.1007/978-3-031-18576-2_12", None),
        ("https://example.com/paper.pdf", None),
        ("https://openaccess.thecvf.com/content/CVPR2023/papers/Foo.pdf", None),
        # And the bare-DOI case
        ("10.1145/3531146.3533088", None),
    ],
)
def test_extract_arxiv_id(input_str: str | None, expected: str | None) -> None:
    assert extract_arxiv_id(input_str) == expected


# ---------- parser ----------


def test_parse_atom_response_extracts_three_papers() -> None:
    candidates = parse_atom_response(ATOM_FIXTURE, query="diffusion models")
    assert len(candidates) == 3


def test_parse_atom_response_first_entry_is_ho_2020() -> None:
    candidates = parse_atom_response(ATOM_FIXTURE, query="diffusion models")
    ho = candidates[0]
    assert ho.title == "Denoising Diffusion Probabilistic Models"
    assert ho.arxiv_id == "2006.11239"
    assert ho.year == 2020
    assert ho.kind == "paper"
    assert ho.source_url == "https://arxiv.org/abs/2006.11239"
    assert ho.pdf_url == "http://arxiv.org/pdf/2006.11239v2"
    assert ho.authors == ["Jonathan Ho", "Ajay Jain", "Pieter Abbeel"]
    assert ho.abstract is not None
    assert "diffusion" in ho.abstract.lower()
    assert ho.provenance.source_name == "arxiv"
    assert ho.provenance.query == "diffusion models"


def test_parse_atom_response_handles_multiline_titles() -> None:
    candidates = parse_atom_response(ATOM_FIXTURE, query="x")
    # Score-Based paper has a wrapped title in the fixture
    score_based = candidates[1]
    assert (
        score_based.title
        == "Score-Based Generative Modeling through Stochastic Differential Equations"
    )


def test_parse_atom_response_normalizes_abstract_whitespace() -> None:
    candidates = parse_atom_response(ATOM_FIXTURE, query="x")
    assert candidates[0].abstract is not None
    assert "\n" not in candidates[0].abstract  # no embedded newlines
    assert "  " not in candidates[0].abstract  # no double spaces


def test_parse_atom_response_invalid_xml_raises_source_unavailable() -> None:
    with pytest.raises(SourceUnavailable, match="failed to parse"):
        parse_atom_response("<not valid xml", query="x")


def test_parse_atom_response_empty_feed_returns_empty_list() -> None:
    empty_feed = '<?xml version="1.0"?><feed xmlns="http://www.w3.org/2005/Atom"/>'
    candidates = parse_atom_response(empty_feed, query="x")
    assert candidates == []


# ---------- protocol conformance ----------


def test_arxiv_plugin_satisfies_both_protocols() -> None:
    plugin = ArxivPlugin()
    assert isinstance(plugin, DiscoverySource)
    assert isinstance(plugin, Resolver)


# ---------- confidence ----------


async def test_confidence_is_one_for_arxiv_id() -> None:
    plugin = ArxivPlugin()
    candidate = WorkCandidate(
        title="x",
        source_url="https://example.org/x",
        provenance=Provenance(source_name="other", query="q"),
        arxiv_id="2006.11239",
    )
    assert await plugin.confidence(candidate) == 1.0


async def test_confidence_is_one_for_arxiv_url() -> None:
    plugin = ArxivPlugin()
    candidate = WorkCandidate(
        title="x",
        source_url="https://arxiv.org/abs/2006.11239",
        provenance=Provenance(source_name="other", query="q"),
    )
    assert await plugin.confidence(candidate) == 1.0


async def test_confidence_is_zero_for_non_arxiv_candidate() -> None:
    plugin = ArxivPlugin()
    candidate = WorkCandidate(
        title="x",
        source_url="https://example.org/something",
        provenance=Provenance(source_name="other", query="q"),
        doi="10.1234/foo",
    )
    assert await plugin.confidence(candidate) == 0.0


# ---------- search via mock transport (no network) ----------


async def test_search_parses_response_via_mock_transport(monkeypatch: pytest.MonkeyPatch) -> None:
    """Mock httpx so we can verify search() flows through the parser."""
    plugin = ArxivPlugin()

    def mock_handler(request: httpx.Request) -> httpx.Response:
        # Sanity: we hit arxiv with the right shape
        assert "export.arxiv.org" in str(request.url)
        assert "search_query" in dict(request.url.params)
        return httpx.Response(200, text=ATOM_FIXTURE)

    transport = httpx.MockTransport(mock_handler)
    plugin._client = httpx.AsyncClient(transport=transport, follow_redirects=True)  # pyright: ignore[reportPrivateUsage]

    # Bypass rate limit for the test
    monkeypatch.setattr(plugin, "_wait_for_rate_limit", lambda: _no_wait())

    results = await plugin.search("diffusion models", limit=5)
    assert len(results) == 3
    assert results[0].arxiv_id == "2006.11239"

    await plugin.close()


async def test_search_translates_http_error_to_source_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plugin = ArxivPlugin()

    def mock_handler(request: httpx.Request) -> httpx.Response:
        del request
        return httpx.Response(429, text="rate limited")

    transport = httpx.MockTransport(mock_handler)
    plugin._client = httpx.AsyncClient(transport=transport, follow_redirects=True)  # pyright: ignore[reportPrivateUsage]
    monkeypatch.setattr(plugin, "_wait_for_rate_limit", lambda: _no_wait())

    with pytest.raises(SourceUnavailable, match="arxiv:"):
        await plugin.search("anything")
    await plugin.close()


async def _no_wait() -> None:
    return None


# ---------- resolve via mock transport ----------


async def test_resolve_returns_latex_source_when_available(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plugin = ArxivPlugin()

    def mock_handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if "/e-print/" in url:
            return httpx.Response(
                200,
                content=b"\x1f\x8b\x08stub-tar-bytes",
                headers={"content-type": "application/x-tar"},
            )
        # PDF fallback shouldn't be reached
        return httpx.Response(404)

    transport = httpx.MockTransport(mock_handler)
    plugin._client = httpx.AsyncClient(transport=transport, follow_redirects=True)  # pyright: ignore[reportPrivateUsage]
    monkeypatch.setattr(plugin, "_wait_for_rate_limit", lambda: _no_wait())

    candidate = WorkCandidate(
        title="DDPM",
        source_url="https://arxiv.org/abs/2006.11239",
        provenance=Provenance(source_name="arxiv", query="q"),
        arxiv_id="2006.11239",
    )
    result = await plugin.resolve(candidate)
    assert result.bytes_ == b"\x1f\x8b\x08stub-tar-bytes"
    assert result.content_type == "application/x-tar"
    assert "/e-print/" in result.source_url
    assert result.resolved_by == "arxiv"
    await plugin.close()


async def test_resolve_falls_back_to_pdf_when_latex_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plugin = ArxivPlugin()

    def mock_handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if "/e-print/" in url:
            return httpx.Response(404)  # no LaTeX source
        if "/pdf/" in url:
            return httpx.Response(200, content=b"%PDF-1.4 stub")
        return httpx.Response(404)

    transport = httpx.MockTransport(mock_handler)
    plugin._client = httpx.AsyncClient(transport=transport, follow_redirects=True)  # pyright: ignore[reportPrivateUsage]
    monkeypatch.setattr(plugin, "_wait_for_rate_limit", lambda: _no_wait())

    candidate = WorkCandidate(
        title="DDPM",
        source_url="https://arxiv.org/abs/2006.11239",
        provenance=Provenance(source_name="arxiv", query="q"),
        arxiv_id="2006.11239",
    )
    result = await plugin.resolve(candidate)
    assert result.bytes_ == b"%PDF-1.4 stub"
    assert result.content_type == "application/pdf"
    await plugin.close()


async def test_resolve_raises_when_no_arxiv_id() -> None:
    plugin = ArxivPlugin()
    candidate = WorkCandidate(
        title="x",
        source_url="https://example.org/x",
        provenance=Provenance(source_name="other", query="q"),
    )
    with pytest.raises(SourceUnavailable, match="no arxiv_id"):
        await plugin.resolve(candidate)


# ---------- live test (real network — gated) ----------


@pytest.mark.live
async def test_live_search_returns_real_diffusion_results() -> None:
    """Hit the real arxiv API. Skipped in default CI."""
    plugin = ArxivPlugin()
    await plugin.start()
    try:
        results = await plugin.search("diffusion models", limit=3)
        assert len(results) > 0
        assert all(r.arxiv_id for r in results)
        assert all(r.provenance.source_name == "arxiv" for r in results)
    finally:
        await plugin.close()
