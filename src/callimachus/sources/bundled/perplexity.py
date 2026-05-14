"""perplexity — bundled `DiscoverySource` backed by Perplexity (via OpenRouter).

Perplexity is a Google-like search-and-synthesize engine. We use it
specifically for the natural-language query mode: ask it 'what are the
most important papers on X', get back a mix of academic + grey-lit
citations curated by the underlying LLM.

Per experiment 32 LEARNINGS:
- Citations come back as `choices[0].message.annotations[*].url_citation`
  with `(url, title)` only (no snippet). We use direct httpx (not Pydantic
  AI) to get access to the raw annotations array.
- Auth is `OPENROUTER_API_KEY` — we route Perplexity through OpenRouter
  for parity with our other LLM calls. No separate PERPLEXITY_API_KEY.
- URLs that look like arxiv get arxiv_id populated; URLs that look like
  doi.org get doi populated; everything else passes through as URL-only.

Year and kind filters are accepted but not passed through — Perplexity
doesn't expose them via the OpenRouter chat-completions interface. The
agent should bake those into the natural-language query when needed
(e.g. "seminal pre-2018 work on X").
"""

from __future__ import annotations

import logging
import os
import re
from typing import Any, cast

import httpx

from callimachus.sources.bundled.arxiv import extract_arxiv_id
from callimachus.sources.protocols import (
    Provenance,
    SourceKind,
    SourceUnavailable,
    WorkCandidate,
    WorkKind,
)

log = logging.getLogger(__name__)

OPENROUTER_API_URL = "https://openrouter.ai/api/v1/chat/completions"
DEFAULT_MODEL = "perplexity/sonar-pro"

# Strip the URL prefix off doi.org URLs ("https://doi.org/10.x" → "10.x").
_DOI_URL_RE = re.compile(r"https?://(?:dx\.)?doi\.org/(.+?)(?:[?#].*)?$", re.IGNORECASE)


def extract_doi(url: str) -> str | None:
    """Pull a bare DOI out of a doi.org URL. Returns None if not a doi.org URL."""
    if not url:
        return None
    match = _DOI_URL_RE.match(url.strip())
    if match:
        return match.group(1)
    return None


def candidate_from_citation(
    citation: dict[str, Any], query: str, *, source_name: str
) -> WorkCandidate | None:
    """Map one Perplexity url_citation annotation -> WorkCandidate.

    Returns None for malformed entries (no URL or no title).
    """
    raw: object = citation.get("url_citation")
    if not isinstance(raw, dict):
        return None
    url_citation = cast("dict[str, Any]", raw)

    url_raw = url_citation.get("url")
    title_raw = url_citation.get("title")
    url = str(url_raw).strip() if url_raw else ""
    title = str(title_raw).strip() if title_raw else ""
    if not url or not title:
        return None

    arxiv_id = extract_arxiv_id(url)
    doi = None if arxiv_id else extract_doi(url)

    # Web sources (blogs, Wikipedia) don't carry the academic kind even though
    # the source is technically bibliographic at the plugin level. Tag them as
    # "essay" if we can't pin them to an arxiv_id or doi.
    kind: WorkKind = "paper" if (arxiv_id or doi) else "essay"

    return WorkCandidate(
        title=title,
        source_url=url,
        provenance=Provenance(source_name=source_name, query=query),
        arxiv_id=arxiv_id,
        doi=doi,
        kind=kind,
    )


class PerplexityPlugin:
    """`DiscoverySource` that runs natural-language queries against Perplexity."""

    name: str = "perplexity"
    kind: SourceKind = "bibliographic"
    enabled: bool = True

    def __init__(
        self,
        *,
        model: str = DEFAULT_MODEL,
        http_timeout: float = 60.0,
    ) -> None:
        self._model = model
        self._http_timeout = http_timeout
        self._client: httpx.AsyncClient | None = None

    async def start(self) -> None:
        if self._client is None:
            self._client = self._make_client()

    async def close(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    def _make_client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            timeout=self._http_timeout,
            headers={"Content-Type": "application/json"},
        )

    def _client_or_init(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = self._make_client()
        return self._client

    @staticmethod
    def _api_key() -> str:
        key = os.environ.get("OPENROUTER_API_KEY", "").strip()
        if not key:
            raise SourceUnavailable("perplexity: OPENROUTER_API_KEY not set in environment")
        return key

    async def search(
        self,
        query: str,
        *,
        limit: int = 50,
        year_from: int | None = None,
        year_to: int | None = None,
        kinds: list[WorkKind] | None = None,
    ) -> list[WorkCandidate]:
        # Perplexity through OpenRouter doesn't expose year / kind filters.
        # The hunter agent should bake date hints into the query string when
        # needed ("seminal pre-2018 work on X" / "recent advances in Y").
        del year_from, year_to, kinds

        api_key = self._api_key()
        body: dict[str, Any] = {
            "model": self._model,
            "messages": [{"role": "user", "content": query}],
        }

        try:
            client = self._client_or_init()
            response = await client.post(
                OPENROUTER_API_URL,
                json=body,
                headers={"Authorization": f"Bearer {api_key}"},
            )
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise SourceUnavailable(f"perplexity: {type(exc).__name__}: {exc}") from exc

        data = cast("dict[str, Any]", response.json())
        choices = cast("list[dict[str, Any]]", data.get("choices") or [])
        if not choices:
            return []

        message = cast("dict[str, Any]", choices[0].get("message") or {})
        annotations = cast("list[dict[str, Any]]", message.get("annotations") or [])

        candidates: list[WorkCandidate] = []
        for annotation in annotations:
            if annotation.get("type") != "url_citation":
                continue
            try:
                cand = candidate_from_citation(annotation, query, source_name=self.name)
            except Exception as exc:
                log.debug("%s: skipping bad citation (%s): %s", self.name, type(exc).__name__, exc)
                continue
            if cand is not None:
                candidates.append(cand)

        # `limit` is a soft cap — Perplexity decides how many to return; we
        # truncate. Typical responses are 5-15 citations.
        if len(candidates) > limit:
            candidates = candidates[:limit]
        return candidates
