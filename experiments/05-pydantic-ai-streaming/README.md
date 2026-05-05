# 05 — pydantic-ai-streaming

Three streaming surfaces in Pydantic AI, each in its own runnable script so you can judge the live feel of each one separately. Foundation for the agentic-feel TUI.

## The three scripts

### `chat.py` — interactive streaming chat

Multi-turn REPL. Type a message, watch the response stream token-by-token. History is preserved across turns. Shows time-to-first-chunk and total elapsed per turn.

```bash
uv run experiments/05-pydantic-ai-streaming/chat.py
```

**Use case in the TUI**: the chat pane (`calli` chat with the librarian).

**Judge by feel**: does the response actually appear progressively, or does it batch-then-dump? Is the time-to-first-chunk acceptable for a chat experience?

### `nodes.py` — node-level introspection (`agent.iter()`)

> Note: file is named `nodes.py` rather than `inspect.py` because the latter would shadow Python's stdlib `inspect` module and break `asyncio`'s import chain. Lesson recorded in LEARNINGS.

Single prompt → prints each graph node as it completes, with timing. Each node represents a step in the agent's reasoning: user prompt, model request, tool call, model response, end.

```bash
uv run experiments/05-pydantic-ai-streaming/nodes.py
uv run experiments/05-pydantic-ai-streaming/nodes.py "Compare the weather in Paris and London."
```

**Use case in the TUI**: the orchestrator pane that shows what the agent is currently *doing* (planning, calling, judging).

**Judge by feel**: are the node attributes useful? Could you imagine rendering each one as a row in a TUI pane?

### `events.py` — high-level event stream (`run_stream_events()`)

Single prompt → fires events as they happen with millisecond-since-last timing. Token deltas, tool call starts, tool results, final result.

```bash
uv run experiments/05-pydantic-ai-streaming/events.py
uv run experiments/05-pydantic-ai-streaming/events.py "What's the weather in Tokyo?"
```

**Use case in the TUI**: the status bar (cost / token counts) and the live works list (papers added events).

**Judge by feel**: are the events granular enough to drive live UI updates without lag? Are the event types named in a way you can map to UI behaviours?

## What we're trying to learn

- Which streaming API is right for which TUI pane
- Whether token-streaming feels live (no buffering jank)
- Whether tool-call events fire in real time (not at the end)
- What event types exist that we'd subscribe to from Textual

## After you've tried them

I'll fill in `LEARNINGS.md` based on your judgment plus what the scripts surface.
