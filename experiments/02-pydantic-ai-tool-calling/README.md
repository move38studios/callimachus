# 02 — pydantic-ai-tool-calling

Single agent + single tool. The model decides to call a Python function, the function runs, the result feeds back, the model produces a final answer.

This is the loop every hunter, the orchestrator, the judge, and the librarian will be built on. We need to see its exact shape.

## What we're testing

- Tool declaration syntax (decorators, type hints, docstrings)
- Whether the model reliably chooses to call the tool when prompted
- The message history structure across the request → tool_call → tool_result → response cycle
- Token usage and request count — proves the tool loop actually happened
- That tool args are validated against the type hints (no manual schema writing)

## The tool

`get_current_weather(city: str) -> str` returns a stub for a few cities, "unavailable" otherwise. The system prompt instructs the agent never to invent weather data — always call the tool.

## Run

```bash
uv run experiments/02-pydantic-ai-tool-calling/run.py
# or with a custom prompt:
uv run experiments/02-pydantic-ai-tool-calling/run.py "Compare the weather in Paris and Tokyo."
```

## Success criteria

- Exit code 0
- Tool is called at least once (visible in the tool-call log)
- Final response incorporates the tool's return value (not invented data)
- `usage.requests > 1` (proving the tool round-trip happened)
- Message history is inspectable: we see request → tool call → tool result → final response
