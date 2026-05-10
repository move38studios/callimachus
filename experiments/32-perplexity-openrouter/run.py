# /// script
# requires-python = ">=3.11"
# dependencies = [
#   "httpx>=0.27",
#   "rich>=13",
# ]
# ///
"""Probe perplexity/sonar-pro via OpenRouter — does the `citations` field pass through?

We need to know before building the scout in M2.3 whether we get a
structured URL list back, or have to regex it out of the synthesis text.
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
OPENROUTER_API_KEY = require_env("OPENROUTER_API_KEY", log)

OUT_DIR = Path(__file__).parent / "output"
OUT_DIR.mkdir(exist_ok=True)

DEFAULT_PROMPT = (
    "What are the main angles people approach 'creativity' from in 2026? "
    "Cover cognitive science, computational creativity, AI generative systems, "
    "organisational innovation, and any other major schools of thought. "
    "Be brief — this is reconnaissance, not a thesis."
)


def main() -> int:
    prompt = " ".join(sys.argv[1:]) or DEFAULT_PROMPT
    log.info("[bold cyan]prompt:[/] %s", prompt)

    response = httpx.post(
        "https://openrouter.ai/api/v1/chat/completions",
        headers={
            "Authorization": f"Bearer {OPENROUTER_API_KEY}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://github.com/move38studios/callimachus",
            "X-Title": "Callimachus experiment 32",
        },
        json={
            "model": "perplexity/sonar-pro",
            "messages": [{"role": "user", "content": prompt}],
            # Optional perplexity-specific knobs that *may* tunnel through:
            "return_citations": True,
            "return_related_questions": True,
        },
        timeout=120,  # sonar can take a while
    )
    response.raise_for_status()
    data = response.json()

    out_path = OUT_DIR / "perplexity_response.json"
    out_path.write_text(json.dumps(data, indent=2))
    log.info("[dim]raw response → %s[/]", out_path)

    log.info("[bold]top-level fields:[/] %s", sorted(data.keys()))

    # Synthesis text
    try:
        text = data["choices"][0]["message"]["content"]
        log.info("[bold]synthesis (%d chars):[/]\n%s", len(text), text[:600] + ("…" if len(text) > 600 else ""))
    except (KeyError, IndexError) as exc:
        log.error("[red]no message content:[/] %s", exc)

    # OpenRouter wraps perplexity's citations in OpenAI-compat
    # `message.annotations[*].url_citation` rather than the flat
    # top-level `citations` field perplexity-direct returns.
    msg = data.get("choices", [{}])[0].get("message", {})
    annotations = msg.get("annotations", []) or []
    url_cits = [a for a in annotations if a.get("type") == "url_citation"]
    if url_cits:
        log.info(
            "[bold green]✓ %d url_citation annotations[/] (in message.annotations)",
            len(url_cits),
        )
        for i, a in enumerate(url_cits[:7], start=1):
            uc = a.get("url_citation", {})
            log.info(
                "  [blue]%d.[/] [bold]%s[/]\n     %s",
                i,
                uc.get("title", "(no title)"),
                uc.get("url", "(no url)"),
            )
        # Note: `content`/snippet field isn't populated for sonar-pro on OpenRouter
        # as of 2026-05; we get URL + title only.
        if any(a.get("url_citation", {}).get("content") for a in url_cits):
            log.info("[dim]some citations carry snippet content[/]")
        else:
            log.info("[dim]no snippet content on citations (URL + title only)[/]")
    elif "citations" in data:
        # Direct perplexity API shape (in case OpenRouter ever changes)
        log.info("[bold green]✓ flat `citations` (perplexity-direct shape)[/]")
    else:
        log.warning("[yellow]✗ no citations found in any expected field[/]")

    # Token usage
    if "usage" in data:
        u = data["usage"]
        log.info(
            "[bold]usage:[/] in=%s out=%s total=%s",
            u.get("prompt_tokens"),
            u.get("completion_tokens"),
            u.get("total_tokens"),
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
