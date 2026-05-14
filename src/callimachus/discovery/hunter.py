"""Hunter — Pydantic AI sub-agent that runs one angle across many sources.

A hunter is spawned per angle by the orchestrator (M2.4). It receives the
topic + angle + a few seed queries, then decides which sources to query
with which keyword variations until it has a useful pool of candidates.

Design (per experiment 06 LEARNINGS):

- One tool per enabled DiscoverySource (`search_<source_name>`), registered
  dynamically. The agent decides which sources to hit and with what queries.
- Tool returns are **compact text** ("arxiv['…'] → 18 hits, 12 new"), not
  serialized candidate JSON — the agent doesn't need full metadata, just
  enough signal to decide whether to keep searching.
- Full WorkCandidate objects accumulate in a deps-scoped seen-dict, keyed
  by `candidate_id` so duplicates across sources collapse automatically.
- `SourceUnavailable` is caught at the tool boundary and re-raised as
  `ModelRetry` so the agent can recover by switching sources.
- Per-hunter `UsageLimits(request_limit=20)` and a `UsageLimitExceeded`
  → `ModelRetry` wrapper at the orchestrator boundary (M2.4 will add that).

The hunter does **no LLM judgment** of candidates — it gathers, dedupes,
and applies a simple deterministic rank (PDF > abstract > year present).
The judge module (M2.1) decides accept/reject downstream.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel, Field
from pydantic_ai import ModelRetry, RunContext

from callimachus.llm import MODEL_FAST
from callimachus.sources.protocols import (
    DiscoverySource,
    SourceUnavailable,
    WorkCandidate,
    WorkKind,
)
from callimachus.sources.registry import SourceRegistry

log = logging.getLogger(__name__)

# Per-hunter request budget. Per experiment 06 LEARNINGS hunters used
# 2-10 requests in practice; 20 gives headroom while still flagging loops.
DEFAULT_REQUEST_LIMIT = 20

# Per-source result cap. Caller can override; the agent never sees these
# numbers but they bound runtime + token usage.
DEFAULT_SEARCH_LIMIT = 25

# Max times each search tool may raise ModelRetry before the agent gives
# up on it. Pydantic AI's default of 1 is too tight for arxiv whose 3s
# rate limit + occasional 503s easily produce two consecutive retries.
SEARCH_TOOL_MAX_RETRIES = 4


class HunterReport(BaseModel):
    """The agent's free-text trace. The actual candidates come back separately."""

    queries_tried: list[str] = Field(
        default_factory=list,
        description="Queries the hunter actually issued to sources.",
    )
    notes: str = Field(
        min_length=20,
        description=(
            "2-3 sentences on what the hunter found, patterns it noticed, and any "
            "gaps. Useful for the orchestrator's synthesis."
        ),
    )


@dataclass
class HunterRunResult:
    """What `run_hunter` returns: the agent's trace + the gathered candidates."""

    angle: str
    candidates: list[WorkCandidate]
    queries_tried: list[str]
    notes: str
    elapsed_seconds: float
    request_count: int | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None


def _empty_seen() -> dict[str, WorkCandidate]:
    return {}


def _empty_queries() -> list[str]:
    return []


@dataclass
class HunterDeps:
    """Per-run state threaded through the agent's tools."""

    seen: dict[str, WorkCandidate] = field(default_factory=_empty_seen)
    queries_tried: list[str] = field(default_factory=_empty_queries)
    year_from: int | None = None
    year_to: int | None = None
    kinds: list[WorkKind] | None = None
    per_source_limit: int = DEFAULT_SEARCH_LIMIT


HUNTER_SYSTEM_PROMPT = """\
You are a paper hunter for a single research angle within a larger library
build. You have one tool per discovery source. Use them to gather candidate
works for the given angle.

Workflow:
1. Issue 2-4 search calls across the most relevant sources, varying the
   query phrasing where useful (e.g. one for the formal name of the angle,
   one for adjacent terms, one for a known seminal author or paper).
2. Don't re-issue an identical query against the same source.
3. Stop when you have a reasonable pool of candidates (typically 15-30
   total across sources) or when the last 2 calls returned mostly duplicates.
4. Return a HunterReport with the queries you tried and a 2-3 sentence note
   on patterns and gaps. The full candidate list is gathered automatically;
   you don't need to repeat titles in the report.

Do not invent candidates. Do not call the same tool with the same query
twice. Bias toward seminal/foundational works where the angle is
foundational; bias toward recent works where the angle is "recent SOTA".
"""


def _rank_candidates(candidates: list[WorkCandidate]) -> list[WorkCandidate]:
    """Stable deterministic ranking. Higher = better.

    Tiers in order: has_pdf > has_abstract > has_year > has_authors > none.
    Within a tier, citation count (when present) breaks ties; ties beyond
    that preserve input order.
    """

    def key(c: WorkCandidate) -> tuple[int, int, int, int, int]:
        cited_raw = c.extras.get("cited_by_count")
        cited = int(cited_raw) if isinstance(cited_raw, int) else 0
        return (
            1 if c.pdf_url else 0,
            1 if c.abstract else 0,
            1 if c.year is not None else 0,
            1 if c.authors else 0,
            cited,
        )

    return sorted(candidates, key=key, reverse=True)


def _summarize_tool_result(
    source_name: str, query: str, new_count: int, dup_count: int, sample_titles: list[str]
) -> str:
    """Compact text the agent sees as the tool's return value."""
    sample = "; ".join(sample_titles[:3]) if sample_titles else "(none)"
    return (
        f"{source_name}[{query!r}] → {new_count + dup_count} hits "
        f"({new_count} new, {dup_count} duplicate). "
        f"Sample new titles: {sample}"
    )


