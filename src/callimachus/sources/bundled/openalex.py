"""openalex — bundled DiscoverySource for OpenAlex.org.

OpenAlex is a free, comprehensive bibliographic database (~250M works)
with a citation graph and structured metadata. No auth needed; sending
`mailto=` puts us in the "polite pool" with better service. We act on
that and read the email from `OPENALEX_MAILTO` env var (optional).

This plugin is DiscoverySource only — no resolver. We route to existing
resolvers via matched arxiv_id (when an OpenAlex result is an arxiv
paper, the DOI is `10.48550/arxiv.{id}`).

Abstracts come back as an "inverted index" (`{word: [positions]}`) which
we reconstruct to plain text.
"""

from __future__ import annotations

import logging
import os
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

OPENALEX_API_URL = "https://api.openalex.org/works"

# Polite-pool identifier — falls back to a generic mailto if the env var
# isn't set. OpenAlex is free either way; this just gets us better
# service and is the project-wide accepted etiquette.
DEFAULT_MAILTO = "callimachus@move38studios.dev"

# Strip the URL prefix off DOIs OpenAlex returns ("https://doi.org/10.x" → "10.x").
_DOI_URL_PREFIX = "https://doi.org/"

# arxiv DOIs come back as 10.48550/arxiv.{id}. Pull out the {id}.
_ARXIV_DOI_PREFIX = "10.48550/arxiv."


def _get(obj: Any, *keys: str) -> Any:
    """Walk a JSON-decoded dict via a series of keys, returning None on any miss.

    Returns `Any` deliberately so pyright doesn't try to drill into untyped
    JSON values. Callers annotate at the leaf when they care.
    """
    cur: Any = obj
    for k in keys:
        if not isinstance(cur, dict):
            return None
        cur = cast("dict[str, Any]", cur).get(k)
        if cur is None:
            return None
    return cur


def reconstruct_abstract(inverted: dict[str, list[int]] | None) -> str | None:
    """Turn an OpenAlex `abstract_inverted_index` back into plain text."""
    if not inverted:
        return None
    positions = [p for poses in inverted.values() for p in poses]
    if not positions:
        return None
    max_pos = max(positions)
    words: list[str] = [""] * (max_pos + 1)
    for word, poses in inverted.items():
        for pos in poses:
            if 0 <= pos <= max_pos:
                words[pos] = word
    text = " ".join(w for w in words if w)
    return text or None


def normalize_doi(doi_url: str | None) -> str | None:
    """`https://doi.org/10.x/y` → `10.x/y`. Returns None if not a DOI URL."""
    if not doi_url:
        return None
    lower = doi_url.lower()
    if lower.startswith(_DOI_URL_PREFIX):
        return doi_url[len(_DOI_URL_PREFIX) :]
    return doi_url  # already a bare DOI


def arxiv_id_from_openalex_record(record: dict[str, Any]) -> str | None:
    """Detect arxiv_id from a record's DOI or best-OA landing URL."""
    doi = normalize_doi(_get(record, "doi"))
    if doi and doi.lower().startswith(_ARXIV_DOI_PREFIX):
        return doi[len(_ARXIV_DOI_PREFIX) :]
    landing: str | None = _get(record, "best_oa_location", "landing_page_url")
    pdf: str | None = _get(record, "best_oa_location", "pdf_url")
    for url in (landing, pdf):
        arxiv_id = extract_arxiv_id(url)
        if arxiv_id:
            return arxiv_id
    return None


