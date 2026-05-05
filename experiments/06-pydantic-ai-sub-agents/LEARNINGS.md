# 06 — pydantic-ai-sub-agents — LEARNINGS

## Run log

- **2026-05-05**, macOS, `openrouter:anthropic/claude-haiku-4.5`.
- First attempt: hit `request_limit=50` even after raising it. Hunter was doing 9 requests; couldn't see why without diagnostics.
- Iterated: added Rich logging via `_common.py`, switched to Haiku 4.5, tightened hunter prompt, added per-call `request_limit=15` + `ModelRetry` conversion for sub-agent failures.
- Final run: all three demos succeeded.

## Findings

### Sub-agent delegation works cleanly

The `@orchestrator.tool` pattern wrapping `hunter.run(brief)` works exactly as Pydantic AI documents it. The orchestrator agent issues a `spawn_hunter` tool call, the framework executes our async function, the function runs a fresh sub-agent, returns its structured output, and the orchestrator continues with that result. No surprises.

### Parallel tool calls execute truly in parallel

Demo A: orchestrator emitted **4 parallel `spawn_hunter` ToolCallParts** in a single `ModelResponse` (the parallel-tool-call pattern from experiment 02). The framework executed all 4 hunters concurrently. We saw all 4 spawn log lines fire ~simultaneously (within 50ms), then completion log lines arrive in finish order over ~25 seconds. The orchestrator waited for all of them before emitting its synthesis.

Demo B: `asyncio.gather` over 4 independent `hunter.run()` calls — total elapsed 12.9s = slowest hunter time. True parallelism confirmed.

**Implication for production**: the orchestrator can fan out N hunters in one model turn and get them all back in one round-trip from its perspective (1 dispatch request + 1 synthesis request = 2 orchestrator requests). For Callimachus's discovery phase this means we can spawn the planning-determined number of hunters and synthesize, with the orchestrator's own token cost staying tiny.

### Per-agent budgets are independent (when usage isn't shared)

Earlier confusion: when the parent passed `usage=ctx.usage` to a sub-agent, the sub-agent's requests counted against the parent's `request_limit`. That made the orchestrator hit limits unrelated to its own activity.

Fix: don't share `usage`. Each `hunter.run()` gets its own usage tracker and its own `usage_limits=UsageLimits(request_limit=15)`. The parent orchestrator has its own separate budget (30 in this experiment).

The framework still tracks total usage at higher levels for cost reporting; we just decoupled limit enforcement.

### Hunter request count is variable (2–10) — depends on prompt + corpus shape

Across runs we saw hunters using anywhere from 2 to 10 requests. Behavior:
- Hunter calls `search_papers` once, gets results
- If results look complete, calls `final_result` (the synthetic structured-output tool) → 2 requests total
- If results look thin or off-target, calls `search_papers` again with different keywords → 3+ requests
- Eventually settles and calls `final_result`

Our stub corpus has only 2-4 papers per category, so hunters often searched multiple times trying to find more. In production with real OpenAlex/Semantic Scholar searches returning dozens of hits per query, hunters should converge faster.

**Reasonable bound**: cap hunters at `request_limit=15-20` in production. Higher than the 8-request initial guess. Loops above that would be a real problem.

### `ModelRetry` is the right way to handle sub-agent failures

When a hunter's `hunter.run()` raises (e.g. hits its request limit), the exception propagates out of the `@orchestrator.tool` function. By default this crashes the orchestrator's whole run.

Fix (per experiment 02 LEARNINGS): catch `UsageLimitExceeded` (and any other recoverable failure) in the spawn_hunter wrapper and re-raise as `pydantic_ai.ModelRetry("...")`. The orchestrator sees this as a `RetryPromptPart` and can:
- Try a different angle
- Skip this angle and continue with the others
- Note the failure in synthesis

This is the production pattern. Same convention applies to source-plugin failures (Exa down, Semantic Scholar rate-limited): wrap in `ModelRetry` so the orchestrator stays alive.

### Haiku 4.5 cost / speed for sub-agent work

| Operation | Haiku 4.5 (this experiment) |
| --- | --- |
| Single hunter | ~6–13s, ~3–11k tokens, 2–7 requests |
| Orchestrator + 4 parallel hunters + synthesis | ~38s, ~50k tokens, ~25 requests total |
| Parallel `asyncio.gather` of 4 hunters | ~13s, ~17k tokens, ~12 requests |

At Haiku pricing this run cost ~$0.10. For the discovery phase of a real library build (orchestrator + many hunters across many snowball iterations), Haiku is the right default for the orchestrator and hunters. Save Sonnet for the **judge** (where quality matters more) and Opus for the **synthesis pass** at the end.

### Logging via `_common.py` works well

Switching from ad-hoc `print` to `setup_logging()` + Rich gave us:
- Coloured, timestamped, structured output
- `log.info("[bold blue]hunter #%d spawn[/]", idx, ...)` markup
- `log.debug` calls quiet by default, surface on `verbose=True`
- Httpx/openai/anthropic noise muted automatically

The `experiments/_common.py` shared module is a small but real win across experiments. New experiments should use it.

### PEP 723 + sibling import works

Pattern that landed:

```python
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from _common import setup_logging, ...  # noqa: E402
```

Each experiment still declares its own dependencies via PEP 723, but can `from _common import ...` for env/logging boilerplate. Fragile-feeling but works reliably; documented in `experiments/README.md`.

## Decisions

- **Sub-agent pattern confirmed for production**: hunters as `@orchestrator.tool`s wrapping `hunter.run(brief)`. No `usage=ctx.usage` sharing. Each hunter gets its own `request_limit=15-20`.
- **Parallel hunter dispatch via the model**: orchestrator's prompt instructs "issue spawn calls in a SINGLE response" — the model handles concurrency for us via parallel ToolCallParts. We don't need `asyncio.gather` in the orchestrator path. (Demo B's `asyncio.gather` pattern is for cases where *we*, not the model, decide what to spawn — e.g. a fixed sweep at the start of discovery.)
- **`ModelRetry` for recoverable sub-agent failures**: catch `UsageLimitExceeded` and other transient failures, re-raise as `ModelRetry`. Apply uniformly to source plugins too.
- **Default models for discovery**: Haiku 4.5 for hunters and orchestrator; Sonnet 4.6 for the judge; Opus 4.7 for end-of-build synthesis.
- **Logging convention**: `experiments/_common.py` for env + Rich logging across all experiments. `src/callimachus/` will use the same pattern with a `--verbose` CLI flag (M1).

## Open questions

- In Demo A the orchestrator's synthesis took the form of well-structured prose with identified coverage gaps. Encouraging, but: how stable is this across runs and topics? Need real-corpus testing in M2/M3.
- Hunter variability (2-10 requests) suggests the model is doing legitimate exploration, not looping. But on real APIs with noisier results, would they converge or oscillate? Verify when discovery sources are wired up (experiments 17-22).
- `ModelRetry` from a sub-agent: how many retries does the orchestrator make before giving up? Need to test (set the angle to deliberately fail and see).
- For very long discovery runs (snowball loops), the orchestrator's own context will grow as hunter results accumulate. We may need explicit context compaction at some point. Defer to M3 when snowball is implemented.
