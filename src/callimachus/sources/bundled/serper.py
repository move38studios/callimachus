"""serper — bundled DiscoverySources for Google Search and Google Scholar.

Serper (https://serper.dev) is a paid Google Search API. We use it for two
complementary jobs in M2:

- **serper_scholar** — Google Scholar results. Per-result fields map
  cleanly to `WorkCandidate` (title, link, snippet, year, pdfUrl, citedBy,
  publicationInfo). The hunter agent's go-to source for academic discovery
  beyond arXiv and OpenAlex.
- **serper_web** — general Google web results. Useful for grey literature,
  blog posts, and the "peopleAlsoAsk" / "relatedSearches" signals the
  scout agent uses for angle expansion in M2.3.

Both are bundled here because they share auth, transport, and most of the
response-shape conventions — separating them into two files would be
duplication. The two registered plugins are thin subclasses that differ
only by `mode`, `name`, and `kind`.

Auth: `X-API-KEY` header from `SERPER_API_KEY`. Read lazily at first
`search()` call so the registry can load this plugin even when the key
is absent (we just raise `SourceUnavailable` at call time instead).
"""

from __future__ import annotations

import logging
import os
import re
from typing import Any, Literal, cast

import httpx

from callimachus.sources.protocols import (
    Provenance,
    SourceKind,
    SourceUnavailable,
    WorkCandidate,
    WorkKind,
)

log = logging.getLogger(__name__)

SERPER_BASE_URL = "https://google.serper.dev"

# Match a 4-digit year anywhere in a string ("Jun 22, 2023" → 2023).
_YEAR_RE = re.compile(r"\b(19|20)\d{2}\b")


def parse_year_from_date(date_str: str | None) -> int | None:
    """Pull a 4-digit year out of a Serper /search `date` field, if present."""
    if not date_str:
        return None
    match = _YEAR_RE.search(date_str)
    return int(match.group()) if match else None


def parse_publication_info(info: str | None) -> tuple[list[str], str | None]:
    """Split a Scholar `publicationInfo` string into (authors, venue).

    Format is typically:
        "J Ho, A Jain, P Abbeel - Advances in neural information…, 2020 - openaccess.thecvf.com"

    We split on " - ". The first segment is comma-separated author names.
    The second segment (when present) is the venue/year string. Trailing
    segments (e.g. host domain) are ignored.
    """
    if not info:
        return [], None
    parts = [p.strip() for p in info.split(" - ")]
    authors_raw = parts[0]
    authors = [a.strip() for a in authors_raw.split(",") if a.strip()]
    venue = parts[1] if len(parts) > 1 else None
    return authors, venue


def scholar_candidate_from_record(
    record: dict[str, Any], query: str, *, source_name: str
) -> WorkCandidate | None:
    """Map one Serper `/scholar` `organic[]` entry → WorkCandidate."""
    title = (record.get("title") or "").strip()
    source_url = (record.get("link") or "").strip()
    if not title or not source_url:
        return None

    snippet = (record.get("snippet") or "").strip() or None
    pdf_url = record.get("pdfUrl") or None
    year = record.get("year")
    cited_by = record.get("citedBy")
    pub_info = record.get("publicationInfo")
    authors, venue = parse_publication_info(pub_info)

    extras: dict[str, object] = {}
    if cited_by is not None:
        extras["cited_by_count"] = cited_by
    if (serper_id := record.get("id")) is not None:
        extras["serper_id"] = serper_id
    if pub_info:
        extras["publication_info"] = pub_info

    return WorkCandidate(
        title=title,
        source_url=source_url,
        provenance=Provenance(source_name=source_name, query=query),
        authors=authors,
        year=year if isinstance(year, int) else None,
        venue=venue,
        abstract=snippet,
        pdf_url=pdf_url,
        kind="paper",
        extras=extras,
    )


def web_candidate_from_record(
    record: dict[str, Any], query: str, *, source_name: str
) -> WorkCandidate | None:
    """Map one Serper `/search` `organic[]` entry → WorkCandidate.

    Web results don't have a kind=paper; we treat them as essays (the
    closest existing WorkKind for blog posts / articles / docs).
    """
    title = (record.get("title") or "").strip()
    source_url = (record.get("link") or "").strip()
    if not title or not source_url:
        return None

    snippet = (record.get("snippet") or "").strip() or None
    year = parse_year_from_date(record.get("date"))

    extras: dict[str, object] = {}
    if (position := record.get("position")) is not None:
        extras["serper_position"] = position
    if (date := record.get("date")) is not None:
        extras["serper_date"] = date

    return WorkCandidate(
        title=title,
        source_url=source_url,
        provenance=Provenance(source_name=source_name, query=query),
        year=year,
        abstract=snippet,
        kind="essay",
        extras=extras,
    )


class _SerperBase:
    """Shared transport + parsing. Subclasses set `mode`, `name`, `kind`."""

    name: str = "serper"
    mode: Literal["search", "scholar"] = "search"
    kind: SourceKind = "web"
    enabled: bool = True

    def __init__(self, *, http_timeout: float = 30.0) -> None:
        self._http_timeout = http_timeout
        self._client: httpx.AsyncClient | None = None

    async def start(self) -> None:
        if self._client is None:
            self._client = httpx.AsyncClient(
                timeout=self._http_timeout,
                headers={"Content-Type": "application/json"},
            )

    async def close(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    def _client_or_init(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                timeout=self._http_timeout,
                headers={"Content-Type": "application/json"},
            )
        return self._client

    @staticmethod
    def _api_key() -> str:
        key = os.environ.get("SERPER_API_KEY", "").strip()
        if not key:
            raise SourceUnavailable("serper: SERPER_API_KEY not set in environment")
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
        del kinds  # serper doesn't filter by WorkKind

        api_key = self._api_key()
        body: dict[str, str | int] = {"q": query, "num": min(limit, 100)}
        if year_from or year_to:
            f = year_from or 1900
            t = year_to or 2099
            # Google's standard custom-date-range filter; Serper passes it through.
            body["tbs"] = f"cdr:1,cd_min:{f},cd_max:{t}"

        url = f"{SERPER_BASE_URL}/{self.mode}"
        try:
            client = self._client_or_init()
            response = await client.post(url, json=body, headers={"X-API-KEY": api_key})
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise SourceUnavailable(f"{self.name}: {type(exc).__name__}: {exc}") from exc

        data = cast("dict[str, Any]", response.json())
        organic = cast("list[dict[str, Any]]", data.get("organic") or [])

        mapper = (
            scholar_candidate_from_record if self.mode == "scholar" else web_candidate_from_record
        )

        candidates: list[WorkCandidate] = []
        for record in organic:
            try:
                cand = mapper(record, query, source_name=self.name)
            except Exception as exc:
                log.debug("%s: skipping bad record (%s): %s", self.name, type(exc).__name__, exc)
                continue
            if cand is not None:
                candidates.append(cand)
        return candidates


class SerperScholarPlugin(_SerperBase):
    """Google Scholar via Serper. Bibliographic — the hunter's workhorse."""

    name: str = "serper_scholar"
    mode: Literal["search", "scholar"] = "scholar"
    kind: SourceKind = "bibliographic"


class SerperWebPlugin(_SerperBase):
    """Google web search via Serper. Grey-lit + scout-angle expansion."""

    name: str = "serper_web"
    mode: Literal["search", "scholar"] = "search"
    kind: SourceKind = "web"
