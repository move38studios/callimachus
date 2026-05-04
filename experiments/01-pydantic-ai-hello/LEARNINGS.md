# 01 — pydantic-ai-hello — LEARNINGS

## Run log

- **2026-05-04**, macOS, Python 3.12 (uv-managed venv from inline script metadata).
  - First run: success. Model returned a coherent answer to "What is the capital of France?". 24 packages installed in 33ms.
  - Second run (after fixing token field deprecations): clean output, no warnings. Custom prompt worked too.
  - Latency: subjectively under 2 seconds per call. Good enough for interactive experiments.

## Findings

- **Model string format**: `openrouter:anthropic/claude-sonnet-4.6` works. Note: OpenRouter uses **dots** for the version (`4.6`), while Anthropic's direct API uses **dashes** (`claude-sonnet-4-6`). The two naming conventions diverge — be careful when swapping providers.
- **Auth**: `OpenRouterProvider` reads `OPENROUTER_API_KEY` from the environment automatically. No explicit provider construction needed for the simple case.
- **Install footprint**: 24 packages via `pip install pydantic-ai-slim[openrouter]`. Includes `pydantic-ai-slim`, `pydantic-ai`, `httpx`, `eval-type-backport`, `griffe`, `logfire-api`, etc. Reasonable.
- **Inline script metadata (PEP 723) + `uv run`**: works perfectly. Each experiment is fully self-contained — no need to add experiment deps to the main project. This is the right model for our experiments.
- **Stdlib `.env` loader** copied into `run.py` works fine. We'll keep this pattern across experiments rather than each one taking a `python-dotenv` dep.
- **Result API**: `result.output` for the text, `result.usage()` for token counts. Usage object has `input_tokens`, `output_tokens`, `total_tokens`, `requests` — clean.
- **API drift**: `request_tokens` → `input_tokens` and `response_tokens` → `output_tokens` are the current names. Older docs / code use the deprecated forms.
- **Cost not exposed by `usage()`**. We'd need to either (a) compute cost from tokens × known per-model rates, or (b) call OpenRouter's `/api/v1/credits` endpoint to track spend. Decision deferred to a later experiment when cost tracking actually matters (probably the snowball loop).
- **System prompt** lives in `Agent(model, system_prompt=...)`. Clean and explicit.
- **Errors**: I didn't deliberately trigger an error this run, but the broad `except Exception` will surface the type — sufficient for this hello-world. Future experiments should test specific error types (auth failure, rate limit, invalid model) explicitly.

## Decisions

- **Pydantic AI is confirmed as the agent harness.** API is ergonomic, install is light, OpenRouter integration is first-class.
- **Default LLM access pattern: OpenRouter.** Multi-provider via one key, matches our open-source positioning. Anthropic-direct stays available as a config option but isn't the default.
- **Canonical model string for Sonnet 4.6**: `openrouter:anthropic/claude-sonnet-4.6` (dot notation, OpenRouter convention).
- **Inline script metadata (PEP 723) is the experiment dependency convention.** No experiment deps go into the main `pyproject.toml`.
- **`.env` loader pattern in experiments**: copy the stdlib parser from `00-env-check`. Don't take a `python-dotenv` dep just for experiments.

## Bonus finding — Perplexity is on OpenRouter

While verifying the OpenRouter setup, also confirmed that **Perplexity Sonar models are available via OpenRouter** (e.g. `perplexity/sonar` at $1/$1 per M tokens, plus `sonar-pro`, `sonar-deep-research`, etc.). This means `OPENROUTER_API_KEY` covers both our LLM (Claude) and our planning-phase synthesis (Perplexity) — no separate `PERPLEXITY_API_KEY` needed in the default setup. Mistral OCR remains separate (different product, not chat completion).

Implication: simpler `.env`, simpler README. `PERPLEXITY_API_KEY` stays as an opt-in for users who want direct Perplexity API features.

## Open questions

- How does `Agent` behave on streaming? (experiment 05)
- What does a tool-call loop look like end-to-end? (experiment 02)
- How do we get cost out of OpenRouter — token math, or a separate credits API call?
- What does the deprecated-warning policy look like as Pydantic AI evolves? Do we pin a minor version, or track latest?
