# /// script
# requires-python = ">=3.11"
# dependencies = [
#   "pydantic-ai-slim[openrouter]>=0.0.20",
# ]
# ///
"""Tool-calling agent: model decides to call a Python function and uses the result.

Validates the loop that every hunter, the orchestrator, and the judge will sit on.
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

from pydantic_ai import Agent

DEFAULT_PROMPT = "What's the current weather in Paris? Be concise."
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


# Track every tool invocation so we can verify the loop happened
TOOL_CALL_LOG: list[dict[str, object]] = []


async def main() -> int:
    here = Path(__file__).resolve().parent
    root = find_repo_root(here)
    if root is not None:
        load_env_into_os(root / ".env")

    if not os.environ.get("OPENROUTER_API_KEY"):
        print("FAIL: OPENROUTER_API_KEY not set.")
        return 1

    prompt = " ".join(sys.argv[1:]) or DEFAULT_PROMPT

    print(f"Model:  {MODEL}")
    print(f"Prompt: {prompt}\n")

    agent = Agent(
        MODEL,
        system_prompt=(
            "You are a helpful assistant. When the user asks about weather, "
            "use the get_current_weather tool. Never invent weather data — "
            "always call the tool, even for cities you think you know."
        ),
    )

    @agent.tool_plain
    def get_current_weather(city: str) -> str:
        """Get the current weather for a city.

        Args:
            city: The city name, e.g. "Paris", "Tokyo", "San Francisco".

        Returns:
            A short text description of current conditions.
        """
        TOOL_CALL_LOG.append({"tool": "get_current_weather", "city": city})
        stubs = {
            "paris": "12°C, light rain",
            "tokyo": "18°C, sunny",
            "san francisco": "16°C, foggy",
            "london": "9°C, overcast",
        }
        return stubs.get(city.lower(), f"Weather data unavailable for {city}")

    try:
        result = await agent.run(prompt)
    except Exception as exc:
        print(f"FAIL: {type(exc).__name__}: {exc}")
        return 1

    print("--- response ---")
    print(result.output)
    print()

    print("--- tool calls observed ---")
    if TOOL_CALL_LOG:
        for entry in TOOL_CALL_LOG:
            print(f"  {entry}")
    else:
        print("  (none — model answered without calling the tool)")
    print()

    print("--- message history ---")
    for msg in result.all_messages():
        kind = type(msg).__name__
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
    print(f"  requests:      {usage.requests}  (> 1 means a tool round-trip happened)")

    if not TOOL_CALL_LOG:
        print("\nNOTE: model didn't call the tool — that's a failure for this experiment.")
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