async def _run_one_source_search(
    source: DiscoverySource,
    query: str,
    deps: HunterDeps,
) -> str:
    """Execute a single source.search() with dedup + summary. Used by each tool."""
    try:
        results = await source.search(
            query,
            limit=deps.per_source_limit,
            year_from=deps.year_from,
            year_to=deps.year_to,
            kinds=deps.kinds,
        )
    except SourceUnavailable as exc:
        raise ModelRetry(
            f"{source.name} unavailable for query {query!r}: {exc}. "
            f"Try a different source or rephrase the query."
        ) from exc

    deps.queries_tried.append(f"{source.name}: {query}")

    new_titles: list[str] = []
    new_count = 0
    dup_count = 0
    for cand in results:
        if cand.candidate_id in deps.seen:
            dup_count += 1
            continue
        deps.seen[cand.candidate_id] = cand
        new_count += 1
        if len(new_titles) < 3:
            new_titles.append(cand.title)

    return _summarize_tool_result(source.name, query, new_count, dup_count, new_titles)


def _make_search_tool(
    source: DiscoverySource,
) -> Any:  # `Any` because Pydantic AI's tool decorator runtime is dynamic
    """Build the per-source tool function. Closure captures `source`."""
    source_name = source.name
    docstring = (
        f"Search the {source_name!r} discovery source for works matching the query.\n"
        f"\n"
        f"Args:\n"
        f"    query: Search terms. Use natural keywords specific to the angle.\n"
        f"\n"
        f"Returns a one-line summary of the hits found."
    )

    async def search_tool(ctx: RunContext[HunterDeps], query: str) -> str:
        return await _run_one_source_search(source, query, ctx.deps)

    search_tool.__name__ = f"search_{source_name}"
    search_tool.__doc__ = docstring
    return search_tool


def make_hunter_agent(
    *,
    enabled_sources: list[DiscoverySource],
    model: str = MODEL_FAST,
) -> Any:
    """Build a Pydantic AI Agent with one tool per provided source.

    Lazy import keeps `pydantic_ai` off the import path for callers that
    only need `HunterReport` / `HunterRunResult` for typing.
    """
    from pydantic_ai import Agent

    agent = Agent(
        model,
        deps_type=HunterDeps,
        output_type=HunterReport,
        system_prompt=HUNTER_SYSTEM_PROMPT,
    )

    for source in enabled_sources:
        tool = _make_search_tool(source)
        agent.tool(tool, retries=SEARCH_TOOL_MAX_RETRIES)  # pyright: ignore[reportCallIssue]

    return agent


async def run_hunter(
    *,
    topic: str,
    angle: str,
    query_seeds: list[str],
    registry: SourceRegistry,
    year_from: int | None = None,
    year_to: int | None = None,
    kinds: list[WorkKind] | None = None,
    per_source_limit: int = DEFAULT_SEARCH_LIMIT,
    model: str = MODEL_FAST,
    request_limit: int = DEFAULT_REQUEST_LIMIT,
    source_names: list[str] | None = None,
) -> HunterRunResult:
    """Run one hunter end-to-end for a single angle.

    Args:
        topic: The overall library topic (e.g. "diffusion models for image gen").
        angle: A specific sub-angle to pursue (e.g. "foundational papers").
        query_seeds: Seed phrasings the hunter should consider for its first
            search calls. The agent may also formulate variations.
        registry: Source registry with discovery plugins loaded.
        year_from / year_to / kinds: Filters passed through to each source.
        per_source_limit: Max results requested per source per call.
        model: LLM model identifier.
        request_limit: Hard cap on the agent's request count. Hitting this
            raises `pydantic_ai.exceptions.UsageLimitExceeded` — callers
            (the orchestrator) catch and convert to ModelRetry.
        source_names: If set, restrict the hunter to these source names
            (intersected with what the registry has enabled). Default: all.

    Returns a `HunterRunResult` with the deduped + heuristically-ranked
    candidates plus the agent's free-text notes.
    """
    if not angle.strip():
        msg = "run_hunter: angle must be non-empty"
        raise ValueError(msg)

    all_sources = registry.discovery_sources()
    if source_names is not None:
        wanted = set(source_names)
        sources = [s for s in all_sources if s.name in wanted]
    else:
        sources = all_sources

    if not sources:
        msg = (
            f"run_hunter: no enabled discovery sources for angle {angle!r} "
            f"(registry has {[s.name for s in all_sources]})"
        )
        raise SourceUnavailable(msg)

    from pydantic_ai.usage import UsageLimits

    agent = make_hunter_agent(enabled_sources=sources, model=model)
    deps = HunterDeps(
        year_from=year_from,
        year_to=year_to,
        kinds=kinds,
        per_source_limit=per_source_limit,
    )

    prompt = (
        f"Topic: {topic}\n"
        f"Angle: {angle}\n"
        f"Seed queries to try (or vary): {query_seeds}\n"
        f"\n"
        f"Available sources: {[s.name for s in sources]}.\n"
        f"Gather a useful pool of candidates for this angle, then return your "
        f"HunterReport."
    )

    started = time.perf_counter()
    result = await agent.run(
        prompt,
        deps=deps,
        usage_limits=UsageLimits(request_limit=request_limit),
    )
    elapsed = time.perf_counter() - started

    ranked = _rank_candidates(list(deps.seen.values()))

    usage = result.usage()
    return HunterRunResult(
        angle=angle,
        candidates=ranked,
        queries_tried=deps.queries_tried,
        notes=result.output.notes,
        elapsed_seconds=elapsed,
        request_count=usage.requests,
        input_tokens=usage.input_tokens,
        output_tokens=usage.output_tokens,
    )
