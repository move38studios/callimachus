"""arxiv — bundled DiscoverySource + Resolver for arXiv.org papers.

Search hits arXiv's Atom-format query API (free, no auth, ~1 req/3s rate
limit). Resolution prefers LaTeX source (cleanest extraction) and falls
back to PDF.
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
from xml.etree import ElementTree as ET

import httpx

from callimachus.sources.protocols import (
    Provenance,
    ResolvedFile,
    SourceKind,
    SourceUnavailable,
    WorkCandidate,
    WorkKind,
)

log = logging.getLogger(__name__)

ARXIV_API_URL = "https://export.arxiv.org/api/query"
ARXIV_ABS_URL = "https://arxiv.org/abs/{}"
ARXIV_PDF_URL = "https://arxiv.org/pdf/{}.pdf"
ARXIV_SOURCE_URL = "https://arxiv.org/e-print/{}"

# arXiv asks for max 1 request per 3s. Be a good citizen.
ARXIV_RATE_LIMIT_DELAY = 3.0

ATOM_NS = {
    "atom": "http://www.w3.org/2005/Atom",
    "arxiv": "http://arxiv.org/schemas/atom",
}

# Match arXiv IDs in two strict ways:
# - The entire input is a bare ID (with optional `arxiv:` prefix).
# - The input contains an `arxiv.org/{abs,pdf,e-print}/<id>` URL.
#
# Anything else returns None. The previous loose pattern matched
# `[a-z]+/\d+` anywhere in the string, which falsely flagged
# `https://doi.org/10.1145/...` as arxiv id `org/10`.
#
# - new-style: 2006.11239 or 2006.11239v1
# - old-style: math/0001234, hep-th/0001234

_ID_BODY = r"(?:[a-z][a-z\-]+/\d{4,7}|\d{4}\.\d{4,5})"

_ARXIV_BARE_RE = re.compile(
    rf"^(?:arxiv:)?({_ID_BODY})(?:v\d+)?$",
    re.IGNORECASE,
)

_ARXIV_URL_RE = re.compile(
    rf"arxiv\.org/(?:abs|pdf|e-print)/({_ID_BODY})(?:v\d+)?(?:\.pdf)?",
    re.IGNORECASE,
)


def extract_arxiv_id(text: str | None) -> str | None:
    """Extract a canonical arxiv_id (no version suffix) from a URL or raw id.

    Returns None unless the input is unambiguously arxiv: either a bare ID
    (optionally prefixed with `arxiv:`) or a URL with an `arxiv.org/{abs,
    pdf,e-print}/` segment. Generic URLs like `https://doi.org/10.x/y`
    deliberately do NOT match.
    """
    if not text:
        return None
    candidate = text.strip()
    bare = _ARXIV_BARE_RE.match(candidate)
    if bare:
        return bare.group(1)
    url_match = _ARXIV_URL_RE.search(candidate)
    if url_match:
        return url_match.group(1)
    return None


def parse_atom_response(xml_text: str, query: str) -> list[WorkCandidate]:
    """Parse arXiv's Atom query response into WorkCandidates."""
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as exc:
        raise SourceUnavailable(f"arxiv: failed to parse response: {exc}") from exc

    candidates: list[WorkCandidate] = []
    for entry in root.findall("atom:entry", ATOM_NS):
        id_text = (entry.findtext("atom:id", default="", namespaces=ATOM_NS) or "").strip()
        arxiv_id = extract_arxiv_id(id_text)
        if not arxiv_id:
            continue

        title = (entry.findtext("atom:title", default="", namespaces=ATOM_NS) or "").strip()
        abstract_raw = entry.findtext("atom:summary", default="", namespaces=ATOM_NS) or ""
        abstract = " ".join(abstract_raw.split()) or None

        authors: list[str] = []
        for author_elem in entry.findall("atom:author", ATOM_NS):
            name = (author_elem.findtext("atom:name", default="", namespaces=ATOM_NS) or "").strip()
            if name:
                authors.append(name)

        published = (entry.findtext("atom:published", default="", namespaces=ATOM_NS) or "").strip()
        year: int | None = None
        if len(published) >= 4 and published[:4].isdigit():
            year = int(published[:4])

        # PDF link is the one with title="pdf"
        pdf_url: str | None = None
        for link_elem in entry.findall("atom:link", ATOM_NS):
            if link_elem.attrib.get("title") == "pdf":
                pdf_url = link_elem.attrib.get("href")
                break

        candidates.append(
            WorkCandidate(
                title=" ".join(title.split()),
                source_url=ARXIV_ABS_URL.format(arxiv_id),
                provenance=Provenance(source_name="arxiv", query=query),
                arxiv_id=arxiv_id,
                authors=authors,
                year=year,
                abstract=abstract,
                pdf_url=pdf_url,
                kind="paper",
            )
        )

    return candidates


