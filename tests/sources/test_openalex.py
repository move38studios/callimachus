"""Tests for the bundled OpenAlex plugin."""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from callimachus.sources import DiscoverySource, Resolver, SourceUnavailable
from callimachus.sources.bundled.openalex import (
    OpenAlexPlugin,
    arxiv_id_from_openalex_record,
    candidate_from_openalex_record,
    normalize_doi,
    reconstruct_abstract,
)

FIXTURE = Path(__file__).parent / "fixtures" / "openalex_response.json"


# ---------- helpers ----------


def test_reconstruct_abstract_simple() -> None:
    inverted = {"hello": [0], "world": [1], "again": [2]}
    assert reconstruct_abstract(inverted) == "hello world again"


def test_reconstruct_abstract_with_repeats() -> None:
    inverted = {"the": [0, 4, 7], "cat": [1], "and": [2], "dog": [3, 5]}
    # positions 0..7 → 'the cat and dog the dog ? the'
    # Position 6 is missing → empty word skipped
    text = reconstruct_abstract(inverted) or ""
    assert text.startswith("the cat and dog")
    assert "the" in text


def test_reconstruct_abstract_empty_returns_none() -> None:
    assert reconstruct_abstract(None) is None
    assert reconstruct_abstract({}) is None


@pytest.mark.parametrize(
    "url, expected",
    [
        ("https://doi.org/10.1234/foo", "10.1234/foo"),
        ("https://doi.org/10.48550/arxiv.2006.11239", "10.48550/arxiv.2006.11239"),
        ("10.1234/already-bare", "10.1234/already-bare"),
        (None, None),
        ("", None),
    ],
)
def test_normalize_doi(url: str | None, expected: str | None) -> None:
    assert normalize_doi(url) == expected


def test_arxiv_id_from_arxiv_doi() -> None:
    record = {"doi": "https://doi.org/10.48550/arxiv.2006.11239"}
    assert arxiv_id_from_openalex_record(record) == "2006.11239"


def test_arxiv_id_from_landing_url() -> None:
    record = {
        "doi": "https://doi.org/10.1234/foo",  # non-arxiv DOI
        "best_oa_location": {"landing_page_url": "http://arxiv.org/abs/2006.11239v1"},
    }
    assert arxiv_id_from_openalex_record(record) == "2006.11239"


def test_arxiv_id_returns_none_for_non_arxiv() -> None:
    record = {
        "doi": "https://doi.org/10.1109/cvpr52688.2022.01117",
        "best_oa_location": {"landing_page_url": "https://example.org/paper"},
    }
    assert arxiv_id_from_openalex_record(record) is None


# ---------- candidate_from_openalex_record ----------


def test_candidate_from_clean_record() -> None:
    """Use a synthetic clean record (the fixture's first row has known data issues)."""
    record = {
        "title": "Improved Denoising Diffusion Probabilistic Models",
        "doi": "https://doi.org/10.48550/arxiv.2102.09672",
        "publication_year": 2021,
        "cited_by_count": 412,
        "authorships": [
            {"author": {"display_name": "Alex Nichol"}},
            {"author": {"display_name": "Prafulla Dhariwal"}},
        ],
        "primary_location": {"source": {"display_name": "arXiv (Cornell University)"}},
        "best_oa_location": {
            "landing_page_url": "http://arxiv.org/abs/2102.09672",
            "pdf_url": "https://arxiv.org/pdf/2102.09672",
        },
        "abstract_inverted_index": {"Denoising": [0], "diffusion": [1], "models": [2]},
        "ids": {"openalex": "https://openalex.org/W3128345567"},
    }
    cand = candidate_from_openalex_record(record, "diffusion")
    assert cand is not None
    assert cand.title == "Improved Denoising Diffusion Probabilistic Models"
    assert cand.doi == "10.48550/arxiv.2102.09672"
    assert cand.arxiv_id == "2102.09672"
    assert cand.year == 2021
    assert cand.authors == ["Alex Nichol", "Prafulla Dhariwal"]
    assert cand.venue == "arXiv (Cornell University)"
    assert cand.pdf_url == "https://arxiv.org/pdf/2102.09672"
    assert cand.abstract == "Denoising diffusion models"
    assert cand.extras["cited_by_count"] == 412
    assert cand.extras["openalex_id"] == "https://openalex.org/W3128345567"
    assert cand.provenance.source_name == "openalex"


