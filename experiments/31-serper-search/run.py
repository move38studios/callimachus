# /// script
# requires-python = ">=3.11"
# dependencies = [
#   "httpx>=0.27",
#   "rich>=13",
# ]
# ///
"""Probe Serper /search and /scholar.

Dumps the response shape so we know what to map into WorkCandidate when
we build the bundled Serper plugin in M2.0a.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from _common import load_env_into_os, require_env, setup_logging  # noqa: E402

log = setup_logging(verbose=False)
load_env_into_os()
SERPER_API_KEY = require_env("SERPER_API_KEY", log)

OUT_DIR = Path(__file__).parent / "output"
OUT_DIR.mkdir(exist_ok=True)


def serper_call(endpoint: str, query: str, *, num: int = 5) -> dict:  # type: ignore[type-arg]
    """One call to https://google.serper.dev/<endpoint>."""
    url = f"https://google.serper.dev/{endpoint}"
    response = httpx.post(
        url,
        headers={"X-API-KEY": SERPER_API_KEY, "Content-Type": "application/json"},
        json={"q": query, "num": num},
        timeout=30,
    )
    response.raise_for_status()
    return response.json()


def main() -> int:
    query = " ".join(sys.argv[1:]) or "diffusion models for image generation"
    log.info("[bold cyan]query:[/] %s", query)

    for endpoint in ("search", "scholar"):
        log.info("[bold]── /%s ──[/]", endpoint)
        try:
            data = serper_call(endpoint, query, num=5)
        except httpx.HTTPError as exc:
            log.error("[red]/%s failed:[/] %s", endpoint, exc)
            continue

        # Save the raw response for inspection
        out_path = OUT_DIR / f"{endpoint}_response.json"
        out_path.write_text(json.dumps(data, indent=2))
        log.info("[dim]raw response → %s[/]", out_path)

        # Top-level keys
        log.info("[bold]top-level fields:[/] %s", sorted(data.keys()))

        # Result-list field varies by endpoint
        for list_key in ("organic", "scholar", "results"):
            if list_key in data and isinstance(data[list_key], list):
                results = data[list_key]
                log.info("[bold]%d %s results[/], per-result keys: %s",
                         len(results), list_key,
                         sorted(results[0].keys()) if results else "(none)")
                for i, r in enumerate(results[:3], start=1):
                    log.info(
                        "[blue]#%d[/] [bold]%s[/]\n     %s\n     [dim]%s[/]",
                        i,
                        r.get("title", "(no title)"),
                        r.get("link", "(no link)"),
                        (r.get("snippet") or "")[:160],
                    )
                break

        # Surface extra blocks if present (knowledge graph, answer box, related)
        for extra in ("knowledgeGraph", "answerBox", "peopleAlsoAsk", "relatedSearches"):
            if extra in data:
                log.info("[magenta]extra block:[/] %s present", extra)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
