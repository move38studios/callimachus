# /// script
# requires-python = ">=3.11"
# dependencies = [
#   "pydantic-ai-slim[openrouter]>=0.0.20",
# ]
# ///
"""Companion to run.py — what happens when the tool raises?"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

from pydantic_ai import Agent, ModelRetry

MODEL = "openrouter:anthropic/claude-sonnet-4.6"


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


async def main() -> int:
    here = Path(__file__).resolve().parent
    root = find_repo_root(here)
    if root is not None:
        load_env_into_os(root / ".env")

    if not os.environ.get("OPENROUTER_API_KEY"):
        print("FAIL: OPENROUTER_API_KEY not set.")
        return 1

    agent = Agent(
        MODEL,
        system_prompt=(
            "You are a helpful assistant. Use the get_current_weather tool. "
            "If the tool fails, explain to the user what went wrong."
        ),
    )

    @agent.tool_plain
    def get_current_weather(city: str) -> str:
        """Get the current weather for a city.

        Args:
            city: The city name.
        """
        # Use ModelRetry: the agent SEES the error and can recover/explain.
        # Plain `raise RuntimeError(...)` would propagate up to the caller
        # without the model knowing.
        raise ModelRetry(f"weather service is down (city={city})")

    print(f"Model: {MODEL}\n")
    print("Asking for Paris weather; tool will raise. Watching what happens.\n")

    try:
        result = await agent.run("What's the weather in Paris?")
    except Exception as exc:
        print(f"Agent.run raised: {type(exc).__name__}: {exc}")
        return 0  # we wanted to see how the error surfaces

    print("--- response ---")
    print(result.output)
    print()

    print("--- message history ---")
    for msg in result.all_messages():
        kind = type(msg).__name__
        print(f"  [{kind}]")
        for part in getattr(msg, "parts", []):
            part_kind = type(part).__name__
            preview = str(getattr(part, "content", part))[:200].replace("\n", " ")
            print(f"      {part_kind}: {preview}")
    print()

    usage = result.usage()
    print(f"--- usage ---")
    print(f"  total tokens: {usage.total_tokens}, requests: {usage.requests}")

    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
