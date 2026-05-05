"""Shared boilerplate for experiments — env loading, logging, model constants.

Experiments are otherwise self-contained (PEP 723 inline-script metadata,
each runnable via `uv run`). This module is the *only* allowed shared code:
env discovery + logging setup + canonical model strings. Everything else
copies in.

Usage from an experiment script:

    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from _common import setup_logging, find_repo_root, load_env_into_os, MODEL_FAST

    log = setup_logging(verbose=False)
    log.info("starting experiment")

The script's PEP 723 dependencies must include `rich>=13` if it uses
`setup_logging`.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

# Canonical model strings — all routed via OpenRouter (single API key).
# Pick by what the experiment actually needs:
#  - MODEL_FAST  for mechanics / harness / pipeline plumbing tests
#  - MODEL_SMART for judging, reasoning quality, planning
#  - MODEL_DEEP  for synthesis passes and final overviews
MODEL_FAST = "openrouter:anthropic/claude-haiku-4.5"
MODEL_SMART = "openrouter:anthropic/claude-sonnet-4.6"
MODEL_DEEP = "openrouter:anthropic/claude-opus-4.7"


def find_repo_root(start: Path | None = None) -> Path | None:
    """Walk up from `start` looking for repo root (README.md + docs/)."""
    here = (start or Path(__file__)).resolve()
    for candidate in [here, *here.parents]:
        if (candidate / "README.md").exists() and (candidate / "docs").is_dir():
            return candidate
    return None


def load_env_into_os(env_path: Path | None = None) -> None:
    """Load a `.env` file's KEY=VALUE pairs into os.environ.

    Stdlib-only parser. Does not overwrite already-set env vars. Quietly
    no-ops if the file doesn't exist. If `env_path` is None, looks for
    `.env` at the repo root.
    """
    if env_path is None:
        root = find_repo_root()
        if root is None:
            return
        env_path = root / ".env"
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


def setup_logging(
    verbose: bool = False,
    *,
    name: str = "callimachus.exp",
) -> logging.Logger:
    """Wire stdlib logging through Rich for colourful, structured experiment output.

    Call once at the top of an experiment's main(). Returns the configured
    logger. Pass `verbose=True` to drop to DEBUG level.

    Levels you'll typically use:
      log.debug("noisy detail")
      log.info("[bold]headline[/]")     # markup is enabled
      log.warning("non-fatal issue")
      log.error("something failed")
    """
    # Local import so the module loads even without rich installed (graceful
    # for experiments that don't call setup_logging).
    from rich.logging import RichHandler  # noqa: PLC0415

    handler = RichHandler(
        rich_tracebacks=True,
        markup=True,
        show_time=True,
        show_path=False,
        omit_repeated_times=False,
    )

    # Re-configure root logger if it's been touched, otherwise basicConfig.
    root = logging.getLogger()
    for h in list(root.handlers):
        root.removeHandler(h)
    root.setLevel(logging.DEBUG if verbose else logging.INFO)
    root.addHandler(handler)

    # Quiet noisy third-party loggers unless verbose
    if not verbose:
        for noisy in ("httpx", "httpcore", "openai", "anthropic"):
            logging.getLogger(noisy).setLevel(logging.WARNING)

    return logging.getLogger(name)


def require_env(key: str, log: logging.Logger | None = None) -> str:
    """Return env var `key` or fail with a clear error and exit 1."""
    value = os.environ.get(key)
    if not value:
        msg = f"FAIL: {key} not set in environment or .env"
        if log is not None:
            log.error(msg)
        else:
            print(msg)
        raise SystemExit(1)
    return value
