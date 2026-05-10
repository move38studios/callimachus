# 31 — serper-search — LEARNINGS

## Run log

- **2026-05-10**, query: "diffusion models for image generation". Both `/search` and `/scholar` returned 200 in <1s.

## Findings

### `/search` (regular Google web results)

- Top-level fields: `searchParameters`, `organic`, `peopleAlsoAsk`, `relatedSearches`, `credits`
- Per-result keys (in `organic[]`): `title`, `link`, `snippet`, `position`, sometimes `date` and `sitelinks`
- **`peopleAlsoAsk` and `relatedSearches`** are useful for the scout's angle expansion — e.g. for "diffusion models" we got related searches for adjacent topics. Free signal we should use.
- Default `num` returned ~10 results even when we asked for 5 (the `num` parameter is a hint, not a strict cap, in this version).

### `/scholar` (Google Scholar via Serper) — this is the one that matters

- Top-level fields: `searchParameters`, `organic`, `credits`
- **Per-result keys**: `title`, `link`, `snippet`, `year`, `pdfUrl`, `citedBy`, `publicationInfo`, `id`
- This maps very cleanly to `WorkCandidate`:
  - `title` → `title`
  - `link` → `source_url`
  - `snippet` → `abstract` (excerpt, often a few sentences)
  - `year` → `year`
  - `pdfUrl` → `pdf_url` (when available — direct PDF link!)
  - `citedBy` → `extras["serper_cited_by"]` (citation count — useful for ranking/judging by impact)
  - `publicationInfo` → `venue` (string like "J Ho, A Jain, P Abbeel - Advances in neural information…, 2020")
- Latency was sub-second for our test query.

### Auth + cost

- Auth: `X-API-KEY` header
- POST JSON body: `{"q": "...", "num": N}`
- Each call = 1 credit. 2,500 free credits on signup; paid tiers from ~$0.30/1k at scale.
- No client SDK needed; plain `httpx.post`.

## Decisions

- **Serper plugin (M2.0a)** will expose two `search()` modes — one defaults to `/search`, an option flag to use `/scholar`. Or two separate plugins — `serper_web` and `serper_scholar`. Lean **one plugin, two modes** keyed off a constructor arg or a per-call kwarg, since the response shapes are similar enough.
- **Citation count** (`citedBy`) is a strong signal for the judge — store it in `WorkCandidate.extras["citedBy"]` and surface it to the judge prompt as one of the seminality signals.
- **`/scholar` is the workhorse for academic discovery**; `/search` is the workhorse for grey lit + related-searches. The hunter agent should use both, biased per angle.
- **Don't worry about `num` strictness** — Serper returns "around N", treat it as a hint.

## Open questions

- Pagination — how do we get >10 results? Serper supports `page` parameter; defer to when we hit a use case.
- Does `/scholar` ever return papers without a `year`? Need to handle `Optional[int]` — current schema already does.
- Rate limiting — Serper docs mention QPS limits but our experiment didn't trigger any. Add adaptive backoff in the plugin once we see real load.
