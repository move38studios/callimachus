# Learnings

The cumulative log of what we discover while building Callimachus. Each component experiment in `experiments/` has its own `LEARNINGS.md` with the full detail; this top-level file collects the highlights, surprises, and decisions that bind future work.

The convention: when an experiment surfaces something that future-you (or a future contributor) needs to know — a gotcha, a non-obvious choice, a default we landed on — note it in the experiment's local LEARNINGS, and if it's broadly relevant, summarise it here in one or two sentences with a link.

## How to read this file

Entries are ordered newest-first. Each entry is short. If you need depth, follow the link to the experiment's local LEARNINGS or the relevant doc.

## Entries

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
