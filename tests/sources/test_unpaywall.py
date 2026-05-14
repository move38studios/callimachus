"""Tests for the bundled Unpaywall resolver."""

from __future__ import annotations

from collections.abc import Callable

import httpx
import pytest

from callimachus.sources import Resolver, SourceUnavailable
from callimachus.sources.bundled.unpaywall import (
    UnpaywallPlugin,
    _pdf_url_from_unpaywall_record,  # pyright: ignore[reportPrivateUsage]
)
from callimachus.sources.protocols import DiscoverySource, Provenance, WorkCandidate

MockHandler = Callable[[httpx.Request], httpx.Response]


def _candidate(*, doi: str | None = "10.1234/foo") -> WorkCandidate:
    return WorkCandidate(
        title="A paper",
        source_url=f"https://doi.org/{doi}" if doi else "https://example.com/x",
        provenance=Provenance(source_name="openalex", query="x"),
        doi=doi,
    )


# ---------- record parsing ----------


def test_pdf_url_from_record_picks_best_oa_location() -> None:
    record = {
        "is_oa": True,
        "best_oa_location": {"url_for_pdf": "https://x.org/best.pdf"},
        "oa_locations": [{"url_for_pdf": "https://x.org/other.pdf"}],
    }
    assert _pdf_url_from_unpaywall_record(record) == "https://x.org/best.pdf"


def test_pdf_url_from_record_falls_back_to_locations() -> None:
    record = {
        "is_oa": True,
        "best_oa_location": {"url_for_pdf": None},
        "oa_locations": [{"url_for_pdf": "https://x.org/other.pdf"}],
    }
    assert _pdf_url_from_unpaywall_record(record) == "https://x.org/other.pdf"


def test_pdf_url_from_record_returns_none_when_not_oa() -> None:
    record = {
        "is_oa": False,
        "best_oa_location": {"url_for_pdf": "https://x.org/best.pdf"},
    }
    assert _pdf_url_from_unpaywall_record(record) is None


def test_pdf_url_from_record_returns_none_when_no_pdf() -> None:
    record: dict[str, object] = {
        "is_oa": True,
        "best_oa_location": None,
        "oa_locations": [],
    }
    assert _pdf_url_from_unpaywall_record(record) is None


# ---------- protocol conformance ----------


def test_satisfies_resolver_protocol_only() -> None:
    plugin = UnpaywallPlugin()
    assert isinstance(plugin, Resolver)
    assert not isinstance(plugin, DiscoverySource)


# ---------- confidence ----------


async def test_confidence_with_doi_returns_seventy_percent() -> None:
    plugin = UnpaywallPlugin()
    assert await plugin.confidence(_candidate(doi="10.1234/foo")) == 0.7


async def test_confidence_without_doi_returns_zero() -> None:
    plugin = UnpaywallPlugin()
    assert await plugin.confidence(_candidate(doi=None)) == 0.0


# ---------- resolve via mock transport ----------


def _attach_mock_transport(plugin: UnpaywallPlugin, handler: MockHandler) -> None:
    transport = httpx.MockTransport(handler)
    plugin._client = httpx.AsyncClient(  # pyright: ignore[reportPrivateUsage]
        transport=transport,
        follow_redirects=True,
    )


async def test_resolve_happy_path_returns_pdf_bytes() -> None:
    plugin = UnpaywallPlugin()
    pdf_bytes = b"%PDF-1.4\nfake pdf bytes"

    def handler(request: httpx.Request) -> httpx.Response:
        if "api.unpaywall.org" in str(request.url):
            assert "email" in dict(request.url.params)
            return httpx.Response(
                200,
                json={
                    "is_oa": True,
                    "best_oa_location": {"url_for_pdf": "https://example.org/paper.pdf"},
                },
            )
        if "example.org/paper.pdf" in str(request.url):
            return httpx.Response(
                200, content=pdf_bytes, headers={"content-type": "application/pdf"}
            )
        return httpx.Response(404)

    _attach_mock_transport(plugin, handler)

    resolved = await plugin.resolve(_candidate(doi="10.1234/foo"))
    assert resolved.bytes_ == pdf_bytes
    assert resolved.content_type == "application/pdf"
    assert resolved.source_url == "https://example.org/paper.pdf"
    assert resolved.resolved_by == "unpaywall"
    await plugin.close()


async def test_resolve_raises_when_doi_not_in_db() -> None:
    plugin = UnpaywallPlugin()

    def handler(request: httpx.Request) -> httpx.Response:
        del request
        return httpx.Response(404, text="Not Found")

    _attach_mock_transport(plugin, handler)

    with pytest.raises(SourceUnavailable, match="not in Unpaywall"):
        await plugin.resolve(_candidate(doi="10.1234/missing"))
    await plugin.close()


async def test_resolve_raises_when_paper_not_open_access() -> None:
    plugin = UnpaywallPlugin()

    def handler(request: httpx.Request) -> httpx.Response:
        del request
        return httpx.Response(200, json={"is_oa": False, "best_oa_location": None})

    _attach_mock_transport(plugin, handler)

    with pytest.raises(SourceUnavailable, match="no open-access PDF"):
        await plugin.resolve(_candidate(doi="10.1234/closed"))
    await plugin.close()


async def test_resolve_raises_on_http_error() -> None:
    plugin = UnpaywallPlugin()

    def handler(request: httpx.Request) -> httpx.Response:
        del request
        return httpx.Response(503)

    _attach_mock_transport(plugin, handler)

    with pytest.raises(SourceUnavailable, match="HTTP 503"):
        await plugin.resolve(_candidate(doi="10.1234/foo"))
    await plugin.close()


async def test_resolve_raises_when_pdf_fetch_returns_html() -> None:
    """Some hosts return 200 + an HTML login wall when they meant to give a PDF."""
    plugin = UnpaywallPlugin()

    def handler(request: httpx.Request) -> httpx.Response:
        if "api.unpaywall.org" in str(request.url):
            return httpx.Response(
                200,
                json={
                    "is_oa": True,
                    "best_oa_location": {"url_for_pdf": "https://example.org/paper.pdf"},
                },
            )
        return httpx.Response(
            200,
            content=b"<html>login required</html>",
            headers={"content-type": "text/html"},
        )

    _attach_mock_transport(plugin, handler)

    with pytest.raises(SourceUnavailable, match="not a PDF"):
        await plugin.resolve(_candidate(doi="10.1234/foo"))
    await plugin.close()


async def test_resolve_raises_when_no_doi_on_candidate() -> None:
    plugin = UnpaywallPlugin()
    cand = WorkCandidate(
        title="No DOI",
        source_url="https://example.com/x",
        provenance=Provenance(source_name="x", query="q"),
    )
    with pytest.raises(SourceUnavailable, match="no DOI"):
        await plugin.resolve(cand)


# ---------- live test ----------


@pytest.mark.live
async def test_live_resolve_against_known_oa_paper() -> None:
    """Resolve a known open-access DOI with a direct PDF URL in Unpaywall.

    BMC Bioinformatics is reliably OA and Unpaywall has direct PDF URLs.
    """
    cand = _candidate(doi="10.1186/s12859-022-04733-8")
    plugin = UnpaywallPlugin()
    await plugin.start()
    try:
        resolved = await plugin.resolve(cand)
        assert resolved.bytes_.startswith(b"%PDF")
        assert len(resolved.bytes_) > 10_000
    finally:
        await plugin.close()
