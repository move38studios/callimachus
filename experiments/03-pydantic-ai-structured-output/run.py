# /// script
# requires-python = ">=3.11"
# dependencies = [
#   "pydantic-ai-slim[openrouter]>=0.0.20",
#   "pydantic>=2",
# ]
# ///
"""Structured output: agent returns a typed Pydantic model.

Prototype for the judge that scores every candidate work in discovery.
Validates that we get a real Pydantic instance back (not JSON wrangling),
and watches what happens when the model produces invalid output.
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

from pydantic import BaseModel, Field
from pydantic_ai import Agent

MODEL = "openrouter:anthropic/claude-sonnet-4.6"

# Real abstract: Ho et al. 2020, "Denoising Diffusion Probabilistic Models"
# (https://arxiv.org/abs/2006.11239)
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

FIXTURE_TITLE = "Denoising Diffusion Probabilistic Models"
FIXTURE_AUTHORS = "Jonathan Ho, Ajay Jain, Pieter Abbeel"
FIXTURE_YEAR = 2020
FIXTURE_VENUE = "NeurIPS"

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
    snowball_candidate: bool = Field(
        description="Should this work seed further citation snowballing?"
    )
    reasoning: str = Field(
        min_length=20, description="Brief explanation of the verdict (2-4 sentences)"
    )
    concerns: list[str] = Field(
        default_factory=list, description="Specific reasons that lowered the score, if any"
    )


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


SYSTEM_PROMPT = """\
You are a research librarian judging whether a candidate work belongs in a
collection. Score on:

- relevance (0-10): how well the work fits the collection topic and notes
- seminality (0-10): how foundational, novel, or load-bearing the work is in
  its area. A landmark paper is 9-10; an incremental contribution is 3-5;
  a tangential mention is 0-2.
- accept: would you put this in the library? (true if relevance + seminality
  together justify inclusion)
- snowball_candidate: should this seed further citation snowballing? (true
  only for works that score very high on seminality — ~8+)
- reasoning: 2-4 sentences explaining the verdict
- concerns: list any specific concerns that lowered the score

Be honest. If you don't have enough information to judge, score conservatively
and put your uncertainty in `concerns`.
"""


async def main() -> int:
    here = Path(__file__).resolve().parent
    root = find_repo_root(here)
    if root is not None:
        load_env_into_os(root / ".env")

    if not os.environ.get("OPENROUTER_API_KEY"):
        print("FAIL: OPENROUTER_API_KEY not set.")
        return 1

    agent = Agent(MODEL, output_type=Verdict, system_prompt=SYSTEM_PROMPT)

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

    print(f"Model: {MODEL}")
    print(f"Judging: {FIXTURE_TITLE} ({FIXTURE_YEAR}) against '{COLLECTION_TOPIC}'\n")

    try:
        result = await agent.run(user_prompt)
    except Exception as exc:
        print(f"FAIL: {type(exc).__name__}: {exc}")
        return 1

    verdict = result.output

    print("--- verdict (typed) ---")
    print(f"  type:       {type(verdict).__name__}")
    print(f"  relevance:  {verdict.relevance}")
    print(f"  seminality: {verdict.seminality}")
    print(f"  accept:     {verdict.accept}")
    print(f"  snowball:   {verdict.snowball_candidate}")
    print(f"  reasoning:  {verdict.reasoning}")
    print(f"  concerns:   {verdict.concerns or '(none)'}")
    print()

    print("--- type checks ---")
    print(f"  isinstance(verdict, Verdict): {isinstance(verdict, Verdict)}")
    print(f"  type(verdict.relevance):      {type(verdict.relevance).__name__}")
    print(f"  type(verdict.accept):         {type(verdict.accept).__name__}")
    print(f"  type(verdict.concerns):       {type(verdict.concerns).__name__}")
    print()

    print("--- message history ---")
    request_count = 0
    for msg in result.all_messages():
        kind = type(msg).__name__
        request_count += 1 if kind == "ModelRequest" else 0
        print(f"  [{kind}]")
        for part in getattr(msg, "parts", []):
            part_kind = type(part).__name__
            preview = str(getattr(part, "content", part))[:140].replace("\n", " ")
            print(f"      {part_kind}: {preview}")
    print()

    usage = result.usage()
    print("--- usage ---")
    print(f"  input tokens:  {usage.input_tokens}")
    print(f"  output tokens: {usage.output_tokens}")
    print(f"  total tokens:  {usage.total_tokens}")
    print(f"  requests:      {usage.requests}  (>1 indicates a validation retry)")

    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
