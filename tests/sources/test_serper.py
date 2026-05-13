"""Tests for the bundled Serper plugins (web + scholar)."""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from callimachus.sources import DiscoverySource, Resolver, SourceUnavailable
from callimachus.sources.bundled.serper import (
    SerperScholarPlugin,
    SerperWebPlugin,
    parse_publication_info,
    parse_year_from_date,
    scholar_candidate_from_record,
    web_candidate_from_record,
)

FIXTURES = Path(__file__).parent / "fixtures"
SCHOLAR_FIXTURE = FIXTURES / "serper_scholar_response.json"
WEB_FIXTURE = FIXTURES / "serper_web_response.json"


# ---------- helpers ----------


@pytest.mark.parametrize(
    "date_str, expected",
    [
        ("Jun 22, 2023", 2023),
        ("Jan 30, 2025", 2025),
        ("1999", 1999),
        (None, None),
        ("", None),
        ("no year here", None),
    ],
)
def test_parse_year_from_date(date_str: str | None, expected: int | None) -> None:
    assert parse_year_from_date(date_str) == expected


def test_parse_publication_info_full() -> None:
    info = "J Ho, A Jain, P Abbeel - Advances in neural information processing systems, 2020"
    authors, venue = parse_publication_info(info)
    assert authors == ["J Ho", "A Jain", "P Abbeel"]
    assert venue == "Advances in neural information processing systems, 2020"


def test_parse_publication_info_with_trailing_domain() -> None:
    info = "Y Zhu, Z Li, T Wang, M He… - Proceedings of the IEEE …, 2023 - openaccess.thecvf.com"
    authors, venue = parse_publication_info(info)
    # The trailing " - openaccess.thecvf.com" is ignored
    assert authors == ["Y Zhu", "Z Li", "T Wang", "M He…"]
    assert venue == "Proceedings of the IEEE …, 2023"


def test_parse_publication_info_empty() -> None:
    assert parse_publication_info(None) == ([], None)
    assert parse_publication_info("") == ([], None)


def test_parse_publication_info_no_separator() -> None:
    """Some entries have no ' - ' delimiter; treat the whole string as authors."""
    authors, venue = parse_publication_info("Single Author Name")
    assert authors == ["Single Author Name"]
    assert venue is None


# ---------- scholar mapping ----------


def test_scholar_candidate_from_clean_record() -> None:
    record = {
        "title": "Cascaded diffusion models for high fidelity image generation",
        "link": "http://www.jmlr.org/papers/v23/21-0635.html",
        "publicationInfo": "J Ho, C Saharia, W Chan - Journal of Machine Learning Research, 2022",
        "snippet": "diffusion models are capable of generating high fidelity images…",
        "year": 2022,
        "citedBy": 1802,
        "pdfUrl": "http://www.jmlr.org/papers/volume23/21-0635/21-0635.pdf",
        "id": "WdZyna4pP5IJ",
    }
    cand = scholar_candidate_from_record(record, "diffusion", source_name="serper_scholar")
    assert cand is not None
    assert cand.title.startswith("Cascaded diffusion models")
    assert cand.source_url == "http://www.jmlr.org/papers/v23/21-0635.html"
    assert cand.year == 2022
    assert cand.authors == ["J Ho", "C Saharia", "W Chan"]
    assert cand.venue == "Journal of Machine Learning Research, 2022"
    assert cand.pdf_url == "http://www.jmlr.org/papers/volume23/21-0635/21-0635.pdf"
    assert cand.extras["cited_by_count"] == 1802
    assert cand.extras["serper_id"] == "WdZyna4pP5IJ"
    assert cand.kind == "paper"
    assert cand.provenance.source_name == "serper_scholar"


def test_scholar_candidate_without_title_returns_none() -> None:
    assert (
        scholar_candidate_from_record(
            {"link": "https://x", "title": ""}, "q", source_name="serper_scholar"
        )
        is None
    )


def test_scholar_candidate_without_link_returns_none() -> None:
    assert (
        scholar_candidate_from_record({"title": "t", "link": ""}, "q", source_name="serper_scholar")
        is None
    )


# ---------- web mapping ----------


def test_web_candidate_from_clean_record() -> None:
    record = {
        "title": "Brief Introduction to Diffusion Models for Image Generation",
        "link": "https://www.machinelearningmastery.com/brief-introduction-to-diffusion-models/",
        "snippet": "Diffusion models are a family of neural network models…",
        "date": "Jul 18, 2024",
        "position": 2,
    }
    cand = web_candidate_from_record(record, "diffusion", source_name="serper_web")
    assert cand is not None
    assert cand.year == 2024
    assert cand.kind == "essay"
    assert cand.extras["serper_position"] == 2
    assert cand.extras["serper_date"] == "Jul 18, 2024"
    assert cand.pdf_url is None  # web results don't carry one
    assert cand.provenance.source_name == "serper_web"


# ---------- fixture round-trips ----------


def test_parses_real_scholar_fixture() -> None:
    data = json.loads(SCHOLAR_FIXTURE.read_text())
    cands = [
        scholar_candidate_from_record(r, "diffusion", source_name="serper_scholar")
        for r in data["organic"]
    ]
    cands = [c for c in cands if c is not None]
    assert len(cands) >= 5
    # Every scholar result should have a year and most should have authors
    assert all(c.year is not None for c in cands)
    assert sum(1 for c in cands if c.authors) >= len(cands) - 1
    # Most should have a pdf
    assert sum(1 for c in cands if c.pdf_url) >= len(cands) - 1
    # citedBy should land in extras
    assert all("cited_by_count" in c.extras for c in cands)


