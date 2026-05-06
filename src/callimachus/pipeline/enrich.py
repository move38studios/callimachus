"""Enrich stage — single LLM call: markdown → structured metadata.

Reads `paper.md`, asks the LLM for an `Enrichment` (title, authors, year,
summary, key claims, methods, datasets, keywords), then writes:

    works/<id>/metadata.yaml   — full enrichment as YAML
    works/<id>/summary.md      — just the summary text
    works/<id>/paper.md        — same content but with YAML frontmatter prepended

The frontmatter is the standard Jekyll/Obsidian/etc. format (`---\\n...---`)
so paper.md renders cleanly in any markdown viewer. Re-running enrichment
strips and replaces the existing frontmatter rather than stacking copies.

Pydantic AI is the default backend, but `enrich_to_files` only needs an
`EnrichFn = Callable[[str], Awaitable[Enrichment]]`. Tests pass a stub;
production wires `make_default_enricher()` which builds a Pydantic AI
agent under the hood.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from pathlib import Path

import yaml
from pydantic import BaseModel, Field

from callimachus.llm import MODEL_SMART
from callimachus.pipeline.paths import markdown_path, work_dir

log = logging.getLogger(__name__)

# Cap input size to leave headroom inside Sonnet 4.6's 200k context.
# Real chunking comes when we hit a doc that needs it.
MAX_INPUT_CHARS = 400_000


class Enrichment(BaseModel):
    """Structured metadata extracted from a work's markdown by the LLM."""

    title: str = Field(description="The work's exact title.")
    authors: list[str] = Field(
        default_factory=lambda: [],
        description="Full author names in the order shown. No initials, no affiliations.",
    )
    year: int | None = Field(
        default=None,
        description="4-digit publication year if discoverable, else null.",
    )
    venue: str | None = Field(
        default=None,
        description="Journal, conference, or publisher name if present, else null.",
    )
    summary: str = Field(
        description=(
            "2-3 sentences capturing the central thesis and contribution. "
            "Don't hedge — state what the work claims, not what it 'discusses'."
        ),
        min_length=20,
    )
    key_claims: list[str] = Field(
        default_factory=lambda: [],
        description="3-5 specific claims or contributions, each one a complete sentence.",
    )
    methods: list[str] = Field(
        default_factory=lambda: [],
        description=(
            "Research methods or techniques used "
            "(e.g. 'denoising score matching', 'ablation study')."
        ),
    )
    datasets: list[str] = Field(
        default_factory=lambda: [],
        description="Named datasets referenced (e.g. 'ImageNet', 'CIFAR-10'). Empty if none.",
    )
    keywords: list[str] = Field(
        default_factory=lambda: [],
        description=(
            "5-10 lowercase topical keywords for retrieval. Prefer multi-word concepts "
            "that capture the work's specific contribution over generic ones."
        ),
    )


EnrichFn = Callable[[str], Awaitable[Enrichment]]


ENRICHMENT_SYSTEM_PROMPT = """\
You are extracting structured metadata from a research paper, essay, or report.

You will receive the markdown text of the work. Read it carefully and produce
a structured Enrichment.

Rules:
- Be precise. Don't invent details that aren't in the text.
- If a field can't be determined from the text, leave it empty/null per its type.
- Don't hedge in summaries — state what the paper claims, not what it "discusses",
  "addresses", or "explores".
- Authors: full names (e.g. "Jonathan Ho"), not initials. Strip affiliations.
- Keywords: lowercase, prefer multi-word concepts that capture the work's specific
  contribution (e.g. "diffusion probabilistic models", "score matching") over
  generic ones (e.g. "machine learning").
"""


# ---------- frontmatter helpers ----------


def render_yaml_frontmatter(enrichment: Enrichment) -> str:
    """Render an Enrichment as a Jekyll/Obsidian-style YAML frontmatter block."""
    data = enrichment.model_dump(mode="json", exclude_none=False)
    yaml_text = yaml.safe_dump(
        data,
        sort_keys=False,
        allow_unicode=True,
        default_flow_style=False,
        width=100,
    )
    return f"---\n{yaml_text}---\n\n"