def test_candidate_from_titleless_record_returns_none() -> None:
    cand = candidate_from_openalex_record({"title": None}, "x")
    assert cand is None


def test_candidate_with_no_url_returns_none() -> None:
    """No DOI, no arxiv_id, no landing page, no openalex id → no candidate."""
    record: dict[str, object] = {
        "title": "x",
        "doi": None,
        "best_oa_location": None,
        "ids": {},
    }
    assert candidate_from_openalex_record(record, "x") is None


# ---------- response parsing against the live fixture ----------


def test_parses_real_fixture_response() -> None:
    data = json.loads(FIXTURE.read_text())
    candidates = [candidate_from_openalex_record(r, "denoising diffusion") for r in data["results"]]
    candidates = [c for c in candidates if c is not None]
    # The fixture has 5 records; the first has corrupt OpenAlex data (right title,
    # wrong author/abstract) but should still parse — we let the judge filter quality.
    assert len(candidates) == 5
    assert all(c.provenance.source_name == "openalex" for c in candidates)
    # At least one should have an arxiv_id (the DDPM-titled record)
    assert any(c.arxiv_id == "2006.11239" for c in candidates)
    # Most should have authors and years
    assert sum(1 for c in candidates if c.authors) >= 4
    assert sum(1 for c in candidates if c.year) >= 4


# ---------- protocol conformance ----------


def test_satisfies_discovery_protocol_only() -> None:
    plugin = OpenAlexPlugin()
    assert isinstance(plugin, DiscoverySource)
    # OpenAlex doesn't implement Resolver
    assert not isinstance(plugin, Resolver)


# ---------- search via mock transport ----------


async def test_search_uses_mock_transport() -> None:
    """Mock httpx so search() flows the fixture through the parser."""
    plugin = OpenAlexPlugin()
    fixture_data = json.loads(FIXTURE.read_text())

    def mock_handler(request: httpx.Request) -> httpx.Response:
        assert "api.openalex.org" in str(request.url)
        # mailto present (polite-pool etiquette)
        assert "mailto" in dict(request.url.params)
        return httpx.Response(200, json=fixture_data)

    transport = httpx.MockTransport(mock_handler)
    plugin._client = httpx.AsyncClient(  # pyright: ignore[reportPrivateUsage]
        transport=transport,
        follow_redirects=True,
    )

    results = await plugin.search("denoising diffusion", limit=5)
    assert len(results) == 5
    assert all(c.provenance.source_name == "openalex" for c in results)
    await plugin.close()


async def test_search_translates_http_error_to_source_unavailable() -> None:
    plugin = OpenAlexPlugin()

    def mock_handler(request: httpx.Request) -> httpx.Response:
        del request
        return httpx.Response(503, text="service unavailable")

    transport = httpx.MockTransport(mock_handler)
    plugin._client = httpx.AsyncClient(  # pyright: ignore[reportPrivateUsage]
        transport=transport,
        follow_redirects=True,
    )

    with pytest.raises(SourceUnavailable, match="openalex:"):
        await plugin.search("anything")
    await plugin.close()


async def test_search_includes_year_filter_when_provided() -> None:
    plugin = OpenAlexPlugin()
    captured: dict[str, str] = {}

    def mock_handler(request: httpx.Request) -> httpx.Response:
        captured.update(dict(request.url.params))
        return httpx.Response(200, json={"results": []})

    transport = httpx.MockTransport(mock_handler)
    plugin._client = httpx.AsyncClient(  # pyright: ignore[reportPrivateUsage]
        transport=transport,
        follow_redirects=True,
    )

    await plugin.search("x", year_from=2020, year_to=2024)
    assert "filter" in captured
    assert "publication_year:2020-2024" in captured["filter"]
    await plugin.close()


# ---------- live test ----------


@pytest.mark.live
async def test_live_search_returns_real_results() -> None:
    """Hit the real OpenAlex API. Skipped in default CI."""
    plugin = OpenAlexPlugin()
    await plugin.start()
    try:
        results = await plugin.search("diffusion models", limit=3)
        assert len(results) >= 1
        assert all(r.provenance.source_name == "openalex" for r in results)
        assert all(r.title for r in results)
    finally:
        await plugin.close()
