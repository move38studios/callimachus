# 05 — pydantic-ai-streaming — LEARNINGS

## Run log

- **2026-05-04**, macOS, `openrouter:anthropic/claude-sonnet-4.6`.
- All three streaming surfaces tested via separate scripts (`chat.py`, `nodes.py`, `events.py`).
- `chat.py` upgraded to the aider pattern (prompt_toolkit + Rich) — user judged the experience as "solid stuff".

## Findings

### The three streaming surfaces

| Surface | API | What it gives | TUI use case |
| --- | --- | --- | --- |
| Token text | `agent.run_stream() + stream_text(delta=True)` | Token-by-token delta strings | Chat pane (live "typing" output) |
| Node-level | `agent.iter()` | Each graph node as it completes (`UserPromptNode`, `ModelRequestNode`, `CallToolsNode`, `End`) | Orchestrator status pane (what is the agent currently doing) |
| High-level events | `agent.run_stream_events()` | Fine-grained events: `PartStartEvent`, `PartDeltaEvent`, `FunctionToolCallEvent`, `FunctionToolResultEvent`, `FinalResultEvent` | Status bar (cost, counts) and works-list updates |

All three streamed cleanly and felt live. No buffering jank.

### The chat experience (aider pattern: prompt_toolkit + Rich)

The `chat.py` upgrade — `prompt_toolkit` for input + `rich.live.Live` + `rich.markdown.Markdown` for streaming output — produced a chat experience the user judged solid:

- Streaming markdown rendering re-renders the live region as tokens arrive; the rendered markdown stays in scrollback after the response finishes (because `Live` defaults to non-transient)
- Native terminal scrollback is fully preserved — copy/paste, search, scroll all work
- `prompt_toolkit` gives multi-line buffer, history, slash-command completion, key bindings, `Ctrl+X Ctrl+E` editor escape, all out of the box
- Visual structure: Rich `Rule` between turns, distinct prompt styles ("you ▸" cyan, "calli ▸" magenta), per-turn token + latency line in dim text
- Slash commands implemented: `/help`, `/clear`, `/history`, `/save <path>`, `/exit`
- Cancel: Ctrl+C cancels a streaming response cleanly without exiting; twice in a row exits

This validates the aider-pattern recommendation. The experience is good enough to be the dominant chat interface without needing a full Textual app.

### Don't shadow stdlib module names

First version of the node-iteration script was named `inspect.py`. This crashed with a "circular import" error because `asyncio` internally imports the stdlib `inspect` module, and Python's import system found our local `inspect.py` first. **Lesson**: never name an experiment script after a stdlib module. Renamed to `nodes.py`. (Same caution for `random.py`, `json.py`, `email.py`, `time.py`, etc.)

### Shift+Enter is hard cross-terminal

The standard mechanism is the **CSI u keyboard protocol** — terminal sends `\x1b[13;2u` for Shift+Enter. Two ways to enable it:

1. **Application-side request**: send `\x1b[>1u` on startup to ask the terminal to enter disambiguation mode. Disable with `\x1b[<u` on exit. This is what Claude Code does to support Shift+Enter without the user touching their config.
2. **User-side terminal config**: enable "Report modifiers using CSI u" in iTerm2; modify `~/.config/zed/keymap.json` to map `shift-enter` to `["terminal::SendText", "[13;2u"]` in Zed; equivalent in VS Code, Cursor, Alacritty.

We tried (1) — it didn't activate in the user's Zed terminal in this session, even though Claude Code itself is making Shift+Enter work in the same terminal (Claude Code may also write keymap.json via its `/terminal-setup` command, or detect & escalate; we didn't reverse-engineer it fully).

**Decision for now**: ship Alt+Enter as the universal multi-line key (works in every terminal). Document Shift+Enter as terminal-dependent. If we later want first-class Shift+Enter, build a `calli setup-terminal` analogous to Claude Code's. Tracked as a future polish task — not blocking experiments 06+.

### prompt_toolkit's Keys enum is incomplete

prompt_toolkit 3.0.52 has `Keys.ShiftDelete`, `Keys.ShiftLeft`, `Keys.ShiftEscape`, etc. — but **no `Keys.ShiftEnter`**. The pattern for binding to unsupported escape sequences:

1. Pick an unused `Keys` value (we used `Keys.WindowsMouseEvent` since we're on macOS)
2. Map the raw escape sequence to it via `ANSI_SEQUENCES["\x1b[13;2u"] = Keys.WindowsMouseEvent`
3. Bind in `KeyBindings` with `@kb.add(Keys.WindowsMouseEvent)`

Hacky but contained. If we end up needing more custom keys, switch to `aenum` to extend the enum properly.

## Decisions

- **Chat interface = `prompt_toolkit` + `Rich`** (aider pattern). Inline scrolling, native scrollback preserved.
- **Build dashboard = Textual** (multi-pane, real-time hunters). Unchanged.
- **Architecture split is real**: chat is conversational, dashboard is spatial. `ARCHITECTURE.md` tech stack updated.
- **Multi-line input**: Alt+Enter universal; Shift+Enter is terminal-dependent and a future polish task.
- **`calli` chat will use the same shape as `experiments/05/chat.py`** — slash commands, persistent history, streaming markdown, cancel-and-resume.
- **Naming convention for experiments**: never use a stdlib module name (no `inspect.py`, `json.py`, `email.py`, etc.).

## Open questions

- Should we ship a `calli setup-terminal` to make Shift+Enter "just work" cross-terminal (Claude Code style)? Future polish, not blocking.
- Live rendering of long streaming markdown sometimes flickers on re-parse. Will McGugan documented an "only re-parse last block" optimization for Textual's Markdown widget. Worth porting to our Rich `Live` setup if flicker becomes an issue at scale.
- Do we eventually want a Toad-style Textual chat (panes for citations, works list, library state)? Defer until we've lived with the pt+Rich chat for a while and know whether the panes are worth losing scrollback.
- Should slash commands be defined declaratively in one place so the librarian agent (M4) can introspect them and answer "what can I do" questions?
