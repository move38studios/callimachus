# /// script
# requires-python = ">=3.11"
# dependencies = [
#   "pydantic-ai-slim[openrouter]>=0.0.20",
#   "prompt_toolkit>=3.0",
#   "rich>=13",
# ]
# ///
"""Chat with Callimachus — the aider pattern (prompt_toolkit input + Rich output).

Inline scrolling, native terminal scrollback preserved, streaming markdown,
slash commands, persistent history.

  uv run experiments/05-pydantic-ai-streaming/chat.py

Slash commands: /help /clear /history /save <path> /exit
Keyboard: Enter submits, Up/Down recalls history, Ctrl+C cancels response,
Ctrl+D exits, Ctrl+X Ctrl+E opens $EDITOR for multi-line input.
"""

from __future__ import annotations

import asyncio
import os
import sys
import time
from pathlib import Path

from prompt_toolkit import PromptSession
from prompt_toolkit.completion import WordCompleter
from prompt_toolkit.formatted_text import FormattedText
from prompt_toolkit.history import FileHistory
from prompt_toolkit.input.ansi_escape_sequences import ANSI_SEQUENCES
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.keys import Keys
from prompt_toolkit.styles import Style

# Register the CSI u Shift+Enter sequence. Modern terminals (iTerm2 with
# "Report modifiers using CSI u", Kitty, Ghostty, WezTerm, VS Code, and
# others configured via Claude Code's /terminal-setup) send `\x1b[13;2u`
# for Shift+Enter. prompt_toolkit 3.0.52 doesn't have a Keys.ShiftEnter
# member, so we hijack Keys.WindowsMouseEvent (never sent on macOS/Linux)
# as the binding target.
_SHIFT_ENTER_KEY = Keys.WindowsMouseEvent
ANSI_SEQUENCES["\x1b[13;2u"] = _SHIFT_ENTER_KEY
from pydantic_ai import Agent
from pydantic_ai.messages import ModelMessage
from rich.console import Console
from rich.live import Live
from rich.markdown import Markdown
from rich.rule import Rule

MODEL = "openrouter:anthropic/claude-sonnet-4.6"

SYSTEM_PROMPT = """\
You are Callimachus, the librarian. Concise, warm, occasionally wry.
Default to 1-3 sentences unless asked for more. Use markdown freely —
**bold**, *italics*, lists, code blocks — it renders nicely in this terminal.
"""

SLASH_COMMANDS = ["/exit", "/quit", "/clear", "/help", "/save", "/history"]

HELP_TEXT = """\
### Slash commands
- `/help` — this message
- `/clear` — clear conversation history (start a fresh thread)
- `/history` — count of messages in current thread
- `/save <path>` — write the conversation to a markdown file
- `/exit` or `/quit` — leave

### Keyboard
- `Enter` — submit
- `Shift+Enter` — newline (multi-line input). Works on terminals that
  support the CSI u keyboard protocol: iTerm2 (with "Report modifiers
  using CSI u" enabled in Preferences > Profiles > Keys), Kitty, Ghostty,
  WezTerm, VS Code, and any terminal that Claude Code's `/terminal-setup`
  has configured.
- `Alt+Enter` — newline (universal fallback for any terminal)
- `Ctrl+X Ctrl+E` — open `$EDITOR` for serious multi-line input
- `Up`/`Down` — recall previous prompts (when buffer is single-line)
- `Ctrl+C` — cancel a streaming response (twice in a row exits)
- `Ctrl+D` — exit
"""


