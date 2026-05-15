# Onboarding

You just joined the project. This doc gets you from zero to "I just shipped a small change" in about a day.

## What this project is

[`README.md`](../README.md) has the pitch. Two-line version: Callimachus is an autonomous research librarian. You give it a topic, it builds you a deep, curated, queryable library on disk. The chat layer that lets you *talk* to your library is the next big milestone.

## Where we are right now

[`docs/DEV_PLAN.md`](DEV_PLAN.md) — top section has a status snapshot.

In one sentence: M1 (deterministic ingest pipeline) and M2 (topic → library with HITL ceremony) are done; M3 (chat with the library) is next.

## Reading order — your first hour

1. [`README.md`](../README.md) — overview, install, what works today, mental model
2. **This file** — onboarding
3. [`docs/STATUS.md`](STATUS.md) is *not* a separate file — the status snapshot lives at the top of [`docs/DEV_PLAN.md`](DEV_PLAN.md). Read that section.
4. [`docs/USER_STORIES.md`](USER_STORIES.md) — the experiences we're building toward, with ✅/🔜/🟦 status per story so you know what's real vs aspirational
5. [`CLAUDE.md`](../CLAUDE.md) — the standing brief for AI coding sessions. Doubles as a coding-conventions doc.

That's enough to start contributing. The other docs ([`ARCHITECTURE.md`](ARCHITECTURE.md), [`PLUGINS.md`](PLUGINS.md), [`LEARNINGS.md`](../LEARNINGS.md)) are reference — read them when you need to.

## Set up your environment

```bash
git clone https://github.com/move38studios/callimachus
cd callimachus

# Python 3.11+ and uv (https://github.com/astral-sh/uv)
uv sync
uv run pre-commit install

# Copy the env template and add your keys
cp .env.example .env
# Edit .env: at minimum OPENROUTER_API_KEY. Optional: SERPER_API_KEY,
# MISTRAL_API_KEY, OPENALEX_MAILTO, UNPAYWALL_EMAIL.
```

## Verify the install

```bash
# Unit tests — fast, no network, must all pass
uv run pytest

# Type check — strict pyright config
uv run pyright

# Lint — ruff
uv run ruff check
```

If any of those fail on a clean clone, that's the bug — fix it first.

## Run the product end-to-end (~10 minutes)

```bash
# Use a tmp library so you don't pollute ~/Callimachus
export CALLIMACHUS_LIBRARY=/tmp/calli-onboard

uv run calli init
uv run calli build --topic "graph neural networks" --auto
# Watch the streaming output: scout angles, hunters firing, judge filtering,
# papers downloaded + extracted + indexed.

uv run calli list
uv run calli query "message passing"
```

When it's done you'll have ~10-15 papers indexed in `/tmp/calli-onboard/works/` with summaries, embeddings, and judge reasoning. That's the M2 deliverable — the topic→library half of the product.

Cleanup: `rm -rf /tmp/calli-onboard`.

## Codebase tour

```
src/callimachus/
  cli.py                  # Typer entry point. Start here for any CLI work.
  llm.py                  # Per-role model defaults (FAST/SMART/DEEP).
  storage/                # SQLModel + sqlite-vec + Alembic migrations.
  sources/                # Plugin contracts + bundled discovery sources & resolvers.
    protocols.py          # The DiscoverySource / Resolver / CitationGraph Protocols.
    registry.py           # Loads entry-point + local-file plugins.
    bundled/              # arxiv, openalex, serper, perplexity, unpaywall, local_pdfs.
  pipeline/               # Deterministic per-paper ingest stages.
    download / extract / enrich / chunk / embed / index / ingest.py
    ocr/                  # OCR provider abstraction (Mistral default).
  discovery/              # M2: topic → library.
    plan.py               # Plan + AngleTree models + YAML I/O.
    scout.py              # LLM hypothesis + parallel OpenAlex probe.
    ceremony.py           # HITL Q&A → Plan.
    judge.py              # Single-shot Verdict per candidate.
    hunter.py             # Pydantic AI sub-agent per angle.
    orchestrator.py       # Plan → run hunters → judge → ingest.

experiments/              # Exploratory probes, kept as evidence.
  NN-name/
    README.md             # what we're testing
    run.py                # the probe
    LEARNINGS.md          # what we found

tests/                    # Mirrors src/. ~360 unit + ~12 live tests.
docs/                     # You are here.
```

## Three rules that will save you time

1. **Look in `experiments/` before building anything new.** Most non-obvious choices were validated in a small probe with a `LEARNINGS.md` capturing what we found. The `experiments/README.md` is the index.

2. **Live tests are gated behind `pytest -m live`.** Default `pytest` runs hit no network. If you need to verify something talks to a real API, write a `@pytest.mark.live` test and run it explicitly: `uv run pytest -m live`.

