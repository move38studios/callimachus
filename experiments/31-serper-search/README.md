# 31 — serper-search

Hit Serper's `/search` and `/scholar` endpoints with a real query. We need to see:

- The raw response shape (what fields per result, what extra blocks like `knowledge_graph` / `answer_box`)
- Specifically how `/scholar` differs from `/search`
- Per-result fields we can populate `WorkCandidate` with
- Latency, rate limit headers (if any)

Confirms what the May 2026 research told us before we wire the plugin in M2.0a.

## Prereq

`SERPER_API_KEY` set in `.env` at the repo root.

## Run

```bash
uv run experiments/31-serper-search/run.py "diffusion models"
```

The script hits both `/search` and `/scholar`, prints field summaries + a few sample results from each, and dumps the full JSON to `output/` for inspection.

## Success criteria

- Both endpoints return 200 with structured JSON
- We can identify the result-list field (`organic` vs scholar's variant) and extract title/url/snippet
- We see whether `/scholar` includes year/citation-count metadata that beats `/search` for academic discovery
