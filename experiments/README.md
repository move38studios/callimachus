# Experiments

Small, self-contained probes that prove a single piece of the stack works the way we think it does. Built in Phase 1 of the [development plan](../docs/DEV_PLAN.md), kept forever as evidence.

## Convention

Each experiment lives in its own numbered directory:

```
experiments/
  NN-short-name/
    README.md       # what we're testing, how to run, what success looks like
    run.py          # the experiment (or main.py, or whatever fits)
    LEARNINGS.md    # what we found, populated after running
    output/         # any artifacts produced (gitignored)
```

The numbering is loose — it reflects the order in `DEV_PLAN.md` but doesn't need to be strictly sequential. Skip a number if you abandon an experiment; that's fine.

## Rules

- **One thing per experiment.** If you're testing two things, make two experiments.
- **Self-contained.** An experiment should run with `cd experiments/NN-name && python run.py` (or `uv run python run.py` once we have a uv environment) without relying on `src/callimachus/` code. If you need a helper, copy it in.
- **Capture LEARNINGS as you go**, not after. Even rough notes are better than nothing.
- **Keep it small.** Aim for 1–3 hours per experiment. If it sprawls, split it.
- **Don't delete experiments.** They're the evidence trail. If an experiment is superseded, note it in the local LEARNINGS but leave the directory.

## Index

| # | Name | Status | Notes |
| --- | --- | --- | --- |
| 00 | env-check | done (2026-05-04) | Python 3.11+ confirmed, stdlib .env parser sufficient for experiments |
| 01 | pydantic-ai-hello | done (2026-05-04) | OpenRouter via Pydantic AI confirmed; `openrouter:anthropic/claude-sonnet-4.6` works |
| 02 | pydantic-ai-tool-calling | done (2026-05-04) | Single + parallel tool calls work; `ModelRetry` vs plain exceptions = graceful vs hard failure |
| 03 | pydantic-ai-structured-output | done (2026-05-04) | Tool Output mode (default) works rock-solid via OpenRouter; Gemini needs `NativeOutput` mode (caveat) |
| 04 | pydantic-ai-provider-swap | not started | |
| 05 | pydantic-ai-streaming | not started | |
| 06 | pydantic-ai-sub-agents | not started | |
| 07 | anthropic-prompt-caching | not started | |
| 08 | textual-hello | not started | |
| 09 | textual-stream-agent | not started | |
| 10 | textual-multi-pane | not started | |
| 11 | sqlite-vec-hello | not started | |
| 12 | sqlmodel-alembic | not started | |
| 13 | sqlmodel-vec-combined | not started | |
| 14 | embeddings-nomic-local | not started | |
| 15 | embeddings-voyage | not started | |
| 16 | embeddings-quality-bakeoff | not started | |
| 17 | source-openalex | not started | |
| 18 | source-semantic-scholar | not started | |
| 19 | source-arxiv-latex | not started | |
| 20 | source-crossref-unpaywall | not started | |
| 21 | source-exa | not started | |
| 22 | source-perplexity | not started | |
| 23 | extract-latex-to-md | not started | |
| 24 | extract-mistral-ocr | not started | |
| 25 | extract-claude-vision | not started | |
| 26 | enrich-llm-call | not started | |
| 27 | chunking-bakeoff | not started | |
| 28 | mcp-fastmcp-hello | not started | |
| 29 | plugin-entry-point | not started | |
| 30 | plugin-local-file | not started | |
