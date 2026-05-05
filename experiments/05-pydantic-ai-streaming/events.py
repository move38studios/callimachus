# /// script
# requires-python = ">=3.11"
# dependencies = [
#   "pydantic-ai-slim[openrouter]>=0.0.20",
# ]
# ///
"""Watch high-level events fire — agent.run_stream_events().

This is what feeds the status bar / works list in the TUI: granular events
(part deltas, tool starts/ends, final result) with millisecond timing so
you can judge how live the stream feels.

  uv run experiments/05-pydantic-ai-streaming/events.py
  uv run experiments/05-pydantic-ai-streaming/events.py "Compare Paris and Tokyo weather."
"""

from __future__ import annotations

import asyncio
import os
import sys
import time
from collections import Counter
from pathlib import Path

from pydantic_ai import Agent

MODEL = "openrouter:anthropic/claude-sonnet-4.6"
DEFAULT_PROMPT = "What's the weather in Paris and Tokyo? Brief comparison."


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


def event_preview(event: object) -> str:
    """Short human preview of an event."""
    bits: list[str] = []
    for attr in ("tool_name", "delta", "content"):
        val = getattr(event, attr, None)
        if val is not None:
            text = str(val)[:80].replace("\n", " ")
            bits.append(f"{attr}={text}")
    part = getattr(event, "part", None)
    if part is not None:
        part_kind = type(part).__name__
        for attr in ("tool_name", "content"):
            val = getattr(part, attr, None)
            if val is not None:
                text = str(val)[:80].replace("\n", " ")
                bits.append(f"part.{attr}={text}")
        if not any("part." in b for b in bits):
            bits.append(f"part={part_kind}")
    result = getattr(event, "result", None)
    if result is not None:
        content = getattr(result, "content", result)
        bits.append(f"result={str(content)[:80].replace(chr(10), ' ')}")
    return " | ".join(bits) or "(no preview attrs)"


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
    print("\nWatching run_stream_events() — each line is one event with timing.\n")

    started = time.perf_counter()
    counts: Counter[str] = Counter()
    last_event_at = started

    async for event in agent.run_stream_events(prompt):
        now = time.perf_counter()
        elapsed = now - started
        delta = (now - last_event_at) * 1000  # ms since last event
        last_event_at = now

        kind = type(event).__name__
        counts[kind] += 1

        # PartDeltaEvent fires per-token — collapse them visually
        if kind == "PartDeltaEvent":
            print(f"[{elapsed:6.2f}s +{delta:5.0f}ms] {kind}: {event_preview(event)}")
        else:
            print(f"[{elapsed:6.2f}s +{delta:5.0f}ms] {kind}: {event_preview(event)}")

    print(f"\nElapsed: {time.perf_counter() - started:.2f}s\n")
    print("Event type counts:")
    for kind, count in counts.most_common():
        print(f"  {kind}: {count}")

    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
