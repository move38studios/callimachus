"""LLM access constants and helpers shared across the product.

Mirror of `experiments/_common.py`'s model constants. All routed via
OpenRouter (one key, many models). See `docs/ARCHITECTURE.md` for the
per-role defaults (Haiku for hunters/orchestrator, Sonnet for the judge
and enricher, Opus for end-of-build synthesis).
"""

from __future__ import annotations

# Default models, in increasing cost / quality order.
MODEL_FAST = "openrouter:anthropic/claude-haiku-4.5"
MODEL_SMART = "openrouter:anthropic/claude-sonnet-4.6"
MODEL_DEEP = "openrouter:anthropic/claude-opus-4.7"
