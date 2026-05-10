# 17 — source-openalex — LEARNINGS

## Run log

- **2026-05-10**, query: "denoising diffusion probabilistic models". HTTP 200 in <1s. Saved 110KB JSON fixture.

## Findings

### Endpoint shape

- Free, no auth. Polite-pool etiquette: send `mailto=` (URL param) and a `User-Agent` with the same email.
- `/works?search=…` returns `{meta, results: [...]}` where `meta.count` is the total match count and `results` honors `per_page` (cap 200).
- Per-result fields we use:
  - `title` — string
  - `doi` — string in `https://doi.org/10.x/y` form (needs URL prefix stripped)
  - `publication_year` — int
  - `cited_by_count` — int
  - `authorships[*].author.display_name` — author names
  - `primary_location.source.display_name` — venue
  - `best_oa_location.landing_page_url` / `.pdf_url` — open-access URLs
  - `abstract_inverted_index` — `{word: [positions]}` form
  - `ids.openalex` — canonical OpenAlex URL (`https://openalex.org/Wxxx`)

### Abstract reconstruction

- Each word maps to its 0-indexed positions in the original text.
- Some positions can be missing (we fill with empty strings and skip on join). Edge case in our DDPM fixture: position 6 was empty in one record — handled fine.
- Returns `None` if input is `None` or `{}`.

### arxiv detection

- arxiv DOIs are uniformly `10.48550/arxiv.{id}` (the `arxiv.` is lowercase). We pull `{id}` directly.
- Fallback: scan `best_oa_location.landing_page_url` and `.pdf_url` for an arxiv pattern via the existing `extract_arxiv_id()` helper.

### Data quality caveat

- The first record we got back had the right title + DOI for "Denoising Diffusion Probabilistic Models" (Ho et al. 2020) but the `authorships` and `abstract_inverted_index` were from a different paper ("DiffuCpG" by Yan, Steven). OpenAlex appears to merge records sometimes. We handle gracefully (parse what's there, log nothing) and rely on the judge agent to filter quality downstream.

## Decisions

- **Polite-pool mailto** is read from `OPENALEX_MAILTO` env var with a project-default fallback (`callimachus@move38studios.dev`). No need to require it.
- **`SourceUnavailable`** wraps `httpx.HTTPError` at the boundary so the agent can decide to retry vs. drop the source.
- **Discovery only, no resolver** for OpenAlex itself. Resolution happens via the matched `arxiv_id` → arxiv resolver, or via DOI → unpaywall (when we add it).
- **Per-record errors are swallowed** at the plugin level (`log.debug`), not raised — one bad record shouldn't poison the batch.

## Open questions

- Pagination beyond `per_page=200`: OpenAlex supports cursor pagination via `cursor=*`. Defer until we hit a use case.
- Citation-graph endpoints (`/works/{id}/cited_by`, `/works/{id}/references`) — the basis for snowballing in M4. Not exercised here.
- Title-match search via `title.search:` filter (vs full text `search:`). Worth probing once the judge starts caring about title-precision matches.