class ArxivPlugin:
    """DiscoverySource + Resolver against arXiv's public API."""

    name: str = "arxiv"
    kind: SourceKind = "preprint"
    enabled: bool = True

    def __init__(self, *, http_timeout: float = 30.0) -> None:
        self._http_timeout = http_timeout
        self._client: httpx.AsyncClient | None = None
        self._last_request_at: float = 0.0
        self._rate_limit_lock = asyncio.Lock()

    async def start(self) -> None:
        if self._client is None:
            self._client = httpx.AsyncClient(
                timeout=self._http_timeout,
                headers={
                    "User-Agent": ("callimachus/0.1 (https://github.com/move38studios/callimachus)")
                },
                follow_redirects=True,
            )

    async def close(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    def _client_or_init(self) -> httpx.AsyncClient:
        """Lazy fallback for callers that didn't call start() (e.g. tests)."""
        if self._client is None:
            self._client = httpx.AsyncClient(
                timeout=self._http_timeout,
                headers={"User-Agent": "callimachus/0.1"},
                follow_redirects=True,
            )
        return self._client

    async def _wait_for_rate_limit(self) -> None:
        async with self._rate_limit_lock:
            elapsed = time.monotonic() - self._last_request_at
            wait = ARXIV_RATE_LIMIT_DELAY - elapsed
            if wait > 0:
                await asyncio.sleep(wait)
            self._last_request_at = time.monotonic()

    # ---------- DiscoverySource ----------

    async def search(
        self,
        query: str,
        *,
        limit: int = 50,
        year_from: int | None = None,
        year_to: int | None = None,
        kinds: list[WorkKind] | None = None,
    ) -> list[WorkCandidate]:
        del kinds  # arXiv is preprints only; assume "paper"

        search_q = f"all:{query}" if query else "all:*"

        if year_from or year_to:
            yfrom = f"{year_from}01010000" if year_from else "190001010000"
            yto = f"{year_to}12312359" if year_to else "210012312359"
            search_q = f"({search_q}) AND submittedDate:[{yfrom} TO {yto}]"

        params = {
            "search_query": search_q,
            "start": 0,
            "max_results": limit,
        }

        try:
            await self._wait_for_rate_limit()
            client = self._client_or_init()
            response = await client.get(ARXIV_API_URL, params=params)
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise SourceUnavailable(f"arxiv: {type(exc).__name__}: {exc}") from exc

        return parse_atom_response(response.text, query)

    # ---------- Resolver ----------

    async def confidence(self, candidate: WorkCandidate) -> float:
        if candidate.arxiv_id:
            return 1.0
        url = candidate.source_url
        if url and ("arxiv.org/abs/" in url or "arxiv.org/pdf/" in url) and extract_arxiv_id(url):
            return 1.0
        return 0.0

    async def resolve(self, candidate: WorkCandidate) -> ResolvedFile:
        arxiv_id = candidate.arxiv_id or extract_arxiv_id(candidate.source_url)
        if not arxiv_id:
            raise SourceUnavailable(f"arxiv: no arxiv_id for {candidate.candidate_id}")

        client = self._client_or_init()

        # Prefer LaTeX source (cleanest extraction path)
        try:
            await self._wait_for_rate_limit()
            url = ARXIV_SOURCE_URL.format(arxiv_id)
            response = await client.get(url)
            if response.status_code == 200 and response.content:
                return ResolvedFile(
                    candidate_id=candidate.candidate_id,
                    bytes_=response.content,
                    content_type=response.headers.get("content-type", "application/x-tar"),
                    source_url=url,
                    resolved_by=self.name,
                )
            log.debug(
                "arxiv: LaTeX source not available for %s (status=%d)",
                arxiv_id,
                response.status_code,
            )
        except httpx.HTTPError as exc:
            log.debug("arxiv: LaTeX source fetch failed for %s: %s", arxiv_id, exc)

        # Fall back to PDF
        try:
            await self._wait_for_rate_limit()
            url = ARXIV_PDF_URL.format(arxiv_id)
            response = await client.get(url)
            response.raise_for_status()
            return ResolvedFile(
                candidate_id=candidate.candidate_id,
                bytes_=response.content,
                content_type="application/pdf",
                source_url=url,
                resolved_by=self.name,
            )
        except httpx.HTTPError as exc:
            raise SourceUnavailable(f"arxiv: PDF fetch failed for {arxiv_id}: {exc}") from exc
