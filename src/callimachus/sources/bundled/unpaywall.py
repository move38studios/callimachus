"""unpaywall — bundled `Resolver` for DOIs that have an open-access PDF.

Unpaywall (https://unpaywall.org) is a free service that maps DOIs to
their best open-access PDF location, when one exists. No auth required;
sending `email=` puts us in the polite pool with better service.

This plugin is a `Resolver` only — no discovery (Unpaywall doesn't have
a search API; it's strictly lookup-by-DOI). Discovery sources (OpenAlex,
Serper Scholar, Perplexity) supply candidates with DOIs; this plugin
turns them into bytes.

Confidence: 0.7 when `candidate.doi` is set, else 0.0. Lower than the
arxiv resolver (1.0) so arxiv wins when both match — arxiv's LaTeX path
gives cleaner extraction. Higher than 0 so DOI-only candidates get
resolved at all.
"""

from __future__ import annotations

import logging
import os
from typing import Any, cast

import httpx

from callimachus.sources.protocols import (
    ResolvedFile,
    SourceUnavailable,
    WorkCandidate,
)

log = logging.getLogger(__name__)

UNPAYWALL_API_URL = "https://api.unpaywall.org/v2/{doi}"
DEFAULT_EMAIL = "callimachus@move38studios.dev"

# When fetching the actual PDF from a publisher (after Unpaywall told us where
# it lives), some publishers (MDPI, certain Elsevier endpoints) sniff the
# User-Agent and 403 anything that doesn't look like a browser. We send a
# real-looking UA for the PDF fetch only — the Unpaywall API itself
# appreciates the polite-pool mailto UA, so we keep that there.
_BROWSER_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_2_1) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/132.0.0.0 Safari/537.36"
)


def _get(obj: Any, *keys: str) -> Any:
    """Walk a JSON dict via keys, returning None on any miss. (Same helper as openalex.py.)"""
    cur: Any = obj
    for k in keys:
        if not isinstance(cur, dict):
            return None
        cur = cast("dict[str, Any]", cur).get(k)
        if cur is None:
            return None
    return cur


def _pdf_url_from_unpaywall_record(record: dict[str, Any]) -> str | None:
    """Return the best available PDF URL from an Unpaywall response, or None."""
    if not record.get("is_oa"):
        return None
    # Prefer best_oa_location.url_for_pdf, then any other oa_locations[].url_for_pdf
    best_pdf = _get(record, "best_oa_location", "url_for_pdf")
    if best_pdf:
        return str(best_pdf)
    locations = cast("list[dict[str, Any]]", record.get("oa_locations") or [])
    for loc in locations:
        url = _get(loc, "url_for_pdf")
        if url:
            return str(url)
    return None


class UnpaywallPlugin:
    """`Resolver` that fetches open-access PDFs for DOI candidates."""

    name: str = "unpaywall"
    enabled: bool = True

    def __init__(
        self,
        *,
        http_timeout: float = 30.0,
        email: str | None = None,
    ) -> None:
        self._http_timeout = http_timeout
        self._email = email or os.environ.get("UNPAYWALL_EMAIL") or DEFAULT_EMAIL
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
            headers={
                "User-Agent": (
                    f"callimachus/0.1 (mailto:{self._email}; "
                    "https://github.com/move38studios/callimachus)"
                )
            },
            follow_redirects=True,
        )

    def _client_or_init(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = self._make_client()
        return self._client

    # ----- Resolver -----

    async def confidence(self, candidate: WorkCandidate) -> float:
        return 0.7 if candidate.doi else 0.0

    async def resolve(self, candidate: WorkCandidate) -> ResolvedFile:
        if not candidate.doi:
            raise SourceUnavailable(f"unpaywall: no DOI on {candidate.candidate_id}")

        url = UNPAYWALL_API_URL.format(doi=candidate.doi)
        client = self._client_or_init()

        try:
            response = await client.get(url, params={"email": self._email})
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 404:
                raise SourceUnavailable(
                    f"unpaywall: DOI {candidate.doi!r} not in Unpaywall database"
                ) from exc
            raise SourceUnavailable(
                f"unpaywall: HTTP {exc.response.status_code} for DOI {candidate.doi!r}"
            ) from exc
        except httpx.HTTPError as exc:
            raise SourceUnavailable(f"unpaywall: {type(exc).__name__}: {exc}") from exc

        record = cast("dict[str, Any]", response.json())
        pdf_url = _pdf_url_from_unpaywall_record(record)
        if not pdf_url:
            raise SourceUnavailable(
                f"unpaywall: no open-access PDF available for DOI {candidate.doi!r}"
            )

        # Fetch the actual PDF — use a browser-like User-Agent + Accept since
        # some publishers (MDPI, certain Elsevier paths) 403 the polite-pool UA.
        try:
            pdf_response = await client.get(
                pdf_url,
                headers={
                    "User-Agent": _BROWSER_UA,
                    "Accept": "application/pdf,*/*;q=0.8",
                },
            )
            pdf_response.raise_for_status()
        except httpx.HTTPError as exc:
            raise SourceUnavailable(f"unpaywall: PDF fetch failed for {pdf_url!r}: {exc}") from exc

        if not pdf_response.content:
            raise SourceUnavailable(
                f"unpaywall: empty PDF body for DOI {candidate.doi!r} ({pdf_url!r})"
            )

        # Some hosts return HTML when they meant to return a PDF (login walls,
        # 200-but-rejected). Sniff the content type and fail loud.
        content_type = pdf_response.headers.get("content-type", "").lower()
        if "pdf" not in content_type and not pdf_response.content.startswith(b"%PDF"):
            raise SourceUnavailable(
                f"unpaywall: response from {pdf_url!r} is not a PDF "
                f"(content-type={content_type!r})"
            )

        return ResolvedFile(
            candidate_id=candidate.candidate_id,
            bytes_=pdf_response.content,
            content_type="application/pdf",
            source_url=pdf_url,
            resolved_by=self.name,
        )
