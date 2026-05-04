# Learnings

The cumulative log of what we discover while building Callimachus. Each component experiment in `experiments/` has its own `LEARNINGS.md` with the full detail; this top-level file collects the highlights, surprises, and decisions that bind future work.

The convention: when an experiment surfaces something that future-you (or a future contributor) needs to know — a gotcha, a non-obvious choice, a default we landed on — note it in the experiment's local LEARNINGS, and if it's broadly relevant, summarise it here in one or two sentences with a link.

## How to read this file

Entries are ordered newest-first. Each entry is short. If you need depth, follow the link to the experiment's local LEARNINGS or the relevant doc.

## Entries

### 2026-05-04 — Provider swap works across 5 model families; Gemini caveat may not apply

Same `Verdict` schema, same fixture, swapped across Claude Sonnet 4.6, Claude Haiku 4.5, GPT-5.1, Gemini 2.5 Pro, and Llama 3.3 70B via OpenRouter. **5/5 returned valid verdicts.** Provider swap is a one-line change as the docs promised. Verdict consistency is high — all four frontier models scored DDPM 10/10/Y/Y; Llama was slightly more conservative at 9/8 but still accepted+snowballed. Notable: GPT-5.1 used ~half the input tokens of Anthropic models (different schema encoding); Gemini was more verbose in output. Surprising: Haiku 4.5 was slowest (21.9s) — needs re-test on a different day before drawing latency conclusions.

**Gemini caveat softened**: Gemini 2.5 Pro returned a valid structured output via the default Tool Output mode. The Pydantic AI docs warning may apply to older Gemini, or the framework auto-handles it, or OpenRouter normalises it. We don't need to pre-emptively code around it. ARCHITECTURE.md updated to soften this claim.

Concern surfacing varies by model: only GPT-5.1 populated `concerns` with useful items; others returned empty. Implication: empty concerns means "no information" rather than "no concerns" — model-dependent.

Default workhorse judge: **Sonnet 4.6**. Cheap-mode option: Llama 3.3 70B. Synthesis pass model TBD.

- **Source**: [`experiments/04-pydantic-ai-provider-swap/LEARNINGS.md`](experiments/04-pydantic-ai-provider-swap/LEARNINGS.md)
- **Affects**: `ARCHITECTURE.md` provider-caveats paragraph (softened); informs default model selection in M2.

### 2026-05-04 — Structured output (judge prototype) works via Tool Output mode

Pydantic AI returns a typed Pydantic model via its **Tool Output mode** by default — the schema becomes a synthetic `final_result` tool that the model "calls" with structured args. Because OpenRouter relays tool calls cleanly, structured output is as reliable as tool calling here (sidestepping older OpenRouter issues with Native JSON mode). Single request, no retries needed. Sonnet 4.6 produced a thoughtful judgment of the Ho 2020 DDPM abstract (relevance=10, seminality=10, accept=True, snowball=True) with full reasoning. Type checks all pass — `int`/`bool`/`list[str]` preserved.

**Caveat to track**: per Pydantic AI docs, Gemini can't combine tools and structured output. If we ever route the judge through Gemini, the LLMProvider wrapper must auto-select `NativeOutput` mode for that path.

Schema design note: `Field(...)` descriptions are sent to the model and function as part of the prompt. Treat them with the same care as system-prompt wording.

- **Source**: [`experiments/03-pydantic-ai-structured-output/LEARNINGS.md`](experiments/03-pydantic-ai-structured-output/LEARNINGS.md)
- **Affects**: `ARCHITECTURE.md` provider abstraction (note Gemini caveat for judge path).

### 2026-05-04 — Tool calling works; ModelRetry is the lever for graceful failure

Pydantic AI's tool loop runs autonomously: type hints + docstring auto-derive the schema; `result.all_messages()` exposes the full exchange. **Parallel tool calls in a single turn work natively** — the orchestrator can fan out to N hunter tools in one round-trip. Important error-handling distinction: plain exceptions from tools propagate to the caller (model never sees them), while `pydantic_ai.ModelRetry("...")` is fed back as a `RetryPromptPart` so the model can recover. Binds: source plugins should use `ModelRetry` for graceful degradation on outages; judge/orchestrator internal failures should `raise` normally for hard fail.

