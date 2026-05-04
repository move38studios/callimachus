# 00 — env-check

The simplest possible experiment. Confirms the basics work before we install any dependencies:

- Python 3.11+ is available
- We can find and parse a `.env` file at the repo root
- Stdlib basics (asyncio, pathlib) work as expected

Stdlib-only. No `uv sync` needed to run this.

## Run

```bash
python experiments/00-env-check/run.py
```

(From the repo root, or any directory — the script finds `.env` itself.)

## Success criteria

- Exit code 0
- Prints the Python version and confirms it's >= 3.11
- Reports whether `.env` exists at repo root, and if so, lists which expected keys are set (without printing values)
- No exceptions

## Why this exists

If this experiment fails, nothing else will work. It's the smoke test before the smoke tests.
