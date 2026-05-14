"""Tests for the bundled Perplexity discovery source plugin."""

from __future__ import annotations

import json
from collections.abc import Callable

import httpx
import pytest

from callimachus.sources import DiscoverySource, Resolver, SourceUnavailable
from callimachus.sources.bundled.perplexity import (
    PerplexityPlugin,
    candidate_from_citation,
    extract_doi,
)

MockHandler = Callable[[httpx.Request], httpx.Response]


# ---------- extract_doi ----------


@pytest.mark.parametrize(
    "url, expected",
    [
        ("https://doi.org/10.1234/foo", "10.1234/foo"),
        ("https://dx.doi.org/10.1234/foo", "10.1234/foo"),
        ("http://doi.org/10.1234/foo", "10.1234/foo"),
        ("https://doi.org/10.48550/arxiv.2006.11239", "10.48550/arxiv.2006.11239"),
        ("https://doi.org/10.1234/foo?utm_source=x", "10.1234/foo"),
        ("https://example.com/article", None),
        ("https://arxiv.org/abs/2006.11239", None),
        ("", None),
    ],
)
def test_extract_doi(url: str, expected: str | None) -> None:
    assert extract_doi(url) == expected


# ---------- candidate_from_citation ----------


def _annotation(url: str, title: str) -> dict[str, object]:
    return {"type": "url_citation", "url_citation": {"url": url, "title": title}}


def test_citation_with_arxiv_url_gets_arxiv_id() -> None:
    annotation = _annotation("https://arxiv.org/abs/2006.11239", "DDPM Paper")
    cand = candidate_from_citation(annotation, "diffusion", source_name="perplexity")
    assert cand is not None
    assert cand.arxiv_id == "2006.11239"
    assert cand.doi is None
    assert cand.kind == "paper"


def test_citation_with_doi_url_gets_doi() -> None:
    annotation = _annotation("https://doi.org/10.1145/3531146.3533088", "FAccT paper")
    cand = candidate_from_citation(annotation, "ethics", source_name="perplexity")
    assert cand is not None
    assert cand.doi == "10.1145/3531146.3533088"
    assert cand.arxiv_id is None
    assert cand.kind == "paper"


def test_citation_with_arxiv_doi_prefers_arxiv_id() -> None:
    """Arxiv DOIs (10.48550/arxiv.X) should still produce an arxiv_id."""
    annotation = _annotation("https://arxiv.org/abs/2006.11239v2", "DDPM v2")
    cand = candidate_from_citation(annotation, "x", source_name="perplexity")
    assert cand is not None
    assert cand.arxiv_id == "2006.11239"


def test_citation_with_generic_url_kind_essay() -> None:
    annotation = _annotation("https://en.wikipedia.org/wiki/Diffusion_model", "Wikipedia")
    cand = candidate_from_citation(annotation, "x", source_name="perplexity")
    assert cand is not None
    assert cand.kind == "essay"
    assert cand.arxiv_id is None
    assert cand.doi is None


def test_citation_missing_url_returns_none() -> None:
    annotation = {"type": "url_citation", "url_citation": {"url": "", "title": "x"}}
    assert candidate_from_citation(annotation, "x", source_name="perplexity") is None


def test_citation_missing_title_returns_none() -> None:
    annotation = {"type": "url_citation", "url_citation": {"url": "https://x", "title": ""}}
    assert candidate_from_citation(annotation, "x", source_name="perplexity") is None


def test_citation_with_malformed_url_citation_returns_none() -> None:
    annotation = {"type": "url_citation", "url_citation": "not a dict"}
    assert candidate_from_citation(annotation, "x", source_name="perplexity") is None


# ---------- protocol conformance ----------


def test_satisfies_discovery_protocol_only() -> None:
    plugin = PerplexityPlugin()
    assert isinstance(plugin, DiscoverySource)
    assert not isinstance(plugin, Resolver)
    assert plugin.kind == "bibliographic"


# ---------- search via mock transport ----------


def _attach_mock_transport(plugin: PerplexityPlugin, handler: MockHandler) -> None:
    transport = httpx.MockTransport(handler)
    plugin._client = httpx.AsyncClient(  # pyright: ignore[reportPrivateUsage]
        transport=transport,
        headers={"Content-Type": "application/json"},
    )