Also: OpenRouter routes through multiple Anthropic backends (direct, Vertex, Bedrock) — `tool_call_id` prefixes vary (`toolu_*`, `toolu_vrtx_*`, `toolu_bdrk_*`). Don't assume the prefix shape.

Cost note: adding one tool with a one-line schema added ~1400 tokens of overhead per request. Implication: keep each agent's toolbox minimal and focused.

- **Source**: [`experiments/02-pydantic-ai-tool-calling/LEARNINGS.md`](experiments/02-pydantic-ai-tool-calling/LEARNINGS.md)
- **Affects**: `ARCHITECTURE.md` (source plugin contract should specify `ModelRetry` for graceful failures), `PLUGINS.md` (mention this in the Resolver/DiscoverySource Protocol docs).

### 2026-05-04 — Pydantic AI hello-world via OpenRouter green; Perplexity also on OpenRouter

`openrouter:anthropic/claude-sonnet-4.6` works as the model string with `pydantic-ai-slim[openrouter]`. `OpenRouterProvider` reads `OPENROUTER_API_KEY` from env automatically. Result API: `result.output` for text, `result.usage()` for tokens (`input_tokens`/`output_tokens`). PEP 723 inline-script metadata + `uv run` validated as the experiment-deps convention. **OpenRouter is the default LLM access pattern**; Anthropic-direct stays available as a config option. Note: OpenRouter uses dot-notation versions (`4.6`); Anthropic-direct uses dash-notation (`4-6`) — naming conventions diverge across providers.

**Bonus**: Perplexity Sonar models (`perplexity/sonar`, `sonar-pro`, `sonar-deep-research`) are available on OpenRouter too. One `OPENROUTER_API_KEY` covers both LLM (Claude) and planning-phase synthesis (Perplexity) — `PERPLEXITY_API_KEY` becomes optional. Mistral OCR stays separate (different product).

- **Source**: [`experiments/01-pydantic-ai-hello/LEARNINGS.md`](experiments/01-pydantic-ai-hello/LEARNINGS.md)
- **Affects**: `ARCHITECTURE.md` (LLM access default + perplexity routing), `README.md` API keys table, `PLUGINS.md` perplexity bundled-plugin description, `.env.example`.

### 2026-05-04 — Phase 0 tooling green

Minimal package skeleton (`src/callimachus/__init__.py` exposing `__version__`) plus dev tooling all pass on first try: `uv sync --group dev`, `ruff check`, `ruff format --check`, `pyright` (strict mode, 0 errors), `pytest` (1 smoke test). Phase 0 of `DEV_PLAN.md` is complete; ready to move into experiment 01 (Pydantic AI hello-world).

- **Affects**: `pyproject.toml` is the source of truth for tool versions and configs. CLAUDE.md captures the coding-style brief (DRY, Pydantic at boundaries, pyright + ruff, tests where they earn their keep, docs-and-code-stay-in-sync as the golden rule).

### 2026-05-04 — env-check passes; stdlib-only is enough for experiments

Smoke test green on macOS / Python 3.14.4. Stdlib `.env` parsing handles the basic case fine; we'll switch to `pydantic-settings` for product code. Repo-root detection convention (`README.md` + `docs/`) established for future experiments to reuse.

- **Source**: [`experiments/00-env-check/LEARNINGS.md`](experiments/00-env-check/LEARNINGS.md)
- **Affects**: nothing binding — confirms baseline assumptions hold.

## Format for entries

```markdown
### YYYY-MM-DD — short title

One- or two-sentence summary of the finding or decision.

- **Source**: `experiments/NN-name/LEARNINGS.md`
- **Affects**: which doc / module / decision this binds (e.g. `ARCHITECTURE.md` chunking, default embedding model, etc.)
```

## Cross-cutting decisions log

A separate, narrower table of decisions that have been made and where they're recorded canonically. Use this to find "what did we decide about X?" without reading every entry.

