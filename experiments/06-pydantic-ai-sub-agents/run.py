# /// script
# requires-python = ">=3.11"
# dependencies = [
#   "pydantic-ai-slim[openrouter]>=0.0.20",
#   "pydantic>=2",
#   "rich>=13",
# ]
# ///
"""Sub-agent delegation: orchestrator spawns hunter sub-agents.

Three demos in sequence, simplest first:
  D0 — single hunter alone (baseline: how many requests does one hunter use?)
  DA — orchestrator with a `spawn_hunter` tool (model decides what to spawn)
  DB — explicit asyncio.gather over independent hunter agents (we decide)

Uses Haiku 4.5 (cheap+fast) since this experiment tests harness mechanics,
not judgment quality. Tight per-agent request caps so loops fail fast.
"""

from __future__ import annotations

import asyncio
import sys
import time
from pathlib import Path
from threading import Lock

from pydantic import BaseModel, Field
from pydantic_ai import Agent, ModelRetry, RunContext
from pydantic_ai.exceptions import UsageLimitExceeded
from pydantic_ai.usage import UsageLimits

# Allow `from _common import ...` despite PEP 723 isolation.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from _common import (  # noqa: E402
    MODEL_FAST,
    load_env_into_os,
    require_env,
    setup_logging,
)

log = setup_logging(verbose=False)
MODEL = MODEL_FAST

# Per-agent request budgets — small enough that real loops are loud, large
# enough to accommodate realistic exploratory search (a hunter may legitimately
# refine its query 2-3 times before settling).
HUNTER_REQUEST_LIMIT = 15
ORCHESTRATOR_REQUEST_LIMIT = 30


# ----- stub corpus -----

STUB_CORPUS: dict[str, list[dict[str, object]]] = {
    "foundations": [
        {
            "title": "Deep Unsupervised Learning Using Nonequilibrium Thermodynamics",
            "authors": "Sohl-Dickstein et al.",
            "year": 2015,
            "abstract": "Diffusion probabilistic models inspired by nonequilibrium thermodynamics.",
        },
        {
            "title": "Denoising Diffusion Probabilistic Models",
            "authors": "Ho, Jain, Abbeel",
            "year": 2020,
            "abstract": "DDPM. Variational bound + denoising score matching.",
        },
        {
            "title": "Score-Based Generative Modeling Through SDEs",
            "authors": "Song et al.",
            "year": 2021,
            "abstract": "Unifies score-based and diffusion models via SDEs.",
        },
        {
            "title": "Generative Modeling by Estimating Gradients of the Data Distribution",
            "authors": "Song & Ermon",
            "year": 2019,
            "abstract": "NCSN. Score matching + annealed Langevin.",
        },
    ],
    "recent": [
        {
            "title": "Analyzing and Improving the Training Dynamics of Diffusion Models",
            "authors": "Karras et al.",
            "year": 2024,
            "abstract": "EDM2; training stability + improved FID.",
        },
        {
            "title": "Scaling Rectified Flow Transformers",
            "authors": "Esser et al.",
            "year": 2024,
            "abstract": "Stable Diffusion 3; rectified flow + DiT.",
        },
    ],
    "applications": [
        {
            "title": "High-Resolution Image Synthesis With Latent Diffusion Models",
            "authors": "Rombach et al.",
            "year": 2022,
            "abstract": "Latent diffusion. Basis of Stable Diffusion.",
        },
        {
            "title": "Photorealistic Text-to-Image Diffusion Models",
            "authors": "Saharia et al.",
            "year": 2022,
            "abstract": "Imagen; LLM encoder + cascaded diffusion.",
        },
    ],
    "scheduling": [
        {
            "title": "Denoising Diffusion Implicit Models",
            "authors": "Song et al.",
            "year": 2021,
            "abstract": "DDIM; non-Markovian sampling.",
        },
        {
            "title": "Elucidating the Design Space of Diffusion-Based Generative Models",
            "authors": "Karras et al.",
            "year": 2022,
            "abstract": "EDM. Decomposed design space.",
        },
    ],
}


def stub_search(query: str) -> list[dict[str, object]]:
    """Match query keywords to canned papers. Always returns at least 2."""
    q = query.lower()
    matched: list[dict[str, object]] = []
    seen: set[str] = set()
    for key, papers in STUB_CORPUS.items():
        if key in q:
            for p in papers:
                title = str(p["title"])
                if title not in seen:
                    matched.append(p)
                    seen.add(title)
    if not matched:
        matched = STUB_CORPUS["foundations"][:2]
    return matched


# ----- schemas -----


