# 32 — perplexity-openrouter

Direct httpx call to OpenRouter using `perplexity/sonar-pro`. The 2026 research said `citations` passes through — verify it. We'll use this raw JSON shape from the scout agent in M2.3 to get both the synthesis text and the seed URLs in one call.

## Prereq

`OPENROUTER_API_KEY` set in `.env`.

## Run

```bash
uv run experiments/32-perplexity-openrouter/run.py "what are the main angles people approach 'creativity' from"
```

## Success criteria

- 200 response from `perplexity/sonar-pro` via OpenRouter
- `citations` field present at the response top level (list of URLs)
- Optionally `search_results` (richer per-source metadata: title, snippet, date)
- Synthesis text in `choices[0].message.content`
- Token usage visible in `usage`

If `citations` is missing, the scout will need to regex-extract URLs from the synthesis text instead — recoverable but worse signal. The point of this experiment is to find out which path we're on.
