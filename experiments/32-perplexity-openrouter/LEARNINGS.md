# 32 — perplexity-openrouter — LEARNINGS

## Run log

- **2026-05-10**, two queries: the canned creativity one + an ad-hoc "main angles people approach diffusion models from" probe. Both got 200 in ~7–10s.

## Findings

### Citation passthrough — works, but in OpenAI-compat shape

The May-2026 research said `response.citations` (perplexity-direct's flat field) passes through OpenRouter. **It does not.** OpenRouter normalises perplexity's citations into the **OpenAI-standard `message.annotations[*].url_citation` format**.

Top-level fields returned: `choices, created, id, model, object, provider, system_fingerprint, usage`. No flat `citations`. No `search_results`.

Per citation, in `choices[0].message.annotations`:

```json
{
  "type": "url_citation",
  "url_citation": {
    "url": "https://arxiv.org/abs/2506.11039",
    "title": "Angle Domain Guidance: Latent Diffusion Requires Rotation Rather…",
    "start_index": 0,
    "end_index": 0
  }
}
```

We get **URL + title** per citation. **No `content`/`snippet`** — that has to be recovered another way (re-fetch the URL, or use the URL to look up the paper in OpenAlex/Serper).

`start_index` / `end_index` are 0 / 0 in our test (apparently not populated for this model variant). Don't rely on them.

### Quality of citations

Test query "main angles people approach diffusion models from" returned 6 citations:
1. arxiv abstract on latent diffusion
2. PMC paper on prior-frequency-guided diffusion
3. Sander Dieleman's blog post (canonical grey-lit source on diffusion)
4. Wikipedia article on diffusion models
5. ACS journal article on conformation generation
6. Personal blog "Demystifying Diffusion Models"

Mix of academic (arxiv, PMC, ACS) and grey-lit (blogs, Wikipedia). Exactly what a scout should be reading on first-look reconnaissance.

### Synthesis text + token cost

- Synthesis is in `choices[0].message.content` — markdown-formatted, structured (uses headers, bullet lists)
- Token usage: 11 input + 1176 output for the diffusion query (~$0.004 at sonar-pro pricing). Reasonable for one scout probe.

### What does NOT come through OpenRouter

- `search_results` (the per-source rich metadata array — title + snippet + date) — **NOT present**. If we want snippets, hit perplexity-direct.
- `related_questions` — even when we sent `return_related_questions: true`, no field came back. Ignored by OpenRouter passthrough.
- `images` — same.

For our scout use case: the URL list + synthesis text is enough. We don't need snippets — we'll resolve interesting URLs through the existing pipeline (arxiv resolver picks up arxiv URLs, OpenAlex picks up DOIs, etc.) which gets us the actual abstract and full text anyway.

## Decisions

- **Scout uses `perplexity/sonar-pro` via OpenRouter** through a small direct-httpx call (NOT Pydantic AI — we need access to the raw `message.annotations`). One key (`OPENROUTER_API_KEY`); no need for `PERPLEXITY_API_KEY`.
- **Citation extraction**: walk `choices[0].message.annotations`, filter `type == "url_citation"`, pull `url_citation.url` + `url_citation.title`. Build seed `WorkCandidate`s with `title` + `source_url` + `provenance(source_name="perplexity-scout", query=...)`.
- **URL classification at seed time**: for each citation URL, detect arxiv ID (regex against `arxiv.org`), DOI (extract from `doi.org` URL), or fall through to "url" candidate. The existing arxiv resolver picks up arxiv hits; non-arxiv ones might not resolve until M4 brings Unpaywall in.
- **Skip `search_results` / `related_questions` / `images`** — defer to whenever we have a use case for them.
- **Synthesis text** flows into the angle-tree presentation to the user (not into per-paper enrichment) — it's the "what's the lay of the land" summary the scout shows during the clarification ceremony.

## Open questions

- Do we ever want to pin to perplexity-direct for snippets? **Probably not for v0.1** — extra key, extra integration, marginal gain since our pipeline produces full text anyway.
- Different sonar variants — `sonar` (cheaper, less metadata) vs `sonar-pro` (default) vs `sonar-deep-research` (multi-step, expensive). Default to `sonar-pro` for scout; expose as a config knob.
- Caching — perplexity sometimes returns the same citations for similar queries. Worth a per-library cache to avoid duplicate calls during one ceremony? Defer.