def candidate_from_openalex_record(record: dict[str, Any], query: str) -> WorkCandidate | None:
    """Map one OpenAlex record → WorkCandidate. Returns None on bad records."""
    title_raw: str | None = _get(record, "title")
    title = (title_raw or "").strip()
    if not title:
        return None

    doi = normalize_doi(_get(record, "doi"))
    arxiv_id = arxiv_id_from_openalex_record(record)

    authors: list[str] = []
    authorships = cast("list[dict[str, Any]]", _get(record, "authorships") or [])
    for a in authorships:
        name: str | None = _get(a, "author", "display_name")
        if name:
            authors.append(name.strip())

    venue: str | None = _get(record, "primary_location", "source", "display_name")
    landing: str | None = _get(record, "best_oa_location", "landing_page_url")
    pdf_url: str | None = _get(record, "best_oa_location", "pdf_url")
    openalex_id: str | None = _get(record, "ids", "openalex")

    # Prefer landing page, then arxiv abstract URL, then DOI URL, then OpenAlex page
    source_url = (
        landing
        or (f"https://arxiv.org/abs/{arxiv_id}" if arxiv_id else None)
        or (f"https://doi.org/{doi}" if doi else None)
        or openalex_id
    )
    if not source_url:
        return None

    abstract = reconstruct_abstract(_get(record, "abstract_inverted_index"))
    year: int | None = _get(record, "publication_year")
    cited_by_count: int | None = _get(record, "cited_by_count")

    extras: dict[str, object] = {}
    if cited_by_count is not None:
        extras["cited_by_count"] = cited_by_count
    if openalex_id is not None:
        extras["openalex_id"] = openalex_id

    return WorkCandidate(
        title=title,
        source_url=source_url,
        provenance=Provenance(source_name="openalex", query=query, raw_score=None),
        doi=doi,
        arxiv_id=arxiv_id,
        authors=authors,
        year=year,
        venue=venue,
        abstract=abstract,
        pdf_url=pdf_url,
        kind="paper",
        extras=extras,
    )


class OpenAlexPlugin:
    """DiscoverySource against the OpenAlex /works endpoint."""

    name: str = "openalex"
    kind: SourceKind = "bibliographic"
    enabled: bool = True

    def __init__(
        self,
        *,
        http_timeout: float = 30.0,
        mailto: str | None = None,
    ) -> None:
        self._http_timeout = http_timeout
        self._mailto = mailto or os.environ.get("OPENALEX_MAILTO") or DEFAULT_MAILTO
        self._client: httpx.AsyncClient | None = None

    async def start(self) -> None:
        if self._client is None:
            self._client = httpx.AsyncClient(
                timeout=self._http_timeout,
                headers={
                    "User-Agent": (
                        f"callimachus/0.1 (mailto:{self._mailto}; "
                        "https://github.com/move38studios/callimachus)"
                    )
                },
                follow_redirects=True,
            )

    async def close(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    def _client_or_init(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                timeout=self._http_timeout,
                headers={"User-Agent": f"callimachus/0.1 (mailto:{self._mailto})"},
                follow_redirects=True,
            )
        return self._client

    async def search(
        self,
        query: str,
        *,
        limit: int = 50,
        year_from: int | None = None,
        year_to: int | None = None,
        kinds: list[WorkKind] | None = None,
    ) -> list[WorkCandidate]:
        del kinds  # OpenAlex /works endpoint only returns scholarly works

        params: dict[str, str | int] = {
            "search": query,
            "per_page": min(limit, 200),  # OpenAlex caps per_page at 200
            "mailto": self._mailto,
        }
        if year_from or year_to:
            f = year_from or 1900
            t = year_to or 2099
            params["filter"] = f"publication_year:{f}-{t}"

        try:
            client = self._client_or_init()
            response = await client.get(OPENALEX_API_URL, params=params)
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise SourceUnavailable(f"openalex: {type(exc).__name__}: {exc}") from exc

        data = cast("dict[str, Any]", response.json())
        results = cast("list[dict[str, Any]]", data.get("results") or [])

        candidates: list[WorkCandidate] = []
        for record in results:
            try:
                cand = candidate_from_openalex_record(record, query)
            except Exception as exc:
                log.debug("openalex: skipping bad record (%s): %s", type(exc).__name__, exc)
                continue
            if cand is not None:
                candidates.append(cand)
        return candidates