def strip_frontmatter(markdown_text: str) -> str:
    """Remove a leading `---\\n...\\n---\\n` block from markdown if present."""
    if not markdown_text.lstrip().startswith("---"):
        return markdown_text
    # Find the closing fence — the second `---` on its own line
    lines = markdown_text.splitlines(keepends=True)
    # Skip leading whitespace lines
    start = 0
    while start < len(lines) and not lines[start].strip():
        start += 1
    if start >= len(lines) or lines[start].rstrip() != "---":
        return markdown_text
    # Find the closing ---
    for i in range(start + 1, len(lines)):
        if lines[i].rstrip() == "---":
            # Strip everything through line i, plus any blank lines after
            rest = "".join(lines[i + 1 :])
            return rest.lstrip("\n")
    # No closing fence found — leave as-is
    return markdown_text


def prepend_frontmatter(markdown_text: str, enrichment: Enrichment) -> str:
    """Write a fresh frontmatter at the head of `markdown_text`.

    Idempotent: if `markdown_text` already has a frontmatter block, it's
    replaced with the new one rather than stacking.
    """
    body = strip_frontmatter(markdown_text)
    return render_yaml_frontmatter(enrichment) + body


# ---------- the stage ----------


async def enrich_to_files(
    library_root: Path,
    work_id: str,
    *,
    enrich_fn: EnrichFn,
) -> Enrichment:
    """Read paper.md, enrich, write metadata.yaml + summary.md, update paper.md.

    Returns the produced Enrichment. Not idempotent in the strict sense:
    re-running re-calls the LLM and overwrites the outputs. (Per-paper
    checkpointing at the orchestrator level decides whether to re-run.)
    """
    md_path = markdown_path(library_root, work_id)
    if not md_path.is_file():
        msg = f"enrich: paper.md not found at {md_path}; run extract first"
        raise FileNotFoundError(msg)

    text = md_path.read_text()
    if not text.strip():
        msg = f"enrich: paper.md at {md_path} is empty"
        raise ValueError(msg)

    if len(text) > MAX_INPUT_CHARS:
        log.warning(
            "enrich: truncating %d-char input to %d chars (real chunking is M2+)",
            len(text),
            MAX_INPUT_CHARS,
        )
        text = text[:MAX_INPUT_CHARS]

    enrichment = await enrich_fn(text)

    out_dir = work_dir(library_root, work_id)
    metadata_yaml_path = out_dir / "metadata.yaml"
    summary_md_path = out_dir / "summary.md"

    metadata_yaml_path.write_text(
        yaml.safe_dump(
            enrichment.model_dump(mode="json", exclude_none=False),
            sort_keys=False,
            allow_unicode=True,
            default_flow_style=False,
            width=100,
        )
    )
    summary_md_path.write_text(enrichment.summary.strip() + "\n")
    md_path.write_text(prepend_frontmatter(text, enrichment))

    log.debug(
        "enrich_to_files: wrote metadata.yaml + summary.md and prepended frontmatter for %s",
        work_id,
    )
    return enrichment


# ---------- default Pydantic AI enricher ----------


def make_default_enricher(model: str = MODEL_SMART) -> EnrichFn:
    """Build the default Pydantic AI-backed enricher.

    Lazy-imports `pydantic_ai` so callers using a custom `enrich_fn` (e.g.
    tests with a stub) don't pay the import cost.
    """
    from pydantic_ai import Agent

    agent: Agent[None, Enrichment] = Agent(
        model,
        output_type=Enrichment,
        system_prompt=ENRICHMENT_SYSTEM_PROMPT,
    )

    async def _enrich(markdown_text: str) -> Enrichment:
        result = await agent.run(markdown_text)
        return result.output

    return _enrich