def make_key_bindings() -> KeyBindings:
    """Override prompt_toolkit's multiline defaults to chat conventions.

    Default with multiline=True: Enter inserts newline, Alt+Enter submits.
    We invert: Enter submits, Alt+Enter inserts newline. Many modern
    terminals send the same escape sequence for Shift+Enter (iTerm2 with
    "report modifiers", VS Code, Kitty), so Shift+Enter works there too.
    """
    kb = KeyBindings()

    @kb.add("enter")
    def _submit(event):  # type: ignore[no-untyped-def]
        event.current_buffer.validate_and_handle()

    # Alt+Enter (= Esc then Enter). Universal fallback for any terminal.
    @kb.add("escape", "enter")
    def _newline_alt(event):  # type: ignore[no-untyped-def]
        event.current_buffer.insert_text("\n")

    # Shift+Enter via CSI u escape sequence (\x1b[13;2u). Registered above
    # to map onto _SHIFT_ENTER_KEY. Works on iTerm2 (with CSI u enabled),
    # Kitty, Ghostty, WezTerm, VS Code, and any terminal Claude Code's
    # /terminal-setup has configured.
    @kb.add(_SHIFT_ENTER_KEY)
    def _newline_shift(event):  # type: ignore[no-untyped-def]
        event.current_buffer.insert_text("\n")

    return kb


def find_repo_root(start: Path) -> Path | None:
    for candidate in [start, *start.parents]:
        if (candidate / "README.md").exists() and (candidate / "docs").is_dir():
            return candidate
    return None


def load_env_into_os(env_path: Path) -> None:
    if not env_path.exists():
        return
    for raw in env_path.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key, value = key.strip(), value.strip().strip('"').strip("'")
        if key and value and key not in os.environ:
            os.environ[key] = value


def render_messages_as_markdown(history: list[ModelMessage]) -> str:
    """Render the message history into a markdown transcript for /save."""
    lines: list[str] = ["# Callimachus chat transcript", ""]
    for msg in history:
        kind = type(msg).__name__
        for part in getattr(msg, "parts", []):
            part_kind = type(part).__name__
            content = getattr(part, "content", None)
            if content is None:
                continue
            if part_kind == "UserPromptPart":
                lines.append(f"## you\n\n{content}\n")
            elif part_kind == "TextPart":
                lines.append(f"## calli\n\n{content}\n")
            elif part_kind == "SystemPromptPart":
                continue  # skip
            else:
                lines.append(f"<!-- {kind}/{part_kind} -->\n\n{content}\n")
    return "\n".join(lines)


async def stream_response(
    agent: Agent[None, str],
    user_text: str,
    history: list[ModelMessage],
    console: Console,
) -> tuple[list[ModelMessage], object | None, float, float | None]:
    """Stream the assistant response, return (new_history, usage, elapsed, ttfb)."""
    buffer = ""
    started = time.perf_counter()
    first_chunk_at: float | None = None

    with Live(
        Markdown(""),
        console=console,
        refresh_per_second=20,
        vertical_overflow="visible",
    ) as live:
        async with agent.run_stream(user_text, message_history=history) as response:
            async for chunk in response.stream_text(delta=True):
                if first_chunk_at is None:
                    first_chunk_at = time.perf_counter() - started
                buffer += chunk
                live.update(Markdown(buffer))
            new_history = response.all_messages()
            usage = response.usage()

    elapsed = time.perf_counter() - started
    return new_history, usage, elapsed, first_chunk_at


def enable_kitty_keyboard_protocol() -> None:
    """Ask the terminal to send CSI u sequences for modified keys.

    This is the standard mechanism applications like Claude Code use to make
    Shift+Enter / Ctrl+Enter etc. distinguishable from plain Enter at runtime,
    without requiring users to modify their terminal config files.

    Mode 1 = "disambiguate escape codes" — enough for Shift+Enter to send
    `\\x1b[13;2u`. Terminals that don't support the protocol ignore the
    request silently.
    """
    sys.stdout.write("\x1b[>1u")
    sys.stdout.flush()


def disable_kitty_keyboard_protocol() -> None:
    """Restore the terminal's previous keyboard protocol state."""
    sys.stdout.write("\x1b[<u")
    sys.stdout.flush()