class PaperCandidate(BaseModel):
    title: str
    authors: str
    year: int
    one_line_pitch: str = Field(
        description="One-sentence explanation of why this paper fits the angle."
    )


class HunterReport(BaseModel):
    angle: str = Field(description="Short label for the angle this hunter covered.")
    candidates: list[PaperCandidate] = Field(
        description="Up to 5 best candidates the hunter found."
    )
    notes: str = Field(min_length=20, description="2-3 sentences of patterns or gaps.")


# ----- hunter -----

# Tight workflow — one search call, then return. Stops the model from being
# too "exploratory" and burning requests.
HUNTER_SYSTEM = """\
You are a paper hunter for a single research angle.

WORKFLOW (mandatory):
1. Call `search_papers` ONCE with the most appropriate query for the angle.
2. From the results, pick up to 5 candidates that fit.
3. Return your HunterReport.

Do NOT call `search_papers` more than once unless the first result is empty.
Be selective: quality over quantity.
"""


def make_hunter() -> Agent[None, HunterReport]:
    hunter: Agent[None, HunterReport] = Agent(
        MODEL,
        output_type=HunterReport,
        system_prompt=HUNTER_SYSTEM,
    )

    @hunter.tool_plain
    def search_papers(query: str) -> list[dict[str, object]]:
        """Search for papers matching the query.

        Args:
            query: Use angle keywords like "foundations", "recent",
                "applications", "scheduling" for best matches.
        """
        results = stub_search(query)
        log.debug("[dim]search_papers(%r) → %d hits[/]", query, len(results))
        return results

    return hunter


# ----- orchestrator -----

ORCHESTRATOR_SYSTEM = """\
You are a research orchestrator building a literature collection on a topic.

WORKFLOW (mandatory):
1. Identify 3-4 distinct angles to pursue.
2. Spawn ONE hunter per angle via `spawn_hunter`. Issue all spawn calls in
   a SINGLE response (parallel tool calls).
3. After all hunters return, write a brief synthesis (2-3 paragraphs).

Do NOT spawn the same angle twice. Do NOT spawn more than 4 hunters total.
"""


def make_orchestrator() -> tuple[Agent[None, str], list[tuple[int, str]]]:
    """Returns (orchestrator, spawn_log) so the caller can inspect spawns."""
    orchestrator: Agent[None, str] = Agent(MODEL, system_prompt=ORCHESTRATOR_SYSTEM)

    spawn_log: list[tuple[int, str]] = []
    counter = 0
    counter_lock = Lock()

    @orchestrator.tool
    async def spawn_hunter(
        ctx: RunContext[None], angle: str, brief: str
    ) -> HunterReport:
        """Spawn a hunter sub-agent to find papers from a specific angle.

        Args:
            angle: One-phrase angle name (e.g., "foundations", "recent SOTA").
            brief: Detailed instructions for the hunter — what to search for and why.
        """
        nonlocal counter
        with counter_lock:
            counter += 1
            idx = counter

        log.info("[bold blue]hunter #%d spawn[/] angle=%r", idx, angle)
        hunter = make_hunter()
        try:
            result = await hunter.run(
                brief,
                usage_limits=UsageLimits(request_limit=HUNTER_REQUEST_LIMIT),
            )
        except UsageLimitExceeded as exc:
            # Convert to ModelRetry so the orchestrator sees a recoverable
            # signal (per experiment 02 finding) instead of crashing.
            log.warning(
                "hunter #%d (angle=%r) hit request limit; reporting as retry",
                idx,
                angle,
            )
            raise ModelRetry(
                f"hunter for angle {angle!r} ran out of request budget "
                f"({exc}); skip this angle or rephrase the brief and try a "
                f"different angle."
            ) from exc
        except Exception as exc:
            log.warning(
                "hunter #%d (angle=%r) failed: %s: %s",
                idx,
                angle,
                type(exc).__name__,
                exc,
            )
            raise

        u = result.usage()
        spawn_log.append((idx, angle))
        log.info(
            "[bold green]hunter #%d done[/] angle=%r candidates=%d "
            "tok=%s+%s reqs=%s",
            idx,
            angle,
            len(result.output.candidates),
            u.input_tokens,
            u.output_tokens,
            u.requests,
        )
        return result.output

    return orchestrator, spawn_log


# ----- demos -----


