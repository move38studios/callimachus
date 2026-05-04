# 01 — pydantic-ai-hello

Single-turn chat with Claude (Sonnet 4.6) via Pydantic AI's `OpenRouterProvider`. The first real test of our chosen agent harness — does the basic shape of the API match what we expect?

## What we're testing

- Pydantic AI installs cleanly via uv inline-script metadata (no need to add to project deps)
- OpenRouter auth works via `OPENROUTER_API_KEY` from environment
- The `openrouter:anthropic/claude-sonnet-4.6` model string resolves correctly
- The agent loop returns a result we can inspect (text, usage, model used)
- Errors (missing key, invalid model, rate limit) surface clearly

We're going through OpenRouter rather than Anthropic direct: validates the multi-provider architecture from the start, and gives users a single key for many models.

## Run

The script declares its own deps via PEP 723 inline metadata, so `uv run` creates an isolated venv on the fly — no need to add `pydantic-ai` to project deps:

```bash
# Make sure your .env has OPENROUTER_API_KEY set
cp .env.example .env  # then edit it

# From the repo root
uv run experiments/01-pydantic-ai-hello/run.py "What is the capital of France?"

# Default prompt if none given:
uv run experiments/01-pydantic-ai-hello/run.py
```

## Success criteria

- Exit code 0
- A coherent answer to the prompt is printed
- Usage metadata (input tokens, output tokens, request count) is printed
- A clear error if `OPENROUTER_API_KEY` is missing

## Why this matters

Pydantic AI is the agent harness for the entire product. If its hello-world doesn't feel right — awkward API, opaque errors, hidden state — we want to know now, before building the orchestrator and hunters on top of it.
