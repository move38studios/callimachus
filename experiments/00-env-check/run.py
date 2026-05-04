"""Smoke test: Python version, .env discoverable and parseable, stdlib basics work.

Stdlib-only. Run before installing any dependencies.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

EXPECTED_KEYS = [
    "ANTHROPIC_API_KEY",
    "OPENAI_API_KEY",
    "GEMINI_API_KEY",
    "OPENROUTER_API_KEY",
    "MISTRAL_API_KEY",
    "EXA_API_KEY",
    "PERPLEXITY_API_KEY",
    "SEMANTIC_SCHOLAR_API_KEY",
    "VOYAGE_API_KEY",
    "CALLIMACHUS_LLM_PROVIDER",
]


def find_repo_root(start: Path) -> Path | None:
    """Walk up from `start` looking for a directory that contains README.md and docs/."""
    for candidate in [start, *start.parents]:
        if (candidate / "README.md").exists() and (candidate / "docs").is_dir():
            return candidate
    return None


def parse_env(path: Path) -> dict[str, str]:
    """Tiny .env parser. Returns {key: value} for non-comment, non-empty lines."""
    result: dict[str, str] = {}
    for raw in path.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key:
            result[key] = value
    return result


async def stdlib_basics_ok() -> bool:
    """Confirm asyncio works at all."""
    await asyncio.sleep(0)
    return True


def main() -> int:
    print("== Callimachus env-check ==\n")

    # Python version
    major, minor = sys.version_info[:2]
    print(f"Python: {sys.version.splitlines()[0]}")
    if (major, minor) < (3, 11):
        print(f"  FAIL: need Python 3.11+, have {major}.{minor}")
        return 1
    print("  OK\n")

    # Repo root + .env discovery
    here = Path(__file__).resolve().parent
    root = find_repo_root(here)
    if root is None:
        print("  FAIL: could not find repo root (no README.md + docs/ in any parent)")
        return 1
    print(f"Repo root: {root}")

    env_path = root / ".env"
    env_example = root / ".env.example"
    if not env_example.exists():
        print(f"  WARN: {env_example} missing — that's the template users copy")

    if not env_path.exists():
        print(f"  .env not present at {env_path}")
        print("  (this is fine for now — copy .env.example to .env when you're ready)")
    else:
        env = parse_env(env_path)
        set_keys = [k for k in EXPECTED_KEYS if env.get(k)]
        unset_keys = [k for k in EXPECTED_KEYS if not env.get(k)]
        print(f"  .env present at {env_path}")
        print(f"  Set ({len(set_keys)}): {', '.join(set_keys) or '(none)'}")
        print(f"  Unset ({len(unset_keys)}): {', '.join(unset_keys) or '(none)'}")
    print()

    # Stdlib smoke test
    print("Stdlib basics:")
    ok = asyncio.run(stdlib_basics_ok())
    print(f"  asyncio.run: {'OK' if ok else 'FAIL'}")
    if not ok:
        return 1

    print("\nAll checks passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
