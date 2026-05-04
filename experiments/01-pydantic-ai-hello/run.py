# /// script
# requires-python = ">=3.11"
# dependencies = [
#   "pydantic-ai-slim[openrouter]>=0.0.20",
# ]
# ///
"""Hello-world Pydantic AI agent via OpenRouter.

Single-turn chat with Claude (routed through OpenRouter). Checks the basic
shape: install, auth, request, response, usage metadata, error handling.

We're using OpenRouter as the provider instead of going to Anthropic directly:
- Open-source friendly (one key for many providers)
- Lets users swap models without code changes
- Validates our multi-provider architecture early
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

from pydantic_ai import Agent

DEFAULT_PROMPT = "What is the capital of France? Answer in one sentence."
MODEL = "openrouter:anthropic/claude-sonnet-4.6"  # latest Sonnet via OpenRouter


def find_repo_root(start: Path) -> Path | None:
    """Walk up from `start` looking for repo root (README.md + docs/)."""
    for candidate in [start, *start.parents]:
        if (candidate / "README.md").exists() and (candidate / "docs").is_dir():
            return candidate
    return None


def load_env_into_os(env_path: Path) -> None:
    """Tiny .env loader (stdlib, no python-dotenv dep)."""
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


async def main() -> int:
    here = Path(__file__).resolve().parent
    root = find_repo_root(here)
    if root is not None:
        load_env_into_os(root / ".env")

    if not os.environ.get("OPENROUTER_API_KEY"):
        print("FAIL: OPENROUTER_API_KEY not set.")
        print("Set it in .env at the repo root, or export it in your shell.")
        return 1

    prompt = " ".join(sys.argv[1:]) or DEFAULT_PROMPT

    print(f"Model:  {MODEL}")
    print(f"Prompt: {prompt}\n")

    agent = Agent(MODEL, system_prompt="You are a concise, helpful assistant.")

    try:
        result = await agent.run(prompt)
    except Exception as exc:  # surface the type so we know what to handle later
        print(f"FAIL: {type(exc).__name__}: {exc}")
        return 1

    print("--- response ---")
    print(result.output)
    print()

    usage = result.usage()
    print("--- usage ---")
    print(f"  input tokens:  {usage.input_tokens}")
    print(f"  output tokens: {usage.output_tokens}")
    print(f"  total tokens:  {usage.total_tokens}")
    print(f"  requests:      {usage.requests}")

    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