3. **Docs and code stay in sync.** [`CLAUDE.md`](../CLAUDE.md) lists which doc owns which kind of change. If you change behavior, update the owning doc in the same commit. We hate doc drift more than we hate bikeshedding doc structure.

## Tooling and preferences in a nutshell

### Package management — `uv`

We use [`uv`](https://github.com/astral-sh/uv) for everything: install, lockfile, virtualenv, running scripts. Forget about `pip`, `pip-tools`, `poetry`, `venv`, `conda`. The patterns you'll use:

```bash
uv sync                         # install/update everything from uv.lock
uv sync --group dev             # include dev dependencies (already default)
uv add some-package             # add a runtime dep (updates pyproject.toml + uv.lock)
uv add --dev some-package       # add a dev-only dep
uv remove some-package          # remove
uv run <command>                # run a command in the project venv (no `source .venv/bin/activate` needed)
uv run pytest                   # tests
uv run pyright                  # type check
uv run ruff check               # lint
uv run pre-commit run --all-files   # full hygiene pass
```

You *can* `source .venv/bin/activate` if you prefer typing `pytest` over `uv run pytest`. Either works.

`uv.lock` is committed. Don't edit it by hand. `uv add` regenerates it.

### Type checking — strict pyright

Strict mode. `pyright` runs in CI and pre-commit. Run it locally with `uv run pyright`.

What that means in practice:

- **Annotate every function signature.** Return types too. Pyright will yell otherwise.
- **No bare `Any`** — if you genuinely need to escape the type system (e.g. JSON parsing, Pydantic AI internals), `cast("dict[str, Any]", x)` and document why.
- **No `# type: ignore`** without a `[reportXxx]` reason and a comment explaining the third-party stub gap. If a Pydantic AI overload doesn't match, add `# pyright: ignore[reportCallIssue]` and one line of context.
- **`from __future__ import annotations`** at the top of every module — defers annotation evaluation, lets you use `X | None` everywhere without 3.10+ runtime baggage in some paths.
- **Modern syntax**: `X | None` (not `Optional[X]`), `list[X]` (not `List[X]`), `dict[K, V]` (not `Dict[K, V]`). PEP 585 + 604.

### Linting + formatting — `ruff`

Ruff replaces flake8, isort, black, pyupgrade, and several others. Configured in `pyproject.toml`. Two commands:

```bash
uv run ruff check               # lint, with --fix to auto-fix what's safe
uv run ruff format              # format (we use ruff-format, the black-replacement)
```

The pre-commit hook runs both. CI fails if either complains.

A few rule-specific gotchas:
- **`T20` (no print)** — `print()` in committed code is an error. Use `logging` or yield to the TUI/CLI display layer. Tests are exempt.
- **`I001` (import sorting)** — auto-fixed; don't fight it.
- **Line length** — 100 chars. Ruff format wraps automatically.
- **Trailing whitespace, EOF newlines, etc.** — pre-commit hook fixes them. If a hook fails on first commit, re-run; the auto-fix sticks.

### When to use Pydantic vs plain dataclass

A surprisingly common confusion. Rule of thumb:

| Use **Pydantic `BaseModel`** when… | Use **`@dataclass`** when… |
|---|---|
| Data crosses a system boundary (LLM I/O, plugin contract, API response, YAML config, user input) | Data only flows between two of your own functions |
| You want runtime validation + clear error messages | You don't need validation; you trust the producer |
| You want JSON Schema generation (e.g. for Pydantic AI `output_type`) | You're holding internal state |
| Serialization matters (`.model_dump()`, `.model_validate()`) | Serialization is irrelevant |

Concrete examples in our codebase:
- `Verdict`, `HunterReport`, `_ScoutHypothesis` — Pydantic (LLM-validated structured output)
- `WorkCandidate`, `ResolvedFile`, `Plan`, `AngleTree`, `Angle` — Pydantic (plugin/config boundaries, persisted to YAML)
- `Work`, `Run`, `Chunk`, `Collection` — `SQLModel` (Pydantic + SQLAlchemy)
- `HunterDeps`, `HunterRunResult`, `BuildResult`, `IngestResult`, `JudgedCandidate` — `@dataclass(slots=True)` (internal state passed between functions)

Don't reach for Pydantic to hold internal state — `@dataclass(slots=True)` is faster, simpler, no validation overhead. Don't use a dataclass at a boundary — you'll regret the missing validation the first time an LLM hallucinates a field.

### Testing — pragmatic, not doctrinaire

Configured in `pyproject.toml`: `pytest` + `pytest-asyncio`. `tests/` mirrors `src/callimachus/` directory structure.

```bash
uv run pytest                   # default: unit tests, no network, ~1s for the full suite
uv run pytest tests/sources/test_arxiv.py    # one file
uv run pytest -k arxiv          # by name
uv run pytest -m live           # live tests only (real APIs, needs keys, ~30s)
uv run pytest -v                # verbose
```

**What we test:**
- Pure-logic functions (parsers, scorers, slugify, regexes)
- Plugin contract conformance — does `MyPlugin` actually satisfy the `DiscoverySource` Protocol?
- Anything wiring to external APIs — mock the API with `httpx.MockTransport`, test our wiring
- Schema migrations
- **Regressions when we fix bugs** — every bug-fix commit adds a test that locks in the fix

**What we don't test:**
- Trivial property accessors
- Glue code between two well-tested libraries (e.g. "this function calls `httpx.get` and returns the result")
- Prototypes — those have `experiments/NN/LEARNINGS.md` as their evidence trail instead

**Mock or live?**
- Default tests **mock the network**. They run fast, deterministic, no API key needed. Use `httpx.MockTransport` for HTTP plugins, `pydantic_ai.models.test.TestModel` for LLM agents, in-memory SQLite (via `make_engine`) for storage tests.
- Live tests are gated behind `@pytest.mark.live`. They hit real APIs and need real keys. CI excludes them by default. Run them locally before merging anything that touches a plugin or an LLM call: `uv run pytest -m live`.

A typical plugin gets ~10-20 unit tests + 1-2 live smoke tests.

### Async by default for I/O

Anything that does network I/O or disk I/O is `async def`. We use `asyncio.run()` at the CLI boundary; everything inside is `await`-able. Pure computation stays sync.

`asyncio.to_thread(blocking_fn, ...)` for libraries that don't have async APIs (e.g. the Mistral SDK).

### Comments — comment *why*, not *what*

Almost no comments in our code. `judge_score` doesn't need a comment that says "the judge's score." Names do that.

What does need a comment:
- Hidden constraints — "OpenAlex polite-pool requires the email in the URL not just the header"
- Workarounds — "Mistral SDK 2.x rejects io.BytesIO even though it's nominally an IO subclass"
- Surprising invariants — "must be called BEFORE session.flush() because of the FK ordering quirk in SQLAlchemy 2"
- "Why didn't you just use X" — when the obvious approach is wrong, head it off

The test for whether to comment: would a smart reader, six months from now, read the line and think "huh"? If yes, comment.

### Docs and code stay in sync

[`CLAUDE.md`](../CLAUDE.md) lists which doc owns which kind of change:
- User-facing UX → [`docs/USER_STORIES.md`](USER_STORIES.md)
- Architecture → [`docs/ARCHITECTURE.md`](ARCHITECTURE.md)
- Plugin contract → [`docs/PLUGINS.md`](PLUGINS.md)
- Milestones / phasing → [`docs/DEV_PLAN.md`](DEV_PLAN.md)
- Cross-cutting findings from experiments → [`LEARNINGS.md`](../LEARNINGS.md) + the experiment's local LEARNINGS

If you change behaviour, update the owning doc *in the same PR*. Doc drift is the bug we hate most.

## LLM-specific concepts you'll need

If you've worked with LLM APIs before, skim. If you haven't, this is the orientation that'll save you time.

### Pydantic AI is our agent framework

We use [Pydantic AI](https://ai.pydantic.dev) (same author as Pydantic). It's the layer between our code and the LLM provider. Mental model:

- **Provider** — OpenRouter, Anthropic-direct, OpenAI-direct, etc. We default to OpenRouter (one API key, many models). Configured via `OPENROUTER_API_KEY` env var; the model string is `"openrouter:anthropic/claude-sonnet-4.6"` style.
- **Agent** — `Agent(model, deps_type=…, output_type=…, system_prompt=…)`. An agent is a thin wrapper around an LLM that knows about tools, structured output, and retries. You call `await agent.run(prompt, deps=…)` and get a `result.output` (typed as `output_type`).
- **Tool** — a Python function the agent can call. `@agent.tool` (with `RunContext` for accessing `deps`) or `@agent.tool_plain` (no context). Tools are async, return JSON-serializable results, and the framework automatically generates a JSON Schema from your type hints + docstring.
- **Structured output** — set `output_type=SomeModel` (a Pydantic BaseModel) and the agent will be forced to return validated JSON matching that schema. This is how our `Verdict`, `HunterReport`, `_ScoutHypothesis` work.
- **`ModelRetry`** — raise this from a tool when the call failed in a recoverable way (rate limit, transient outage). The agent sees a retry signal in its history and can adjust its next move. We translate plugin `SourceUnavailable` → `ModelRetry` at the agent boundary.
- **`UsageLimits`** — pass `usage_limits=UsageLimits(request_limit=20)` to bound how many requests an agent run can make before raising `UsageLimitExceeded`. We use this on hunters to catch runaway loops.
- **`TestModel` / `FunctionModel`** — `from pydantic_ai.models.test import TestModel` lets tests run an agent without hitting any network, by feeding canned tool calls and outputs. We use this throughout the test suite.

Read this in order if it's new:
- [Pydantic AI `Agent` docs](https://ai.pydantic.dev/agents/) — the core abstraction
- [Tools docs](https://ai.pydantic.dev/tools/) — how the LLM calls Python functions
- [Structured outputs](https://ai.pydantic.dev/output/) — Pydantic models as agent output
- Then `experiments/01-pydantic-ai-hello/` through `experiments/06-pydantic-ai-sub-agents/` — six small probes we did when learning it. The `LEARNINGS.md` in each captures the gotchas.

### Per-role models

`src/callimachus/llm.py` has three constants:

- `MODEL_FAST` = Haiku 4.5 — angle generation, classification, anything one-shot
- `MODEL_SMART` = Sonnet 4.6 — judgment calls, query strategy, enrichment
- `MODEL_DEEP` = Opus 4.7 — end-of-build synthesis (not used yet, reserved for M4)

When in doubt, default to `MODEL_SMART`. Haiku is fine for things where the worst case is "the LLM is a bit dumb." Sonnet is for things where being dumb costs you papers or tokens.

### Why we don't use the Anthropic SDK directly

Pydantic AI gives us provider portability, structured outputs, agent + sub-agent primitives, and `TestModel` for free. The Anthropic SDK would force us to roll our own retry/structured-output/test infrastructure and lock us to one provider. The cost is a thin abstraction layer; the benefit is a tested agent framework you don't have to maintain.

### What "embedding" means in our pipeline

We chunk papers into ~2000-char passages, run each chunk through `nomic-embed-text-v1.5` (a local sentence-transformer model, no API key, ~500MB), and store the resulting 768-dimensional vectors in a `vec_chunks` virtual table via [`sqlite-vec`](https://github.com/asg017/sqlite-vec). Vector search is `SELECT … WHERE embedding MATCH ? AND k = 20`.

You don't need to understand sentence-transformers internals; treat the embedder as `embed_documents(list[str]) -> list[list[float]]` and you're fine. If you want to swap to an API embedder (Voyage, OpenAI), implement the `Embedder` Protocol in `src/callimachus/pipeline/embed.py`.

### What "OCR" means in our pipeline

When we ingest a PDF (no LaTeX source available), we send it to Mistral's `mistral-ocr-latest` model via their SDK. It returns markdown + per-page images. The `OcrProvider` Protocol lets you swap in a different provider; today only `MistralOcr` is implemented.

### Cost intuition (rough)

Per build (~15 ingested papers):
- Hunter LLM (Sonnet 4.6, ~80k tokens total across 8 angles): ~$1
- Judge LLM (Sonnet 4.6, ~500 candidates × small prompt): ~$5–10
- Enricher LLM (Sonnet 4.6, one call per ingested paper, full text): ~$3–5
- Mistral OCR (only when LaTeX unavailable): ~$0.20 per build typical
- Embeddings: free (local)
- Discovery API calls (OpenAlex, Serper, Perplexity): pennies

Total: ~$10–20 per build. Untracked currently; this is from-the-back-of-an-envelope. Worth instrumenting before users complain.

## What to work on first

Look at [`docs/DEV_PLAN.md`](DEV_PLAN.md) — M3 is the next milestone (chat with your library). M3.0 (Librarian agent + read tools) is the natural starting point.

For a smaller first PR, browse the open Issues on GitHub. Fixing a typo in docs, a small CLI ergonomics improvement, or a missing test for an existing feature are all good first contributions.

## Two failure modes to know about

When you run real builds, you'll hit these — they're handled gracefully but worth understanding:

1. **Publisher 403s on PDF fetch.** ACM, Elsevier, MDPI sometimes block scrapers. We send a browser-like User-Agent for the PDF fetch step which helps but isn't bulletproof. Failed candidates fall through to the next try-more candidate; the build keeps going.
2. **Rate limits on arxiv.** arxiv enforces 1 req/3s. Hunters share an arxiv plugin instance with a rate-limit lock, so they cooperate. If you see a hunt stage take 30+ seconds, that's why — it's polite, not stuck.

## Asking for help

- For architecture / "why is it this way" questions: read the relevant `experiments/NN/LEARNINGS.md` first. We document why-decisions there.
- For "how does this work in code" questions: pyright + grep are your friends. The codebase is small (~5000 lines of `src/`).
- For project-direction questions: open a GitHub Discussion or DM the maintainer.

Welcome aboard.
