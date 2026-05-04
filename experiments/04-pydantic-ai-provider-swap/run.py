# /// script
# requires-python = ">=3.11"
# dependencies = [
#   "pydantic-ai-slim[openrouter]>=0.0.20",
#   "pydantic>=2",
# ]
# ///
"""Provider swap: same judge schema, multiple models via OpenRouter.

Validates the multi-provider promise (one OPENROUTER_API_KEY → many models)
and surfaces per-model differences in structured-output reliability,
verdict quality, latency, and cost.
"""

from __future__ import annotations

import asyncio
import os
import sys
import time
from dataclasses import dataclass
from pathlib import Path

from pydantic import BaseModel, Field
from pydantic_ai import Agent

# Models to swap through. Mix of families and price points.
MODELS = [
    ("Claude Sonnet 4.6 (Anthropic)", "openrouter:anthropic/claude-sonnet-4.6"),
    ("Claude Haiku 4.5 (Anthropic)", "openrouter:anthropic/claude-haiku-4.5"),
    ("GPT-5.1 (OpenAI)", "openrouter:openai/gpt-5.1"),
    ("Gemini 2.5 Pro (Google)", "openrouter:google/gemini-2.5-pro"),
    ("Llama 3.3 70B (Meta, open weights)", "openrouter:meta-llama/llama-3.3-70b-instruct"),
]

FIXTURE_TITLE = "Denoising Diffusion Probabilistic Models"
FIXTURE_AUTHORS = "Jonathan Ho, Ajay Jain, Pieter Abbeel"
FIXTURE_YEAR = 2020
FIXTURE_VENUE = "NeurIPS"
FIXTURE_ABSTRACT = """\
We present high quality image synthesis results using diffusion probabilistic
models, a class of latent variable models inspired by considerations from
nonequilibrium thermodynamics. Our best results are obtained by training on a
weighted variational bound designed according to a novel connection between
diffusion probabilistic models and denoising score matching with Langevin
dynamics, and our models naturally admit a progressive lossy decompression
scheme that can be interpreted as a generalization of autoregressive decoding.
On the unconditional CIFAR10 dataset, we obtain an Inception score of 9.46 and
a state-of-the-art FID score of 3.17. On 256x256 LSUN, we obtain sample quality
similar to ProgressiveGAN.
"""

COLLECTION_TOPIC = "diffusion models for image generation"
COLLECTION_NOTES = (
    "I care about foundational works and the lineage from VAEs and energy "
    "models. Less interested in pure product applications."
)


class Verdict(BaseModel):
    """The judge's verdict on a single candidate work."""

    relevance: int = Field(ge=0, le=10, description="Relevance to the collection topic, 0-10")
    seminality: int = Field(ge=0, le=10, description="How seminal/foundational the work is, 0-10")
    accept: bool = Field(description="Should this work be admitted to the library?")
    snowball_candidate: bool = Field(description="Should this work seed further snowballing?")
    reasoning: str = Field(min_length=20, description="2-4 sentence explanation of the verdict")
    concerns: list[str] = Field(default_factory=list, description="Reasons that lowered the score")


SYSTEM_PROMPT = """\
You are a research librarian judging whether a candidate work belongs in a
collection. Score relevance (0-10) and seminality (0-10), decide whether to
accept it, decide whether it should seed further citation snowballing (only
true for very seminal works), give 2-4 sentences of reasoning, and list any
specific concerns.
"""


def find_repo_root(start: Path) -> Path | None:
    for candidate in [start, *start.parents]:
        if (candidate / "README.md").exists() and (candidate / "docs").is_dir():
            return candidate
    return None


def load_env_into_os(env_path: Path) -> None:
    if not env_path.exists():
        return
    for raw in env_path.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key, value = key.strip(), value.strip().strip('"').strip("'")
        if key and value and key not in os.environ:
            os.environ[key] = value


@dataclass
class Run:
    label: str
    model: str
    ok: bool
    verdict: Verdict | None = None
    elapsed_s: float = 0.0
    input_tokens: int = 0
    output_tokens: int = 0
    error: str | None = None


async def judge_with(label: str, model: str, prompt: str) -> Run:
    print(f"\n=== {label} ===")
    print(f"    {model}")
    agent: Agent[None, Verdict] = Agent(
        model, output_type=Verdict, system_prompt=SYSTEM_PROMPT
    )
    started = time.perf_counter()
    try:
        result = await agent.run(prompt)
    except Exception as exc:
        elapsed = time.perf_counter() - started
        msg = f"{type(exc).__name__}: {exc}"
        print(f"    FAIL ({elapsed:.1f}s): {msg[:200]}")
        return Run(label=label, model=model, ok=False, elapsed_s=elapsed, error=msg)

    elapsed = time.perf_counter() - started
    verdict = result.output
    usage = result.usage()
    print(
        f"    OK ({elapsed:.1f}s, {usage.input_tokens}+{usage.output_tokens} tok) "
        f"rel={verdict.relevance} sem={verdict.seminality} "
        f"accept={verdict.accept} snow={verdict.snowball_candidate}"
    )
    print(f"    reasoning: {verdict.reasoning[:200]}{'…' if len(verdict.reasoning) > 200 else ''}")
    if verdict.concerns:
        for c in verdict.concerns:
            print(f"      concern: {c}")
    return Run(
        label=label,
        model=model,
        ok=True,
        verdict=verdict,
        elapsed_s=elapsed,
        input_tokens=usage.input_tokens or 0,
        output_tokens=usage.output_tokens or 0,
    )


async def main() -> int:
    here = Path(__file__).resolve().parent
    root = find_repo_root(here)
    if root is not None:
        load_env_into_os(root / ".env")

    if not os.environ.get("OPENROUTER_API_KEY"):
        print("FAIL: OPENROUTER_API_KEY not set.")
        return 1

    user_prompt = f"""\
Collection topic: {COLLECTION_TOPIC}
Collection notes: {COLLECTION_NOTES}

Candidate work:
- Title: {FIXTURE_TITLE}
- Authors: {FIXTURE_AUTHORS}
- Year: {FIXTURE_YEAR}
- Venue: {FIXTURE_VENUE}

Abstract:
{FIXTURE_ABSTRACT}

Judge it.
"""

    print(f"Judging '{FIXTURE_TITLE}' against '{COLLECTION_TOPIC}'")
    print(f"across {len(MODELS)} models via OpenRouter.")

    runs: list[Run] = []
    for label, model in MODELS:
        run = await judge_with(label, model, user_prompt)
        runs.append(run)

    print("\n\n=== Comparison ===")
    print(
        f"{'Model':<40} {'OK':<4} {'rel':<4} {'sem':<4} "
        f"{'acc':<4} {'snow':<5} {'sec':<6} {'tok':<8}"
    )
    print("-" * 80)
    for r in runs:
        if r.ok and r.verdict is not None:
            v = r.verdict
            print(
                f"{r.label:<40} {'✓':<4} {v.relevance:<4} {v.seminality:<4} "
                f"{('Y' if v.accept else 'N'):<4} {('Y' if v.snowball_candidate else 'N'):<5} "
                f"{r.elapsed_s:<6.1f} {r.input_tokens + r.output_tokens:<8}"
            )
        else:
            print(f"{r.label:<40} {'✗':<4} ({r.error[:60] if r.error else 'unknown'})")

    failures = [r for r in runs if not r.ok]
    print(f"\n{len(runs) - len(failures)}/{len(runs)} models returned valid verdicts.")

    return 0 if any(r.ok for r in runs) else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
