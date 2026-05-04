# 02 — pydantic-ai-tool-calling — LEARNINGS

## Run log

- **2026-05-04**, macOS, `openrouter:anthropic/claude-sonnet-4.6`.
  - `run.py` "What's the weather in Paris?" → tool called once, response uses real tool data. 2 requests, 1500 tokens.
  - `run.py` "Compare Paris and Tokyo" → **parallel tool calls in a single turn**, both results returned together. 2 requests, 1771 tokens.
  - `run_error.py` with `raise RuntimeError(...)` → exception **propagates to caller**, agent never sees it.
  - `run_error.py` with `raise ModelRetry(...)` → agent **sees the error as a `RetryPromptPart`**, recovers gracefully, gives a useful response to the user.

## Findings

### Tool declaration

- Use `@agent.tool_plain` for context-free tools (just args in, value out).
- Use `@agent.tool` when you need `RunContext` (deps injection, retries, parent-state access). We'll need this for hunter tools that read library state.
- Pydantic AI auto-derives the JSON schema from **type hints + docstring**. The docstring's `Args:` section becomes the parameter descriptions the model sees. So clear docstrings are not optional — they're the model's interface.

### Message exchange shape

```
ModelRequest (system + user)
ModelResponse (one or more ToolCallParts)
ModelRequest (one ToolReturnPart per call)
ModelResponse (TextPart with the final answer)
```

- One `ModelResponse` can contain **multiple `ToolCallPart`s** — the model issues parallel calls in a single turn.
- The framework executes them, gathers results, and sends them back together as one `ModelRequest` with multiple `ToolReturnPart`s. That's a single round-trip, not N.
- `result.all_messages()` exposes the full history for inspection — useful for the TUI (we'll render this live).

### Tool args format

- Args appear in `ToolCallPart` as a **JSON string** (`args='{"city": "Paris"}'`) plus a `tool_call_id`. The framework parses + validates against the type hints before invoking the Python function — we don't deal with raw JSON in the tool body.

### Error handling — important architectural choice

| Tool raises | Behaviour |
| --- | --- |
| `Exception` (any normal exception) | Propagates to the caller of `agent.run()`. The model never sees it. |
| `pydantic_ai.ModelRetry("...")` | Caught by the framework, fed back to the model as a `RetryPromptPart`. The model can retry, choose a different tool, or explain the failure to the user. |

This is the lever for graceful vs hard failure. **Architectural decisions this binds**:

- **Source plugins** (Exa, OpenAlex, Semantic Scholar, etc.) should wrap exceptions and `raise ModelRetry(reason)` so a hunter can degrade gracefully — one source down doesn't kill the run.
- **Internal failures** (DB unreachable, schema invariant violated, judge crash) should `raise` normally — hard fail, surface to the user, don't pretend the model can handle it.

### OpenRouter provider routing

Across the runs we saw `tool_call_id` prefixes from three different Anthropic backends:
- `toolu_*` — Anthropic direct
- `toolu_vrtx_*` — Vertex AI
- `toolu_bdrk_*` — Bedrock

OpenRouter routes between them transparently based on availability. **Don't assume the prefix shape** if we ever need to inspect call IDs.

### Token cost of tool calling

- Adding one tool with a one-line schema added ~1400 tokens to the input on a small prompt (29 tokens straight chat → 1422 tokens with one tool).
- The bulk is tool schema + system prompt overhead, fixed per request.
- Implication: don't over-attach tools. Each agent should expose only the tools it actually needs. The orchestrator and hunters should have minimal, focused toolboxes.

## Decisions

- **Tool schema = type hints + docstring**. Treat docstrings as the model's interface; review them like prompts.
- **`tool_plain` for stateless tools, `tool` (with `RunContext`) for stateful ones.** Hunter source-search tools are stateless → `tool_plain`. Tools that read library state will be `tool`.
- **Source plugins use `ModelRetry`** so hunters degrade gracefully on source outages.
- **Judge / orchestrator failures propagate** — we want loud crashes for genuine bugs.
- **Keep per-agent tool counts minimal**. Each tool costs ~tokens on every request to that agent.
- **Parallel tool calls work natively** — the orchestrator can fan out to N hunter tools in one turn. We don't need separate `asyncio.gather` for this case (though we'll still need it for fully independent agents).

## Open questions

- Tool result size limits — what happens with very large tool returns (e.g. an OpenAlex search returning 50 papers)?
- How does Pydantic AI surface streamed tool execution (does the framework let us stream tool progress to a TUI)? — experiment 05.
- Cost-of-schema scaling: at what tool count do we start crowding the context window meaningfully? — care about this for the orchestrator.
- Best practice for testing tool behaviour without LLM round-trips (mock the model, assert tool was called with right args).
