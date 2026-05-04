# 00 — env-check — LEARNINGS

## Run log

- **2026-05-04**, macOS (Darwin 24.6.0), Python 3.14.4 — exit 0, all checks passed.

## Findings

- Python 3.14.4 is the local install; well above the 3.11 minimum stated in `ARCHITECTURE.md`. No syntax issues with `from __future__ import annotations`, `X | None` unions, or `asyncio.run`.
- `find_repo_root()` (walk up looking for `README.md` + `docs/`) works regardless of where the script is invoked from — robust to `cd experiments/00-env-check && python run.py`, `python experiments/00-env-check/run.py` from root, or absolute path.
- `.env` not present at this stage is the expected state — the script reports it cleanly without erroring. Once `.env` exists the script lists which expected keys are set without printing any values.
- The stdlib-only `.env` parser is intentionally minimal: handles `KEY=VALUE`, optional surrounding quotes, comments, blank lines. Does **not** handle multiline values, escape sequences, or `$VAR` interpolation. Good enough for v0.1 smoke tests; if we ever need richer parsing in product code, switch to `python-dotenv` (which Pydantic settings uses anyway).

## Decisions

- **Minimum Python version stays 3.11.** No reason to lift it; 3.11 is the floor for `Self` typing, faster startup, and improved error messages we want.
- **Stdlib `.env` parsing is sufficient for experiments.** Product code (in `src/`) will use `pydantic-settings` which handles `.env` properly.
- **Repo root detection convention** = walk up looking for `README.md` + `docs/`. This is safe enough for our purposes; experiments should reuse this pattern when they need the repo root.

## Open questions

- None. This was a smoke test; everything worked.
