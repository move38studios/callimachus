# 17 — source-openalex

Probe the OpenAlex `/works` endpoint to confirm the data shape we need for `WorkCandidate`. OpenAlex is a free, comprehensive bibliographic database (~250M works) with no auth required and a citation graph. Sending `mailto=` puts us in the "polite pool" with better service.

## Goal

Verify against the live API that:

1. The `/works` endpoint returns enough metadata to populate `WorkCandidate` (title, DOI, year, authors, venue, abstract, pdf_url, citation count).
2. Abstracts come back as an inverted index (`{word: [positions]}`) — confirm the reconstruction logic.
3. arxiv papers can be detected via DOI prefix (`10.48550/arxiv.{id}`) so we can route to the arxiv resolver.

## Run

```sh
uv run experiments/17-source-openalex/run.py "denoising diffusion probabilistic models"
```

No API key required. Optional: set `OPENALEX_MAILTO` to a real email for polite-pool service.

## Success criteria

- HTTP 200, JSON body shaped as `{meta, results: [...]}`.
- At least one result has the expected fields populated.
- Abstract inverted-index round-trips back to plain text.
- arxiv-flavored DOIs are detected and the bare arxiv_id extracted.

## Pointer

The fixture used in unit tests (`tests/sources/fixtures/openalex_response.json`) was captured from this probe. The production plugin lives at `src/callimachus/sources/bundled/openalex.py` and has full unit + live test coverage in `tests/sources/test_openalex.py`.