def test_parses_real_web_fixture() -> None:
    data = json.loads(WEB_FIXTURE.read_text())
    cands = [
        web_candidate_from_record(r, "diffusion", source_name="serper_web") for r in data["organic"]
    ]
    cands = [c for c in cands if c is not None]
    assert len(cands) >= 5
    assert all(c.kind == "essay" for c in cands)


# ---------- protocol conformance ----------


def test_scholar_satisfies_discovery_protocol_only() -> None:
    plugin = SerperScholarPlugin()
    assert isinstance(plugin, DiscoverySource)
    assert not isinstance(plugin, Resolver)
    assert plugin.kind == "bibliographic"


def test_web_satisfies_discovery_protocol_only() -> None:
    plugin = SerperWebPlugin()
    assert isinstance(plugin, DiscoverySource)
    assert not isinstance(plugin, Resolver)
    assert plugin.kind == "web"


# ---------- search via mock transport ----------


async def test_scholar_search_uses_mock_transport(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SERPER_API_KEY", "test-key-123")
    plugin = SerperScholarPlugin()
    fixture = json.loads(SCHOLAR_FIXTURE.read_text())

    def mock_handler(request: httpx.Request) -> httpx.Response:
        assert str(request.url) == "https://google.serper.dev/scholar"
        assert request.headers.get("x-api-key") == "test-key-123"
        body = json.loads(request.content)
        assert body["q"] == "diffusion"
        return httpx.Response(200, json=fixture)

    transport = httpx.MockTransport(mock_handler)
    plugin._client = httpx.AsyncClient(  # pyright: ignore[reportPrivateUsage]
        transport=transport,
        headers={"Content-Type": "application/json"},
    )

    results = await plugin.search("diffusion", limit=5)
    assert len(results) >= 5
    assert all(c.provenance.source_name == "serper_scholar" for c in results)
    await plugin.close()


async def test_web_search_uses_mock_transport(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SERPER_API_KEY", "test-key-123")
    plugin = SerperWebPlugin()
    fixture = json.loads(WEB_FIXTURE.read_text())

    def mock_handler(request: httpx.Request) -> httpx.Response:
        assert str(request.url) == "https://google.serper.dev/search"
        return httpx.Response(200, json=fixture)

    transport = httpx.MockTransport(mock_handler)
    plugin._client = httpx.AsyncClient(  # pyright: ignore[reportPrivateUsage]
        transport=transport,
        headers={"Content-Type": "application/json"},
    )

    results = await plugin.search("diffusion", limit=5)
    assert len(results) >= 5
    assert all(c.kind == "essay" for c in results)
    await plugin.close()


async def test_search_translates_http_error_to_source_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SERPER_API_KEY", "test-key-123")
    plugin = SerperScholarPlugin()

    def mock_handler(request: httpx.Request) -> httpx.Response:
        del request
        return httpx.Response(503, text="service unavailable")

    transport = httpx.MockTransport(mock_handler)
    plugin._client = httpx.AsyncClient(  # pyright: ignore[reportPrivateUsage]
        transport=transport,
        headers={"Content-Type": "application/json"},
    )

    with pytest.raises(SourceUnavailable, match="serper_scholar:"):
        await plugin.search("anything")
    await plugin.close()


async def test_search_raises_when_api_key_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    """Plugin loads fine without the key; the failure happens at search()."""
    monkeypatch.delenv("SERPER_API_KEY", raising=False)
    plugin = SerperScholarPlugin()
    with pytest.raises(SourceUnavailable, match="SERPER_API_KEY"):
        await plugin.search("anything")


async def test_search_includes_year_filter_when_provided(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SERPER_API_KEY", "test-key-123")
    plugin = SerperScholarPlugin()
    captured: dict[str, object] = {}

    def mock_handler(request: httpx.Request) -> httpx.Response:
        captured.update(json.loads(request.content))
        return httpx.Response(200, json={"organic": []})

    transport = httpx.MockTransport(mock_handler)
    plugin._client = httpx.AsyncClient(  # pyright: ignore[reportPrivateUsage]
        transport=transport,
        headers={"Content-Type": "application/json"},
    )

    await plugin.search("x", year_from=2020, year_to=2024)
    assert captured.get("tbs") == "cdr:1,cd_min:2020,cd_max:2024"
    await plugin.close()


# ---------- live test ----------


@pytest.mark.live
async def test_live_scholar_search() -> None:
    """Hit the real Serper /scholar endpoint. Skipped in default CI."""
    plugin = SerperScholarPlugin()
    await plugin.start()
    try:
        results = await plugin.search("diffusion models", limit=3)
        assert len(results) >= 1
        assert all(r.title for r in results)
    finally:
        await plugin.close()


@pytest.mark.live
async def test_live_web_search() -> None:
    """Hit the real Serper /search endpoint. Skipped in default CI."""
    plugin = SerperWebPlugin()
    await plugin.start()
    try:
        results = await plugin.search("diffusion models", limit=3)
        assert len(results) >= 1
    finally:
        await plugin.close()