| Decision | Value | Recorded in |
| --- | --- | --- |
| Minimum Python version | 3.11 | `ARCHITECTURE.md`, `experiments/00-env-check/LEARNINGS.md` |
| `.env` parsing — experiments | stdlib (KEY=VALUE, comments, blanks, optional quotes) | `experiments/00-env-check/LEARNINGS.md` |
| `.env` parsing — product code | `pydantic-settings` | `experiments/00-env-check/LEARNINGS.md` |
| Repo-root detection convention | walk up looking for `README.md` + `docs/` | `experiments/00-env-check/run.py` |
| Type checker | `pyright` strict mode | `pyproject.toml`, `CLAUDE.md` |
| Lint + format | `ruff` (replaces black + isort + flake8) | `pyproject.toml`, `CLAUDE.md` |
| Test runner | `pytest` + `pytest-asyncio`, `asyncio_mode = "auto"`, `-m "not live"` default | `pyproject.toml` |
| Live-API tests | gated behind `pytest -m live`, excluded from default + CI | `pyproject.toml`, `CLAUDE.md` |
| Dev deps style | PEP 735 `[dependency-groups]` (uv-native) over `[project.optional-dependencies]` | `pyproject.toml` |
| Build backend | `hatchling` | `pyproject.toml` |
| Agent harness | Pydantic AI (`pydantic-ai-slim[openrouter]`) | `ARCHITECTURE.md`, `experiments/01-pydantic-ai-hello/LEARNINGS.md` |
| Default LLM access | OpenRouter (one key, many models) | `experiments/01-pydantic-ai-hello/LEARNINGS.md` |
| Perplexity routing | via OpenRouter (`perplexity/sonar`); `PERPLEXITY_API_KEY` is opt-in | `experiments/01-pydantic-ai-hello/LEARNINGS.md` |
| Canonical Sonnet 4.6 model string | `openrouter:anthropic/claude-sonnet-4.6` | `experiments/01-pydantic-ai-hello/LEARNINGS.md` |
| Experiment dependency convention | PEP 723 inline-script metadata, run via `uv run` | `experiments/01-pydantic-ai-hello/LEARNINGS.md` |
| Token field names (Pydantic AI) | `input_tokens` / `output_tokens` (not `request_/response_`) | `experiments/01-pydantic-ai-hello/run.py` |
| Tool decorator | `@agent.tool_plain` (no context) or `@agent.tool` (with `RunContext`) | `experiments/02-pydantic-ai-tool-calling/LEARNINGS.md` |
| Tool schema source | type hints + docstring `Args:` section | `experiments/02-pydantic-ai-tool-calling/LEARNINGS.md` |
| Source plugin error contract | raise `pydantic_ai.ModelRetry("reason")` for graceful degradation; plain exceptions for hard failures | `experiments/02-pydantic-ai-tool-calling/LEARNINGS.md` (to be reflected in `ARCHITECTURE.md` + `PLUGINS.md`) |
| Parallel tool calls | one `ModelResponse` can carry multiple `ToolCallPart`s, executed in parallel by the framework | `experiments/02-pydantic-ai-tool-calling/LEARNINGS.md` |
| Structured output mode | Tool Output (Pydantic AI default) — schema → synthetic `final_result` tool | `experiments/03-pydantic-ai-structured-output/LEARNINGS.md` |
| Gemini caveat for structured output | Gemini can't combine tools + structured output; provider wrapper must auto-select `NativeOutput` mode if Gemini is ever used for the judge | `experiments/03-pydantic-ai-structured-output/LEARNINGS.md` |
| Judge schema (v0) | `relevance: int(0-10)`, `seminality: int(0-10)`, `accept: bool`, `snowball_candidate: bool`, `reasoning: str`, `concerns: list[str]` | `experiments/03-pydantic-ai-structured-output/run.py` (refinement pending in M2/M3) |
| Default workhorse judge model | `openrouter:anthropic/claude-sonnet-4.6` | `experiments/04-pydantic-ai-provider-swap/LEARNINGS.md` |
| Cheap-mode judge alternative | `openrouter:meta-llama/llama-3.3-70b-instruct` (open weights, slightly more conservative scores) | `experiments/04-pydantic-ai-provider-swap/LEARNINGS.md` |
| Gemini structured-output caveat | softened — works in practice with default Tool Output mode for Gemini 2.5 Pro; only special-case if real failures observed | `experiments/04-pydantic-ai-provider-swap/LEARNINGS.md` |