async def main() -> int:
    here = Path(__file__).resolve().parent
    root = find_repo_root(here)
    if root is not None:
        load_env_into_os(root / ".env")

    if not os.environ.get("OPENROUTER_API_KEY"):
        print("FAIL: OPENROUTER_API_KEY not set.")
        return 1

    console = Console()
    agent: Agent[None, str] = Agent(MODEL, system_prompt=SYSTEM_PROMPT)

    # Persistent history (across runs of this script)
    history_dir = Path.home() / ".callimachus" / "experiments"
    history_dir.mkdir(parents=True, exist_ok=True)
    history_file = history_dir / "05-chat-history"

    style = Style.from_dict({"prompt.you": "ansicyan bold"})

    session: PromptSession[str] = PromptSession(
        history=FileHistory(str(history_file)),
        completer=WordCompleter(SLASH_COMMANDS, sentence=True, ignore_case=True),
        style=style,
        enable_open_in_editor=True,  # Ctrl+X Ctrl+E
        multiline=True,
        key_bindings=make_key_bindings(),
        prompt_continuation=lambda width, line_number, is_soft_wrap: " " * width,
    )

    # Ask the terminal to send CSI u sequences for modified keys, so Shift+Enter
    # is distinguishable from plain Enter. Mirrors what Claude Code does.
    enable_kitty_keyboard_protocol()

    # Welcome
    console.print()
    console.print(
        Rule("[bold cyan]Callimachus[/bold cyan]", align="left", characters="─")
    )
    console.print(f"[dim]Model: {MODEL}  •  /help for commands  •  Ctrl+D to exit[/dim]")
    console.print()

    history: list[ModelMessage] = []
    turn = 0
    consecutive_cancels = 0

    while True:
        try:
            user_text = await session.prompt_async(
                FormattedText([("class:prompt.you", "you ▸ ")])
            )
        except EOFError:
            console.print("\n[dim]goodbye[/dim]")
            break
        except KeyboardInterrupt:
            consecutive_cancels += 1
            if consecutive_cancels >= 2:
                console.print("[dim]bye[/dim]")
                break
            console.print("[dim](Ctrl+C again to exit)[/dim]")
            continue

        consecutive_cancels = 0
        user_text = user_text.strip()
        if not user_text:
            continue

        # Slash commands
        if user_text.startswith("/"):
            parts = user_text.split(maxsplit=1)
            cmd = parts[0].lower()
            arg = parts[1] if len(parts) > 1 else ""

            if cmd in ("/exit", "/quit"):
                break
            if cmd == "/clear":
                history = []
                console.print("[dim]history cleared[/dim]\n")
                continue
            if cmd == "/help":
                console.print(Markdown(HELP_TEXT))
                console.print()
                continue
            if cmd == "/history":
                console.print(f"[dim]{len(history)} message(s) in current thread[/dim]\n")
                continue
            if cmd == "/save":
                if not arg:
                    console.print("[red]usage: /save <path>[/red]\n")
                    continue
                path = Path(arg).expanduser()
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(render_messages_as_markdown(history))
                console.print(f"[dim]saved {len(history)} messages → {path}[/dim]\n")
                continue
            console.print(f"[red]unknown command: {cmd}  (try /help)[/red]\n")
            continue

        # Assistant turn
        turn += 1
        console.print(Rule(style="dim"))
        console.print("[bold magenta]calli ▸[/bold magenta]")

        try:
            history, usage, elapsed, ttfb = await stream_response(
                agent, user_text, history, console
            )
        except KeyboardInterrupt:
            console.print("\n[yellow]cancelled[/yellow]\n")
            continue
        except Exception as exc:
            console.print(f"\n[red]error: {type(exc).__name__}: {exc}[/red]\n")
            continue

        ttfb_s = ttfb if ttfb is not None else elapsed
        in_tok = getattr(usage, "input_tokens", 0) or 0
        out_tok = getattr(usage, "output_tokens", 0) or 0
        console.print()
        console.print(
            f"[dim]{in_tok}+{out_tok} tok  •  "
            f"{ttfb_s:.2f}s to first chunk  •  {elapsed:.2f}s total[/dim]"
        )
        console.print()

    console.print(f"[dim]({turn} turn{'s' if turn != 1 else ''})[/dim]")
    return 0


async def main_with_cleanup() -> int:
    try:
        return await main()
    finally:
        # Always restore terminal state, even if main() raised.
        disable_kitty_keyboard_protocol()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main_with_cleanup()))
