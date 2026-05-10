# /// script
# requires-python = ">=3.11"
# dependencies = ["httpx>=0.27", "rich>=13"]
# ///
"""Probe the OpenAlex /works endpoint and dump a sample record.

Saves the full JSON response under output/ so we can use it as a fixture
for unit tests without re-hitting the network.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from _common import setup_logging  # noqa: E402

log = setup_logging(verbose=False)

OPENALEX_API_URL = "https://api.openalex.org/works"
MAILTO = "callimachus@move38studios.dev"
OUTPUT = Path(__file__).parent / "output"


def reconstruct_abstract(inverted: dict[str, list[int]] | None) -> str | None:
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
    return " ".join(w for w in words if w) or None


def main(query: str) -> None:
    OUTPUT.mkdir(parents=True, exist_ok=True)

    log.info("openalex: GET /works  search=%r  mailto=%s", query, MAILTO)
    response = httpx.get(
        OPENALEX_API_URL,
        params={"search": query, "per_page": 5, "mailto": MAILTO},
        headers={"User-Agent": f"callimachus-experiment/0.1 (mailto:{MAILTO})"},
        timeout=30.0,
    )
    response.raise_for_status()
    data = response.json()

    out_path = OUTPUT / "openalex_response.json"
    out_path.write_text(json.dumps(data, indent=2))
    log.info("saved full response → %s (%d bytes)", out_path, out_path.stat().st_size)

    results = data.get("results") or []
    log.info("openalex: %d results, meta=%s", len(results), data.get("meta"))

    for i, r in enumerate(results, 1):
        log.info("--- result %d ---", i)
        log.info("title:        %s", r.get("title"))
        log.info("doi:          %s", r.get("doi"))
        log.info("year:         %s", r.get("publication_year"))
        log.info("cited_by:     %s", r.get("cited_by_count"))
        authorships = r.get("authorships") or []
        authors = [
            (a.get("author") or {}).get("display_name")
            for a in authorships
            if (a.get("author") or {}).get("display_name")
        ]
        log.info("authors:      %s", authors[:5])
        prim = (r.get("primary_location") or {}).get("source") or {}
        log.info("venue:        %s", prim.get("display_name"))
        oa = r.get("best_oa_location") or {}
        log.info("landing:      %s", oa.get("landing_page_url"))
        log.info("pdf_url:      %s", oa.get("pdf_url"))
        abstract = reconstruct_abstract(r.get("abstract_inverted_index"))
        if abstract:
            log.info("abstract:     %s%s", abstract[:200], "…" if len(abstract) > 200 else "")
        else:
            log.info("abstract:     (none)")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("usage: run.py '<search query>'", file=sys.stderr)
        sys.exit(2)
    main(sys.argv[1])