def _mock_response(annotations: list[dict[str, object]]) -> dict[str, object]:
    return {
        "id": "test-id",
        "model": "perplexity/sonar-pro",
        "choices": [
            {
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": "Some prose about the topic with citations.",
                    "annotations": annotations,
                },
                "finish_reason": "stop",
            }
        ],
        "usage": {"prompt_tokens": 11, "completion_tokens": 200},
    }


async def test_search_parses_citations_into_candidates(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    plugin = PerplexityPlugin()

    fixture = _mock_response(
        [
            _annotation("https://arxiv.org/abs/2006.11239", "DDPM"),
            _annotation("https://doi.org/10.1145/3531146.3533088", "FAccT paper"),
            _annotation("https://en.wikipedia.org/wiki/Diffusion_model", "Wikipedia"),
        ]
    )

    def handler(request: httpx.Request) -> httpx.Response:
        assert "openrouter.ai" in str(request.url)
        assert request.headers["authorization"] == "Bearer test-key"
        body = json.loads(request.content)
        assert body["model"] == "perplexity/sonar-pro"
        assert body["messages"][0]["content"] == "best diffusion papers"
        return httpx.Response(200, json=fixture)

    _attach_mock_transport(plugin, handler)

    results = await plugin.search("best diffusion papers")
    assert len(results) == 3
    assert results[0].arxiv_id == "2006.11239"
    assert results[1].doi == "10.1145/3531146.3533088"
    assert results[2].kind == "essay"
    assert all(r.provenance.source_name == "perplexity" for r in results)
    await plugin.close()


async def test_search_skips_non_url_citation_annotations(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """If Perplexity adds new annotation types in the future, ignore them."""
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    plugin = PerplexityPlugin()

    fixture = _mock_response(
        [
            {"type": "image", "image_url": "https://x"},
            _annotation("https://arxiv.org/abs/2006.11239", "DDPM"),
        ]
    )

    def handler(request: httpx.Request) -> httpx.Response:
        del request
        return httpx.Response(200, json=fixture)

    _attach_mock_transport(plugin, handler)

    results = await plugin.search("x")
    assert len(results) == 1
    assert results[0].arxiv_id == "2006.11239"
    await plugin.close()


async def test_search_truncates_to_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    plugin = PerplexityPlugin()

    fixture = _mock_response(
        [_annotation(f"https://arxiv.org/abs/2001.{i:05d}", f"Paper {i}") for i in range(20)]
    )

    def handler(request: httpx.Request) -> httpx.Response:
        del request
        return httpx.Response(200, json=fixture)

    _attach_mock_transport(plugin, handler)

    results = await plugin.search("x", limit=5)
    assert len(results) == 5
    await plugin.close()


async def test_search_returns_empty_list_when_no_choices(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    plugin = PerplexityPlugin()

    def handler(request: httpx.Request) -> httpx.Response:
        del request
        return httpx.Response(200, json={"choices": []})

    _attach_mock_transport(plugin, handler)
    results = await plugin.search("x")
    assert results == []
    await plugin.close()


async def test_search_translates_http_error_to_source_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    plugin = PerplexityPlugin()

    def handler(request: httpx.Request) -> httpx.Response:
        del request
        return httpx.Response(503)

    _attach_mock_transport(plugin, handler)
    with pytest.raises(SourceUnavailable, match="perplexity:"):
        await plugin.search("x")
    await plugin.close()


async def test_search_raises_when_api_key_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    plugin = PerplexityPlugin()
    with pytest.raises(SourceUnavailable, match="OPENROUTER_API_KEY"):
        await plugin.search("anything")


# ---------- live test ----------


@pytest.mark.live
async def test_live_search_returns_real_citations() -> None:
    """End-to-end against real Perplexity via OpenRouter."""
    plugin = PerplexityPlugin()
    await plugin.start()
    try:
        results = await plugin.search(
            "What are the most important academic papers on denoising diffusion models?"
        )
        assert len(results) >= 3
        assert all(c.title for c in results)
        # We expect at least one arxiv hit for a query like this
        assert any(c.arxiv_id for c in results)
    finally:
        await plugin.close()
