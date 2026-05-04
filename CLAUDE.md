# Callimachus — coding guide for Claude

This file is your standing brief when working on Callimachus. Read once per session.

## What we're building

Callimachus: an open-source autonomous librarian that builds, grows, and queries deep research libraries. Personal-Library-of-Alexandria model. Full picture in `README.md` and `docs/`. Build phased in `docs/DEV_PLAN.md`.

## The golden rule

**Docs and code stay in sync.** When code behaviour changes, update the doc that owns that behaviour *in the same change*:

- User-facing experience change → `docs/USER_STORIES.md`
- Architectural / structural change → `docs/ARCHITECTURE.md`
- Plugin contract change → `docs/PLUGINS.md`
- Build process / phasing change → `docs/DEV_PLAN.md`
- Anything an experiment teaches → the experiment's local `LEARNINGS.md` + an entry in top-level `LEARNINGS.md` if broadly relevant + `experiments/README.md` index update

If you don't know which doc owns what you're changing, ask before writing code.

## Type safety

Python's TS equivalents:

| Python | TypeScript | Role |
| --- | --- | --- |
| `pyright` | `tsc` | Static type checker. Run `uv run pyright`. Configured strict in `pyproject.toml`. |
| `ruff` | `ESLint` + `Prettier` | Lint + format. **Does not check types.** Run `uv run ruff check && uv run ruff format`. |
| `Pydantic` | `zod` (closest) | Runtime validation of data crossing system boundaries. |

Rules:
- Type everything. `from __future__ import annotations` at the top of every module.
- Modern syntax: `X | None` (not `Optional[X]`), `list[X]` (not `List[X]`), `dict[K, V]` (not `Dict[K, V]`).
- **Pydantic for boundaries** — anything coming in from LLMs, APIs, config files, user input, plugin contracts. `SQLModel` for DB rows. `FastMCP` tools auto-derive schemas from Pydantic.
- **Plain typed dataclasses or pyright-checked types for internals** — don't reach for Pydantic when data only flows between two of your own functions.

If pyright is unhappy, fix the types — don't `# type: ignore`. The only acceptable ignore is for a documented third-party stub gap, with a comment.

## Code style

- **DRY but not religious.** Three similar lines beats a premature abstraction. Two implementations before extracting a base class.
- **Small, focused modules.** Aim < 300 lines per file. Split when it wants to split.
- **Async by default for I/O.** Sync for pure computation.
- **No comments explaining what code does** — let names do that. Comments explain *why* — non-obvious constraints, subtle invariants, workarounds for specific bugs.
- **No trailing-summary blocks** ("now we save the result").
- **No `print` in committed code.** Use `logging` (or a stream the TUI consumes).
- **Errors explicit.** Raise typed exceptions; don't swallow. Validate at boundaries, trust internals.

## Testing

- **Tests where they earn their keep, not TDD-doctrinaire.**
- **Test:** pure-logic functions (parsers, scorers, schedulers, snowball convergence), plugin contract conformance, schema migrations, anything wiring to external APIs (mock the API, test the wiring), regressions when we fix bugs.
- **Don't test:** trivial property accessors, glue code between two well-tested libraries, prototypes (those have evidence in `experiments/*/LEARNINGS.md`).
- **LLM tests** mock responses by default. Real-LLM tests are gated by `pytest -m live` and excluded from default CI.
- `tests/` mirrors `src/callimachus/` directory structure.
- Use `pytest` + `pytest-asyncio`.

## Experiments vs production code

- `experiments/` — exploratory, prove-it-works code. Stdlib + minimal deps. Self-contained per directory. Lives forever as evidence.
- `src/callimachus/` — production code. Strict types, tested, documented.
- An experiment can promote a *pattern* into `src/`, but copy the intent, not the code. Production code uses the right abstractions, not the quick ones.

## Workflow rules

1. **Before writing code**: identify which DEV_PLAN milestone or experiment this belongs to. If neither, propose adding it before doing the work.
2. **Before changing behaviour**: identify the doc that owns it; plan to update in the same change.
3. **After completing an experiment**: write the local `LEARNINGS.md`, update `experiments/README.md` index, add to top-level `LEARNINGS.md` if broadly relevant.
4. **After completing a milestone**: review against `DEV_PLAN.md`, update if scope shifted, demo the slice.
5. **For risky / hard-to-reverse actions** (anything touching git history, external state, deletes): confirm with user first.

## Things to avoid

- Backwards-compatibility shims for code that hasn't shipped
- Feature flags for code with one path
- Defensive validation at internal boundaries (validate at system edges only)
- Building "for v2" — `DEV_PLAN`'s out-of-scope list is what we're not doing
- Premature plugin extraction (don't make something a plugin until we have two implementations or a clear external need)
- Dependencies that aren't pulling weight (every `uv add` is a maintenance commitment)
- Fancy abstractions before two real users exist

## Communication style

- Brief status updates: what changed, what's next, blockers. Skip narration.
- For decisions: lay out options + recommendation, don't just write code.
- For ambiguity: ask before guessing.
- For open questions: surface them in `DEV_PLAN.md`'s decisions table or in the relevant doc — don't bury them.

## Bash / tooling specifics

- Package manager is **`uv`**. Don't use raw `pip`.
- Run things via `uv run <tool>` rather than activating the venv.
- Common one-liners:
  - `uv sync --group dev` — install everything including dev deps
  - `uv run pytest` — run tests
  - `uv run ruff check && uv run ruff format --check` — lint
  - `uv run pyright` — type check
  - `uv run pre-commit run --all-files` — full hygiene pass
