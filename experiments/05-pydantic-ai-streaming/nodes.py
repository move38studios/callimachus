# /// script
# requires-python = ">=3.11"
# dependencies = [
#   "pydantic-ai-slim[openrouter]>=0.0.20",
# ]
# ///
"""Watch the agent's brain — node-level iteration via agent.iter().

This is what feeds the orchestrator pane in the TUI: every model request,
every tool call, every model response, in order, with timing.

  uv run experiments/05-pydantic-ai-streaming/inspect.py
  uv run experiments/05-pydantic-ai-streaming/inspect.py "Compare Paris and Tokyo weather."
"""

from __future__ import annotations

import asyncio
import os
import sys
import time
from pathlib import Path

from pydantic_ai import Agent

MODEL = "openrouter:anthropic/claude-sonnet-4.6"
DEFAULT_PROMPT = "What's the weather in Paris and Tokyo? Give a brief comparison."


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

    prompt = " ".join(sys.argv[1:]) or DEFAULT_PROMPT

    agent: Agent[None, str] = Agent(
        MODEL,
        system_prompt=(
            "You are a helpful assistant. When asked about weather, call "
            "get_current_weather. Never invent data."
        ),
    )

    @agent.tool_plain
    def get_current_weather(city: str) -> str:
        """Get current weather for a city.

        Args:
            city: The city name.
        """
        stubs = {
            "paris": "12°C, light rain",
            "tokyo": "18°C, sunny",
            "san francisco": "16°C, foggy",
            "london": "9°C, overcast",
        }
        return stubs.get(city.lower(), f"Weather data unavailable for {city}")

    print(f"Model:  {MODEL}")
    print(f"Prompt: {prompt}")
    print("\nWatching agent.iter() — each line is a graph node as it completes.\n")

    started = time.perf_counter()

    async with agent.iter(prompt) as agent_run:
        node_index = 0
        async for node in agent_run:
            node_index += 1
            elapsed = time.perf_counter() - started
            kind = type(node).__name__
            print(f"[{elapsed:6.2f}s] node {node_index}: {kind}")

            # Show the most useful attribute per node type
            if hasattr(node, "user_prompt") and node.user_prompt is not None:
                print(f"            user_prompt: {str(node.user_prompt)[:120]}")
            if hasattr(node, "model_response") and node.model_response is not None:
                resp = node.model_response
                for part in getattr(resp, "parts", []):
                    part_kind = type(part).__name__
                    preview = str(getattr(part, "content", part))[:120].replace("\n", " ")
                    print(f"            response part: {part_kind}: {preview}")
            if hasattr(node, "request") and node.request is not None:
                req = node.request
                for part in getattr(req, "parts", []):
                    part_kind = type(part).__name__
                    preview = str(getattr(part, "content", part))[:120].replace("\n", " ")
                    print(f"            request part:  {part_kind}: {preview}")
            if hasattr(node, "data"):
                print(f"            data: {str(node.data)[:120]}")
            print()

        result = agent_run.result
        usage = agent_run.usage()

    if result is not None:
        print(f"--- final output ---")
        print(result.output)

    print(f"\n--- usage ---")
    print(f"  input tokens:  {usage.input_tokens}")
    print(f"  output tokens: {usage.output_tokens}")
    print(f"  requests:      {usage.requests}")
    print(f"  total elapsed: {time.perf_counter() - started:.2f}s")

    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