async def demo_0_single_hunter() -> None:
    log.info("[bold]" + "=" * 70 + "[/]")
    log.info("[bold]DEMO 0 — single hunter (baseline)[/]")
    log.info("[bold]" + "=" * 70 + "[/]")

    hunter = make_hunter()
    started = time.perf_counter()
    result = await hunter.run(
        "Find foundational diffusion model papers. The angle is 'foundations'.",
        usage_limits=UsageLimits(request_limit=HUNTER_REQUEST_LIMIT),
    )
    elapsed = time.perf_counter() - started

    u = result.usage()
    log.info(
        "single hunter: %d candidates, tok=%s+%s, reqs=%s, %.1fs",
        len(result.output.candidates),
        u.input_tokens,
        u.output_tokens,
        u.requests,
        elapsed,
    )
    for c in result.output.candidates:
        log.info("  • %s (%d) — %s", c.title, c.year, c.one_line_pitch)


async def demo_a_orchestrator() -> None:
    log.info("[bold]" + "=" * 70 + "[/]")
    log.info("[bold]DEMO A — orchestrator-driven (model decides what to spawn)[/]")
    log.info("[bold]" + "=" * 70 + "[/]")

    orch, spawn_log = make_orchestrator()
    prompt = (
        "Build a literature collection on diffusion models for image generation."
    )
    log.info("prompt: %s", prompt)

    started = time.perf_counter()
    try:
        result = await orch.run(
            prompt,
            usage_limits=UsageLimits(request_limit=ORCHESTRATOR_REQUEST_LIMIT),
        )
    except Exception as exc:
        elapsed = time.perf_counter() - started
        log.error(
            "orchestrator failed after %.1fs (%d hunter spawns logged): %s: %s",
            elapsed,
            len(spawn_log),
            type(exc).__name__,
            exc,
        )
        return
    elapsed = time.perf_counter() - started

    u = result.usage()
    log.info(
        "[bold green]orchestrator done[/] %d spawns, tok=%s+%s, reqs=%s, %.1fs",
        len(spawn_log),
        u.input_tokens,
        u.output_tokens,
        u.requests,
        elapsed,
    )
    log.info("synthesis:\n%s", result.output)


async def demo_b_parallel() -> None:
    log.info("[bold]" + "=" * 70 + "[/]")
    log.info("[bold]DEMO B — explicit parallel hunters (asyncio.gather)[/]")
    log.info("[bold]" + "=" * 70 + "[/]")

    angles = [
        ("foundations", "Find foundational diffusion model papers."),
        ("recent SOTA", "Find recent state-of-the-art diffusion papers."),
        ("applications", "Find diffusion model applications: latent, text-to-image."),
        ("scheduling", "Find work on samplers, schedulers, sampling design."),
    ]
    log.info("spawning %d hunters in parallel", len(angles))

    async def run_one(angle: str, brief: str) -> tuple[str, object, float]:
        hunter = make_hunter()
        t0 = time.perf_counter()
        result = await hunter.run(
            brief,
            usage_limits=UsageLimits(request_limit=HUNTER_REQUEST_LIMIT),
        )
        return angle, result, (time.perf_counter() - t0)

    started = time.perf_counter()
    results = await asyncio.gather(*[run_one(a, b) for a, b in angles])
    elapsed = time.perf_counter() - started

    individual = [r[2] for r in results]
    total_in = sum(int(r[1].usage().input_tokens or 0) for r in results)
    total_out = sum(int(r[1].usage().output_tokens or 0) for r in results)
    total_req = sum(int(r[1].usage().requests or 0) for r in results)

    log.info(
        "[bold green]all %d hunters done in %.1fs[/] "
        "(slowest=%.1fs → parallelism ✓ if ≈ slowest)",
        len(results),
        elapsed,
        max(individual),
    )
    log.info(
        "totals: tok=%d+%d, reqs=%d (across all %d hunters)",
        total_in,
        total_out,
        total_req,
        len(results),
    )

    for angle, result, t in results:
        report = result.output
        u = result.usage()
        log.info(
            "[blue]hunter angle=%r[/] %.1fs tok=%s+%s reqs=%s candidates=%d",
            angle,
            t,
            u.input_tokens,
            u.output_tokens,
            u.requests,
            len(report.candidates),
        )


async def main() -> int:
    load_env_into_os()
    require_env("OPENROUTER_API_KEY", log)

    log.info("[bold cyan]experiment 06 — sub-agent delegation[/]")
    log.info("model: %s", MODEL)
    log.info(
        "limits: hunter=%d req, orchestrator=%d req",
        HUNTER_REQUEST_LIMIT,
        ORCHESTRATOR_REQUEST_LIMIT,
    )

    await demo_0_single_hunter()
    await demo_a_orchestrator()
    await demo_b_parallel()

    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
