# Learnings

The cumulative log of what we discover while building Callimachus. Each component experiment in `experiments/` has its own `LEARNINGS.md` with the full detail; this top-level file collects the highlights, surprises, and decisions that bind future work.

The convention: when an experiment surfaces something that future-you (or a future contributor) needs to know — a gotcha, a non-obvious choice, a default we landed on — note it in the experiment's local LEARNINGS, and if it's broadly relevant, summarise it here in one or two sentences with a link.

## How to read this file

Entries are ordered newest-first. Each entry is short. If you need depth, follow the link to the experiment's local LEARNINGS or the relevant doc.

## Entries

### 2026-05-10 — Probed Serper + Perplexity-via-OpenRouter for M2 scout

Two focused experiments before wiring the M2.0a Serper plugin and the M2.3 scout agent.

**Serper** (experiments/31): `/search` returns standard Google org results plus `peopleAlsoAsk` and `relatedSearches` (useful for scout angle expansion). `/scholar` is the gold mine for academic discovery — per-result keys are `title, link, snippet, year, pdfUrl, citedBy, publicationInfo` which maps very cleanly to `WorkCandidate`. Citation count (`citedBy`) is a strong seminality signal we'll surface to the judge. One plugin (M2.0a) with two modes — defaults to `/search`, flag for `/scholar`. 1 credit per call, fast.

**Perplexity via OpenRouter** (experiments/32): citations DO pass through but **not via the flat top-level `citations` field** the May-2026 research suggested. OpenRouter normalises perplexity's output into **OpenAI-compat `choices[0].message.annotations[*].url_citation`** with `{type, url_citation: {url, title, start_index, end_index}}`. We get URL + title only — no snippet/content. `search_results`, `related_questions`, `images` are stripped on the OpenRouter passthrough. For the scout this is enough — non-snippet seed URLs flow through the existing pipeline (arxiv resolver picks up arxiv URLs, OpenAlex picks up DOIs) which gives us full text anyway.

**Confirms the M2 plan**: scout uses a small direct-httpx call to OpenRouter (not Pydantic AI — we need raw access to `message.annotations`) for perplexity-sonar-pro synthesis + URL citations. Plus arxiv + OpenAlex + Serper as DiscoverySource plugins for per-angle structured search. **No `PERPLEXITY_API_KEY` needed** — the existing `OPENROUTER_API_KEY` covers it.

- **Sources**: [`experiments/31-serper-search/LEARNINGS.md`](experiments/31-serper-search/LEARNINGS.md), [`experiments/32-perplexity-openrouter/LEARNINGS.md`](experiments/32-perplexity-openrouter/LEARNINGS.md)
- **Affects**: M2.0a (Serper plugin shape locked), M2.3 (scout citation-extraction path locked).

### 2026-05-09 — Roadmap re-prioritised after M1 ships

After the deterministic pipeline shipped end-to-end, paused to reassess. Three changes to DEV_PLAN.md:

1. **Cost tracking dropped.** Translating tokens to USD isn't Callimachus's business — pricing changes too often, varies by deployment (OpenRouter / direct / Bedrock / Vertex), and isn't load-bearing for the product. We *do* keep token + model logging (truthful runtime info) but no `cost.json`, no `calli cost`, no `--budget-usd`. Bounds are `--max-works N` and `--max-hours N`. Users who want a USD number can multiply tokens × current per-token price themselves.

2. **M2 = "topic → library" with mandatory HITL ceremony.** Original M2 was orchestrator+hunter+judge+ingest. New M2 adds a **scout** stage and a **clarification ceremony** in front. A bare topic like "creativity" is ambiguous; agent must do shallow probing across plausible angles + related fields, present what it found, and ask targeted questions before committing to a deep build. Two-step UX (terraform plan/apply style): `calli build --topic "..."` produces a plan; `calli build --from-plan ...` runs it. `--auto` available but not the default.

3. **M3 = chat (talk to your library).** Was M4 in the original. Promoted because: it reuses everything we have (the query stage, the chat REPL pattern from experiment 05), it's a smaller lift than snowball, and it closes the second-biggest product-vision gap. Snowball + multi-collection + dashboard moved to M4.

Doc updates landed:
- `DEV_PLAN.md`: Direction-change note added; M1.5 marked dropped; M2 rewritten with scout/ceremony sub-phases (M2.0–M2.5); M3 rewritten as the chat milestone with sub-phases (M3.0–M3.2); M4 absorbs old M3 (snowball) + dashboard work.
- `README.md`: "Estimated cost per run" table replaced with "Cost (you do the math)" — explains the no-USD policy, lists `--max-works` / `--max-hours` as the caps.
- `USER_STORIES.md`: story 9 ("Cost and time control") rewritten as "Scope control + run transparency".
- `ARCHITECTURE.md`: "Cost transparency" section renamed "Run transparency (no cost translation)"; `calli cost` removed from the CLI table; `cost_usd` column kept in schema (already in DB) but commented as vestigial / not populated in v0.1; folder layouts updated to drop `cost.json`.

- **Affects**: `docs/DEV_PLAN.md`, `docs/ARCHITECTURE.md`, `docs/USER_STORIES.md`, `README.md`. No code changes.

### 2026-05-06 — M1.4b CLI green; first real end-to-end ingest works

`src/callimachus/cli.py` — Typer app with four commands:
- `calli init [path]` — create library directory + DB
- `calli ingest <seed.yaml> [--library PATH] [--no-ocr] [--fail-fast]` — run the pipeline over a YAML list of identifiers (`arxiv:`, `doi:`, `url:`, or full custom)
- `calli query "..." [--library PATH] [-k N]` — vector search the library
- `calli list [--library PATH]` — show works in the library

Wired into `pyproject.toml` as `[project.scripts]` so `uv run calli ...` works after `uv sync`. 19 unit tests + the real-network smoke test below.

**Real end-to-end smoke test passed**:
- Local tmp dir at `/var/folders/.../callimachus-smoke-XXXXXX` (no `~/Callimachus` pollution)
- `calli init` created the library
- `calli ingest seed.yaml` (with one arxiv id) ran arxiv → LaTeX → Sonnet enrichment via OpenRouter → nomic embeddings on mps (Apple Silicon GPU) → 30 chunks indexed
- `calli query "what is the variational bound for diffusion training"` returned the "Extended Derivations" section of the DDPM paper as the top hit — semantic search working
- `calli list` showed enriched title + authors
- Tmp dir cleaned up after

**Lessons captured**:
- **CLI must load `.env`** the same way experiments did. Pydantic AI's `OpenRouterProvider` raises `UserError` if `OPENROUTER_API_KEY` isn't in `os.environ`. Added `_load_env_file()` + `_bootstrap_env()` helpers; called from each command before any LLM/network step. First-wins (shell env beats `.env`).
- **Typer's `CliRunner(mix_stderr=False)`** was removed in newer Typer/Click. The new default *is* to separate stderr from stdout. Just `CliRunner()` works.
- **`Annotated[Path | None, typer.Option(...)]`** is the modern Typer signature for optional kwargs. Cleaner than `Optional[Path] = typer.Option(...)`.
- **`raw_obj: object = yaml.safe_load(...)`** + `cast` is the right way to thread an untyped parser result through pyright strict.
- **First real run takes ~30s** — most of which is the first nomic-v1.5 model download and load. Subsequent runs are ~5s for the model + actual embedding. Worth surfacing this in user-facing docs.
- **Smoke test discipline**: write the smoke dir path to `/tmp/_callimachus_smoke_dir` so cleanup at the end is one `rm -rf "$(cat ...)"` away. No accidental pollution of the real `~/Callimachus`.
- **`calli ingest` with stubs is fast** (test runs in <1s); the real network/model run takes ~30s for one paper. Production path: ~$0.005 per paper for Sonnet enrichment + free for arxiv/embedding.

**M1.4 is complete.** The CLI is real. M1.5 (cost tracking + run log) is next, then v0.1 ships.

- **Affects**: `pyproject.toml` (calli + callimachus scripts uncommented), `src/callimachus/cli.py` (new), `tests/test_cli.py` (new).

### 2026-05-06 — M1.4a ingest orchestrator (full pipeline callable)

`src/callimachus/pipeline/ingest.py` — single `ingest_one(candidate, …)` function that runs the seven pipeline stages end to end: resolve → download → extract → enrich → chunk → embed → index. Returns an `IngestResult(work_id, work, enrichment, chunks_indexed)` summary.

`make_work_id(candidate)` derives a stable slug: `arxiv-2006-11239` for arxiv IDs, `doi-...` for DOIs, title-slug fallback (truncated at 60 chars), `untitled` last resort.

The orchestrator applies **Contextual Retrieval lite** at embed-time — `apply_contextual_prefix(chunk.text, title=enrichment.title, section=chunk.section)` for each chunk, so the embedder sees `[Paper: title] [Section: section]\n\n<chunk text>` while `Chunk.text` in the DB stays clean (per the design from M1.3d).

11 new tests, **170 unit + 2 live total**. Coverage:
- Happy path (LaTeX archive end-to-end → DB has Work + Chunks + vec_chunks, FS has all artifacts)
- PDF path with stub OCR (verifies images saved + paper.md written)
- Embeddings searchable post-ingest
- Failures propagate (resolver, enricher)
- Re-runs idempotent (chunk count stable across runs)
- `make_work_id` cases (arxiv new + old style, DOI, title fallback, truncation)

**Lessons captured**:
- **Pipeline is "thin glue"** — `ingest_one` is ~50 lines because each stage is well-typed and idempotent. Worth the front-loading on the M1.3 sub-stages.
- **Stub-friendly design pays off**: every stage takes injected dependencies (`enricher`, `embedder`, `ocr` callable/Protocols + `registry` instance). Tests need zero LLM calls and zero network — full pipeline runs in tmp_path with stubs in <1s.
- **Per-stage idempotency = no checkpoint state needed for v0.1**: each stage already detects "I've done this" (download via size check, extract via paper.md exists, enrich via overwrite, chunk/embed/index via delete-and-rewrite). Crash mid-paper → re-run resumes naturally. Real `state.json` checkpointing for *cost* tracking lands in M1.5.
- **`cast()` for Protocol parameters in tests**: when test stub classes structurally satisfy a Protocol, pyright sometimes can't infer it through generic functions — `cast("Resolver", _StubResolver(...))` makes the intent explicit.

- **Affects**: `src/callimachus/pipeline/ingest.py`. CLI in M1.4b will wrap this.

### 2026-05-06 — M1.3d chunk + embed + index (deterministic pipeline complete)

Three modules close out M1.3:

- **`pipeline/chunk.py`** — recursive paragraph-aware splitter, no LangChain dep. ~2000 char target with ~250 char overlap (~12%). Tracks section headings (markdown `#`/`##` and pylatexenc's `§ HEADING`). Splits at paragraph → sentence → arbitrary char boundaries in that order. YAML frontmatter stripped before chunking. Section change forces a chunk break (don't mix sections).
- **`pipeline/embed.py`** — `Embedder` Protocol with `embed_documents()` and `embed_query()`. `NomicEmbedder` default impl, lazy-loads `sentence-transformers` + nomic-v1.5. Critical: applies `search_document:` / `search_query:` prefixes per the model card (skipping costs ~5 MTEB points). `apply_contextual_prefix(text, title=, section=)` is the cheap "Contextual Retrieval lite" helper — prepends `[Paper: ...] [Section: ...]\n\n` for retrieval gain at zero LLM cost.
- **`pipeline/index.py`** — `index_work(...)` upserts `Work`, replaces all `Chunk` + `vec_chunks` rows for the work in one transaction. Idempotent — re-runs cleanly replace state rather than stacking.

Total: 159 unit + 2 live (gated). Pipeline is complete: candidate → resolve → download → extract → enrich → chunk → embed → index → queryable library.

**Lessons captured**:
- **Recursive char splitting beats semantic chunking** on academic papers per Vecta/FloTorch's Feb 2026 benchmark (69% vs 54% accuracy). Don't waste compute on semantic chunking for v0.1.
- **Nomic prefix discipline**: must use `search_document: ` for indexed text and `search_query: ` for queries. Tested explicitly to catch any future regression where someone might forget.
- **Heading regex covers both pylatexenc `§ HEADING` and markdown `#` styles** in one pattern. Avoids needing to canonicalize extractor output.
- **Section change forces chunk break** — chunks shouldn't mix content across section boundaries. Tested this directly.
- **Embedding-side prefix vs storage-side text**: the `search_document:` prefix and the contextual prefix (`[Paper: ...] [Section: ...]`) are applied **only at embedding time**. The stored `Chunk.text` is clean — keeps it usable for full-text search, retrieval display, and future BM25 indexing without prefix garbage.
- **Idempotent index_work**: transaction = upsert Work → delete old chunks (with vec_chunks too) → insert new chunks + embeddings. Tested re-runs replace cleanly.
- **Contextual Retrieval lite vs full**: we ship the cheap (heading-prefix) variant. The Anthropic-style LLM-generated context per chunk would be next-step polish.
- **`sentence-transformers` adds torch + transformers + scikit-learn etc.** — heavy but the cost of running embeddings locally without an external API.
- **`del unused_arg` pattern** continues to be the cleanest way to "use" Protocol-required parameters without ARG002 noise.
- **Pyright fixture typing**: `@pytest.fixture def engine(tmp_path: Path) -> Engine:` — annotate the return type so all `engine: Engine` parameters in tests check cleanly. Avoids `reportUnknownArgumentType` cascades.

- **Affects**: `pyproject.toml` (sentence-transformers + einops), `src/callimachus/pipeline/{chunk,embed,index}.py`.

### 2026-05-06 — M1.3c enrich stage (LLM → metadata + frontmatter)

`src/callimachus/pipeline/enrich.py` — single LLM call per work that takes the extracted markdown and produces a structured `Enrichment` (title, authors, year, venue, summary, key_claims, methods, datasets, keywords). Outputs:

- `works/<id>/metadata.yaml` — full Enrichment as YAML for programmatic access
- `works/<id>/summary.md` — just the summary text
- `works/<id>/paper.md` — same body, with YAML frontmatter prepended (Jekyll/Obsidian convention; renders cleanly in any markdown viewer)

Re-running enrichment **strips and replaces** existing frontmatter rather than stacking. Idempotent for the rewriting; the LLM call itself isn't (per-work checkpointing at the orchestrator decides whether to re-run).

Also new: `src/callimachus/llm.py` — model constants (`MODEL_FAST` / `SMART` / `DEEP`) shared between product code and `experiments/_common.py`. Pipeline gets `pydantic-ai-slim[openrouter]` as a project dep.

**Decoupling from Pydantic AI**: `enrich_to_files` only requires an `EnrichFn = Callable[[str], Awaitable[Enrichment]]`. Tests pass stub functions; production uses `make_default_enricher()` which lazy-imports Pydantic AI and wraps an `Agent`. This means tests don't need any LLM mocking infrastructure.

**16 new tests, 130 total green**.

**Lessons captured**:
- **`EnrichFn` callable abstraction** beats taking an `Agent` directly. Tests are dead-simple (`async def stub(text): return canned`), production wraps in `make_default_enricher()`. No `TestModel` plumbing needed.
- **YAML frontmatter parser**: detect leading `---`, find the next `---` on its own line, treat anything between as the YAML block. Handle malformed (unclosed) blocks by leaving content alone — better than silently mangling.
- **`exclude_none=False`** on Pydantic's `model_dump`: include null fields explicitly in YAML so consumers see what's known-missing vs not-yet-extracted.
- **Truncation with a warning** is the right v0.1 answer for very long inputs (book chapters etc.). Real chunking is M2+. Cap at 400k chars (~100k tokens, well within Sonnet's 200k window).
- **`ENRICHMENT_SYSTEM_PROMPT` discipline**: explicit anti-hedge rule ("don't say 'discusses' or 'addresses' — state the claim"), explicit format rules (full names, lowercase keywords, multi-word concept preference). These will need iteration on real corpora; recorded as M1.3c-v0 baseline.
- **`Field(default_factory=lambda: [])` again** for the same `reportUnknownVariableType` reason as M1.3b. Pattern is settling; consider extracting to a `_empty_list` helper if it spreads further.

Pipeline at end of M1.3c — read paper PDF → extract markdown → enrich → ready for embed/index in M1.3d.

- **Affects**: `pyproject.toml` (pydantic-ai-slim + pyyaml deps), `src/callimachus/llm.py` (new), `src/callimachus/pipeline/enrich.py`.

### 2026-05-06 — M1.3b OCR provider abstraction + Mistral implementation

`src/callimachus/pipeline/ocr/` — pluggable OCR layer. Protocol-based contract (`OcrProvider`) + first implementation (`MistralOcr`). The PDF path through `extract_to_markdown` now routes to whichever OCR provider is passed in.

**Mistral flow** (per the cookbook): `files.upload(purpose="ocr")` → `files.get_signed_url()` → `ocr.process(document={"type":"document_url",...}, include_image_base64=True)` → `files.delete()` for cleanup. Image extraction: each `page.images[i].image_base64` is a **data URL** (`data:image/jpeg;base64,...`), not raw base64. Parser splits the prefix, decodes the payload, returns `(content_type, bytes)`.

**On-disk layout for OCR'd works**:
```
works/<id>/
  original.pdf
  paper.md          # markdown with image refs rewritten to images/img-N.png
  images/
    img-0.png
    img-1.png
```

`_rewrite_image_refs(markdown, "images/")` rewrites `![alt](img-0.png)` → `![alt](images/img-0.png)`, leaving absolute URLs and data URLs untouched. Idempotent re-runs preserved (already-prefixed paths aren't double-prefixed).

**51 pipeline tests pass** (33 from M1.3a + 18 new for OCR + Mistral). Total: 114 unit + 1 live, all green.

**Lessons captured**:
- **`mistralai` import path**: `from mistralai.client import Mistral` (the top-level `from mistralai import Mistral` no longer works in v2.4+). The cookbook uses the `.client` form.
- **Mistral data URLs**: `image_base64` is a full data URL string, not a raw base64 payload. Strip the `data:<ct>;base64,` prefix before decoding. Build a `parse_data_url()` helper.
- **`asyncio.to_thread` is the bridge** for Mistral's sync SDK from our async pipeline. Wraps cleanly.
- **`finally`-cleanup pattern for uploaded files** — file_id deletion runs even if OCR call raises, so we don't leak files on Mistral's side.
- **Image dedup across pages**: same `img.id` can appear in multiple pages' `images` lists. Track `seen_ids` and emit each image only once.
- **Bad data URLs from a single image shouldn't kill the whole result** — log a warning and skip that one image.
- **`ASYNC240` ruff rule**: async functions calling `pathlib.Path.read_bytes()` block the event loop. Wrap with `await asyncio.to_thread(path.read_bytes)`. Also applies to `write_bytes`, but only for genuinely large I/O; for small writes the cost of switching threads exceeds the benefit (we kept download.py sync since it writes once per work).
- **`Field(default_factory=list)` triggers pyright `reportUnknownVariableType`** in some cases (`list[Unknown]` inferred). Workaround: `Field(default_factory=lambda: [])` lets the annotation drive inference.
- **Be deliberate with global renames** — `_parse_data_url` → `parse_data_url` would have broken `test_parse_data_url_*` test functions if I'd used `replace_all` (the leading-underscore would match the `_` between `test` and `parse` in test names). Used targeted `sed` instead, learned from the M1.2 incident.
- **Removed `cast` calls** when SDK fields are now properly typed — pyright flags `reportUnnecessaryCast`. Sign that the SDK has improved its stubs.

- **Affects**: `pyproject.toml` (mistralai dep), `src/callimachus/pipeline/ocr/`, `src/callimachus/pipeline/extract.py`.

### 2026-05-06 — M1.3a pipeline scaffold: paths + download + extract (LaTeX path)

`src/callimachus/pipeline/`:
- `paths.py` — single source of truth for library + per-work paths. `get_library_root()` resolves from explicit override → `$CALLIMACHUS_LIBRARY` → `~/Callimachus/`. `extension_for_content_type()` maps Content-Type to file extensions for `original.{ext}`.
- `download.py` — `download_to_library(library_root, work_id, ResolvedFile)` writes bytes to `works/<id>/original.{ext}`. Idempotent via size check.
- `extract.py` — `extract_to_markdown(...)` for the LaTeX path (`.tar.gz` / `.tex`). Uses pylatexenc's `LatexNodes2Text` with math rendered as Unicode. Multi-file archives: picks the largest `.tex` containing `\documentclass`. PDF and HTML paths raise `ExtractError` for now (M1.3b).

**33 new tests** (paths, download, extract end-to-end). Total: 96 unit + 1 live, all green.

**Lessons captured**:
- **pylatexenc renders section headings UPPERCASE** (e.g. `\section{Introduction}` → `§ INTRODUCTION`). Functionality is fine — content survives — but tests should case-insensitive match. If we want title-case headings we'd need a custom converter or post-process.
- **Math via Unicode**: `math_mode="text"` renders `$\beta$` → `β`, `$\sqrt{x}$` → `√x`. Good for embedding/enrichment; unreadable-but-grep-able for users. Acceptable for v0.1.
- **arxiv source archives are tar.gz, not just .tex**. `tarfile.open(mode="r:*")` auto-detects compression. Multi-file projects need a "pick the main .tex" heuristic; `\documentclass` presence + size is a workable signal.
- **`pytest.raises(match=...)` with regex metacharacters needs raw strings or escaping** (RUF043). `match=r"M1\.3a"`, not `match="M1.3a"`.
- **pylatexenc has no type stubs** — `latex_to_text()` returns `Unknown | str`. Pattern: assign to `object` with `# pyright: ignore[reportUnknownMemberType, reportUnknownVariableType]`, then `cast("str", ...)`. Contained in one line.
- **Pre-commit hook habit**: running `uv run pre-commit run --all-files` before `git commit` skips the abort-and-retry cycle when hooks reformat files.

- **Affects**: `pyproject.toml` (pylatexenc dep), `src/callimachus/pipeline/`.

### 2026-05-05 — M1.2 arxiv plugin green (real network, both interfaces)

`src/callimachus/sources/bundled/arxiv.py` — bundled `arxiv` plugin implementing both `DiscoverySource` (Atom-format query API) and `Resolver` (LaTeX source preferred, PDF fallback). Real `httpx` async client with connection pooling via `start()/close()` lifecycle hooks, ~1 req/3s rate limiting (arxiv's published policy), confidence-based selection (1.0 if `arxiv_id` present or `arxiv.org/abs/`-style URL). Registered as entry point under both `discovery_sources` and `resolvers` groups. **63/63 unit tests pass** (1 live test deselected by default).

**Tests**: against a hand-crafted Atom-format fixture (`tests/sources/fixtures/arxiv_atom_response.xml`) that mirrors arxiv's real response shape — chose this over a captured-from-real-API fixture because arxiv 429'd me when I tried to fetch one (which itself confirmed rate-limit aggressiveness). 13-case parametrized `extract_arxiv_id` test covers new-style, old-style (`hep-th/0001234`), versioned (`v2`), URL forms (abs/pdf/e-print), and edge cases. `httpx.MockTransport` for search/resolve flow tests. Live test gated behind `pytest -m live`.

**Lessons captured**:
- **arxiv 429s aggressively** even on first requests with reasonable user-agent. Real client must wait between requests; tests must mock. The 3s-per-request limit is the real ceiling.
- **`httpx.MockTransport`** is the clean way to test http-using code in pytest — assign to `plugin._client` (with `# pyright: ignore[reportPrivateUsage]`), no monkey-patching of internals required.
- **arxiv ID regex** must handle both new-style (`2006.11239`) and old-style (`hep-th/0001234`) IDs, version suffixes (`v22` not just `v1`), and URL forms (abs/pdf/e-print). Single regex with alternation works.
- **Atom XML namespacing** — must use `findtext("atom:id", namespaces=ATOM_NS)`. The `arxiv:` namespace adds metadata fields (`primary_category` etc.) but isn't strictly needed for our parsing.
- **LaTeX source preferred over PDF** for arxiv — cleaner extraction (math intact, no OCR), and the `e-print` endpoint returns gzipped tar with the original LaTeX. PDF is the fallback.
- **`# pyright: ignore[reportPrivateUsage]`** is the right way to allow legitimate test access to `_client` rather than relaxing the rule globally.
- **Be careful with `replace_all`** — renaming `_parse_atom_response` → `parse_atom_response` also matched test function names like `test_parse_atom_response_*` because they share the prefix. Tests would silently stop being collected since pytest needs `test_` not `testparse_`. Cross-check test counts after a global rename.

- **Affects**: `pyproject.toml` (httpx dep + arxiv entry points), `src/callimachus/sources/bundled/arxiv.py`, `tests/sources/`.

### 2026-05-05 — M1.1 plugin loader green (sources + registry + local_pdfs)

`src/callimachus/sources/` lives. `protocols.py` (DiscoverySource, CitationGraph, Resolver Protocols + WorkCandidate, ResolvedFile, Provenance, SourceUnavailable). `registry.py` (entry-point + local-file plugin loading, instance-cache so a class registered under both groups instantiates once, confidence-based `resolve()` loop, optional `start()/close()` lifecycle hooks). `bundled/local_pdfs.py` as the first plugin: implements both Protocols, scans configured paths for PDFs, crude title-substring matching. Registered as an entry point in `pyproject.toml` under both `discovery_sources` and `resolvers` groups. **35/35 tests pass** (29 sources, 6 storage).

**Lessons captured**:
- **Entry-point dedup**: when a plugin class is registered under multiple groups, the registry must cache by `ep.value` and instantiate once. Otherwise plugins like `local_pdfs` end up with two separate instances and divergent config state.
- **Protocol invariance bites**: declaring `kind: str = "vault"` in a plugin trips pyright when the Protocol declares `kind: SourceKind` (a Literal type). Plugins must use the typed alias: `kind: SourceKind = "vault"`. Same for `kinds: list[WorkKind]` parameter on `search()`. Export `SourceKind`/`WorkKind` from the package so plugin authors can use them.
- **`getattr(plugin, 'start', None)` returns `object`** under pyright strict — can't `await` directly. Helper `_maybe_call(plugin, "method_name")` that uses `inspect.isawaitable()` to type-narrow before awaiting.
- **N818 (Exception naming)** flags `SourceUnavailable` (no `Error` suffix). Kept the name; it reads better and matches Pydantic AI's `ModelRetry`. `# noqa: N818` on the class.
- **`del query, limit, ...`** is a clean way to "use" deliberately-unused parameters that exist for Protocol conformance — avoids ruff ARG002 noise more cleanly than per-arg `# noqa`.

- **Affects**: `pyproject.toml` (entry points for bundled plugins), `src/callimachus/sources/`, `docs/PLUGINS.md` (contract spec already updated).

### 2026-05-05 — Plugin protocol design locked (M1.1 prep)

Worked through the architectural decisions for the source/resolver plugin contract before writing any code. Key calls:

- **`typing.Protocol` (PEP 544), not ABC.** Plugin authors don't inherit anything; pyright catches mismatches structurally; `runtime_checkable` for `isinstance` when needed.
- **`WorkCandidate` ≠ `Work`.** Candidate is pre-acceptance Pydantic, lightweight, source-agnostic. Work is the SQLModel in the DB. Conversion happens at admission.
- **Optional capabilities = separate Protocols.** `DiscoverySource` (everyone) + `CitationGraph` (Semantic Scholar etc.). Plugins implement what they support; registry exposes capability checks. No `NotImplementedError` stubs.
- **Local plugins live at `<library_root>/plugins/`** (not project-cwd). Library is the unit of configuration.
- **Plugins raise `callimachus.sources.SourceUnavailable`**, not `pydantic_ai.ModelRetry`. Decouples plugins from `pydantic_ai`. Agent-tool wrappers translate at the boundary.
- **Confidence-based resolver selection, not integer priority.** Each resolver self-reports `confidence(candidate) -> float` per call. Registry sorts descending, tries in order. Adaptive (depends on candidate), self-explanatory (no magic numbers), deterministic. LLM is **not** in the per-resolution loop — only re-enters if all resolvers fail.
- **All async** (most plugins do I/O); **Pydantic** for boundary data; **long-lived** plugin instances with optional `start()/close()`; **explicit kwargs** on `search()` (limit, year_from, year_to, kinds) — no `**filters`; **both** entry-point and local-file plugin discovery.
- **`ResolvedFile.bytes_: bytes`** for v0.1; revisit if we hit memory wall on large artifacts.

PLUGINS.md updated with the locked contracts. Building M1.1 now.

- **Affects**: `docs/PLUGINS.md` (canonical contract); upcoming `src/callimachus/sources/` modules.

### 2026-05-05 — M1.0 storage scaffold green (SQLModel + sqlite-vec + Alembic)

`src/callimachus/storage/` lives. `Work`, `Chunk`, `Collection`, `WorkCollection`, `Run` SQLModel classes; `db.py` opens SQLite and auto-loads `sqlite-vec` on every connect via SQLAlchemy event listener; `vec.py` exposes `insert_chunk_embedding` and `search_chunks` returning typed `SearchHit(work, chunk, distance)` tuples; Alembic baseline migration generated and round-trips clean. 6/6 storage tests pass.

**Lessons captured**:
- `sqlite-vec v0.1.9` loads cleanly on macOS via `sqlite_vec.load(conn)` after `enable_load_extension(True)`. Standard pattern. Wired into the SQLAlchemy `connect` event so it's transparent to callers.
- The `vec_chunks` virtual table is created in `init_db()` (not Alembic) — sqlite-vec virtual tables don't fit Alembic autogenerate. Document this in migration env.py.
- SQLModel deprecates `Session.execute()` in favour of `Session.exec()`, but `exec()` is typed for ORM queries, not raw SQL. **Pattern for raw SQL: `session.connection().execute(text(...), {params})`** — uses the underlying SQLAlchemy connection directly.
- Embedding bytes packed as `struct.pack(f"{N}f", *embedding)`. Dimension is `EMBEDDING_DIM = 768` (nomic-embed-text-v1.5). Changing the embedding model requires rebuilding `vec_chunks`.
- `expire_on_commit=False` is the SQLModel-friendly default for sessions — lets callers read object fields outside the session context (matches FastAPI ergonomics).
- `__tablename__ = "..."` triggers a SQLModel + pyright-strict mismatch (`declared_attr[Unknown]`). Use `# type: ignore[assignment]` on each — known issue in SQLModel + SQLAlchemy 2.0.
- Alembic autogen forgets to import `sqlmodel` in generated migrations. Fixed: added `import sqlmodel` to `script.py.mako`. Also excluded `migrations/versions/` from ruff and pyright (autogen code, not our style).
- pyright's `reportUnusedImport` doesn't honour ruff's `# noqa: F401`. Need `# pyright: ignore[reportUnusedImport]` separately.

- **Affects**: `pyproject.toml` (excludes for autogen migrations), `src/callimachus/storage/`.

### 2026-05-05 — Pivoting from experiments to product (M1 build)

After 6 agent-harness experiments (01–06, with 07 deferred), we paused and reassessed the remaining 24 experiments. Honest answer: the agent-harness phase earned its keep because Pydantic AI was unfamiliar and we found real things (provider swap mechanics, sub-agent budgets, ModelRetry pattern, streaming surfaces, model defaults per role, the chat-vs-dashboard split, the OpenRouter-via-Pydantic-AI gaps). The remaining 24 experiments — TUI, storage, embeddings, six discovery sources, five pipeline pieces, MCP, plugins — are mostly "use a well-documented library, confirm it works as advertised". Low surprise risk; low information-per-experiment ratio.

**Decision**: defer experiments 07–30. Fold into the integration milestones in `DEV_PLAN.md`. When we hit something genuinely uncertain during M1+ work, spin a focused mini-experiment in the moment. Default is "build it and see."

M1 broken into 6 sub-phases (`M1.0` storage scaffold → `M1.5` cost tracking) so each is demonstrable. Starting with M1.0.

- **Affects**: `DEV_PLAN.md` (Phase 2 expanded with M1 sub-phases; direction-change note added to Phase 1).

### 2026-05-05 — Sub-agent delegation works; introduced `experiments/_common.py` logging

Sub-agent delegation via `@orchestrator.tool` wrapping `hunter.run(brief)` works as documented. **Parallel tool calls execute truly in parallel** — orchestrator emits N `ToolCallParts` in one ModelResponse, framework runs hunters concurrently, returns all results in one round-trip from orchestrator's perspective (so orchestrator's own request count stays tiny — ~2). For cases where *we* (not the model) decide what to spawn, `asyncio.gather` over independent `hunter.run()`s gives the same parallelism with explicit control. Both patterns will be used in production: model-driven for orchestrator-led discovery, explicit for fixed sweeps.

**Per-agent budgets**: each sub-agent gets its own `request_limit` when `usage` is NOT shared via `ctx.usage`. We default to `request_limit=15-20` per hunter (loose enough for legitimate query refinement, tight enough to fail fast on real loops). Sub-agent failures (e.g. `UsageLimitExceeded`) should be caught and re-raised as `ModelRetry` so the parent orchestrator can recover gracefully — same convention as source-plugin failures from experiment 02.

**Models for discovery**: Haiku 4.5 for hunters + orchestrator (cheap, fast, plenty good for mechanics), Sonnet 4.6 for the judge (quality matters), Opus 4.7 for end-of-build synthesis.

**Infrastructure win**: introduced `experiments/_common.py` for env loading + Rich logging + canonical model constants (`MODEL_FAST`, `MODEL_SMART`, `MODEL_DEEP`). Convention added to `experiments/README.md`. Cleans up boilerplate; coloured structured logging makes diagnosing future experiments much easier than ad-hoc print.

- **Source**: [`experiments/06-pydantic-ai-sub-agents/LEARNINGS.md`](experiments/06-pydantic-ai-sub-agents/LEARNINGS.md)
- **Affects**: `ARCHITECTURE.md` discovery section (agent default = Haiku, judge = Sonnet, synthesis = Opus); experiments going forward use `_common.py`.

### 2026-05-04 — Streaming validated; chat = prompt_toolkit + Rich (aider pattern), dashboard = Textual

All three Pydantic AI streaming surfaces (`run_stream() + stream_text()`, `agent.iter()`, `agent.run_stream_events()`) work cleanly and feel live. The aider-pattern chat — `prompt_toolkit` for input + `rich.live.Live` + `rich.markdown.Markdown` for streaming output — was judged solid by the user. Native terminal scrollback preserved.

**Architecture decision**: chat and dashboard are different categories. Chat (`calli` librarian) = `prompt_toolkit` + `Rich`. Build dashboard (parallel hunters) = Textual. This split is real and the ARCHITECTURE.md tech stack now reflects it. A future Toad-style fully-Textual chat with side panes is plausible later but not in scope for v0.1.

**Known limitation**: Shift+Enter is terminal-protocol-dependent (CSI u). We send `\x1b[>1u` on startup to ask the terminal to enable disambiguation mode (Claude Code's mechanism), but it didn't activate in the user's Zed terminal in this session. Alt+Enter is the universal multi-line fallback. Future polish: a `calli setup-terminal` analogous to Claude Code's, which writes the right config file per terminal.

**Lessons captured**:
- Don't shadow stdlib module names in experiments (initial `inspect.py` crashed `asyncio`'s import chain).
- prompt_toolkit 3.0.52 lacks `Keys.ShiftEnter`; bind via `ANSI_SEQUENCES["\x1b[13;2u"] = Keys.WindowsMouseEvent` or similar hijack.
- Live re-rendering streamed Markdown sometimes flickers; future optimization possible.

- **Source**: [`experiments/05-pydantic-ai-streaming/LEARNINGS.md`](experiments/05-pydantic-ai-streaming/LEARNINGS.md)
- **Affects**: `ARCHITECTURE.md` (chat = pt+Rich, dashboard = Textual; repo layout updated to add `chat/` directory).

### 2026-05-04 — Provider swap works across 5 model families; Gemini caveat may not apply

Same `Verdict` schema, same fixture, swapped across Claude Sonnet 4.6, Claude Haiku 4.5, GPT-5.1, Gemini 2.5 Pro, and Llama 3.3 70B via OpenRouter. **5/5 returned valid verdicts.** Provider swap is a one-line change as the docs promised. Verdict consistency is high — all four frontier models scored DDPM 10/10/Y/Y; Llama was slightly more conservative at 9/8 but still accepted+snowballed. Notable: GPT-5.1 used ~half the input tokens of Anthropic models (different schema encoding); Gemini was more verbose in output. Surprising: Haiku 4.5 was slowest (21.9s) — needs re-test on a different day before drawing latency conclusions.

**Gemini caveat softened**: Gemini 2.5 Pro returned a valid structured output via the default Tool Output mode. The Pydantic AI docs warning may apply to older Gemini, or the framework auto-handles it, or OpenRouter normalises it. We don't need to pre-emptively code around it. ARCHITECTURE.md updated to soften this claim.

Concern surfacing varies by model: only GPT-5.1 populated `concerns` with useful items; others returned empty. Implication: empty concerns means "no information" rather than "no concerns" — model-dependent.

Default workhorse judge: **Sonnet 4.6**. Cheap-mode option: Llama 3.3 70B. Synthesis pass model TBD.

- **Source**: [`experiments/04-pydantic-ai-provider-swap/LEARNINGS.md`](experiments/04-pydantic-ai-provider-swap/LEARNINGS.md)
- **Affects**: `ARCHITECTURE.md` provider-caveats paragraph (softened); informs default model selection in M2.

### 2026-05-04 — Structured output (judge prototype) works via Tool Output mode

Pydantic AI returns a typed Pydantic model via its **Tool Output mode** by default — the schema becomes a synthetic `final_result` tool that the model "calls" with structured args. Because OpenRouter relays tool calls cleanly, structured output is as reliable as tool calling here (sidestepping older OpenRouter issues with Native JSON mode). Single request, no retries needed. Sonnet 4.6 produced a thoughtful judgment of the Ho 2020 DDPM abstract (relevance=10, seminality=10, accept=True, snowball=True) with full reasoning. Type checks all pass — `int`/`bool`/`list[str]` preserved.

**Caveat to track**: per Pydantic AI docs, Gemini can't combine tools and structured output. If we ever route the judge through Gemini, the LLMProvider wrapper must auto-select `NativeOutput` mode for that path.

Schema design note: `Field(...)` descriptions are sent to the model and function as part of the prompt. Treat them with the same care as system-prompt wording.

- **Source**: [`experiments/03-pydantic-ai-structured-output/LEARNINGS.md`](experiments/03-pydantic-ai-structured-output/LEARNINGS.md)
- **Affects**: `ARCHITECTURE.md` provider abstraction (note Gemini caveat for judge path).

### 2026-05-04 — Tool calling works; ModelRetry is the lever for graceful failure

Pydantic AI's tool loop runs autonomously: type hints + docstring auto-derive the schema; `result.all_messages()` exposes the full exchange. **Parallel tool calls in a single turn work natively** — the orchestrator can fan out to N hunter tools in one round-trip. Important error-handling distinction: plain exceptions from tools propagate to the caller (model never sees them), while `pydantic_ai.ModelRetry("...")` is fed back as a `RetryPromptPart` so the model can recover. Binds: source plugins should use `ModelRetry` for graceful degradation on outages; judge/orchestrator internal failures should `raise` normally for hard fail.

Also: OpenRouter routes through multiple Anthropic backends (direct, Vertex, Bedrock) — `tool_call_id` prefixes vary (`toolu_*`, `toolu_vrtx_*`, `toolu_bdrk_*`). Don't assume the prefix shape.

Cost note: adding one tool with a one-line schema added ~1400 tokens of overhead per request. Implication: keep each agent's toolbox minimal and focused.

- **Source**: [`experiments/02-pydantic-ai-tool-calling/LEARNINGS.md`](experiments/02-pydantic-ai-tool-calling/LEARNINGS.md)
- **Affects**: `ARCHITECTURE.md` (source plugin contract should specify `ModelRetry` for graceful failures), `PLUGINS.md` (mention this in the Resolver/DiscoverySource Protocol docs).

### 2026-05-04 — Pydantic AI hello-world via OpenRouter green; Perplexity also on OpenRouter

`openrouter:anthropic/claude-sonnet-4.6` works as the model string with `pydantic-ai-slim[openrouter]`. `OpenRouterProvider` reads `OPENROUTER_API_KEY` from env automatically. Result API: `result.output` for text, `result.usage()` for tokens (`input_tokens`/`output_tokens`). PEP 723 inline-script metadata + `uv run` validated as the experiment-deps convention. **OpenRouter is the default LLM access pattern**; Anthropic-direct stays available as a config option. Note: OpenRouter uses dot-notation versions (`4.6`); Anthropic-direct uses dash-notation (`4-6`) — naming conventions diverge across providers.

**Bonus**: Perplexity Sonar models (`perplexity/sonar`, `sonar-pro`, `sonar-deep-research`) are available on OpenRouter too. One `OPENROUTER_API_KEY` covers both LLM (Claude) and planning-phase synthesis (Perplexity) — `PERPLEXITY_API_KEY` becomes optional. Mistral OCR stays separate (different product).

- **Source**: [`experiments/01-pydantic-ai-hello/LEARNINGS.md`](experiments/01-pydantic-ai-hello/LEARNINGS.md)
- **Affects**: `ARCHITECTURE.md` (LLM access default + perplexity routing), `README.md` API keys table, `PLUGINS.md` perplexity bundled-plugin description, `.env.example`.

### 2026-05-04 — Phase 0 tooling green

Minimal package skeleton (`src/callimachus/__init__.py` exposing `__version__`) plus dev tooling all pass on first try: `uv sync --group dev`, `ruff check`, `ruff format --check`, `pyright` (strict mode, 0 errors), `pytest` (1 smoke test). Phase 0 of `DEV_PLAN.md` is complete; ready to move into experiment 01 (Pydantic AI hello-world).

- **Affects**: `pyproject.toml` is the source of truth for tool versions and configs. CLAUDE.md captures the coding-style brief (DRY, Pydantic at boundaries, pyright + ruff, tests where they earn their keep, docs-and-code-stay-in-sync as the golden rule).

### 2026-05-04 — env-check passes; stdlib-only is enough for experiments

Smoke test green on macOS / Python 3.14.4. Stdlib `.env` parsing handles the basic case fine; we'll switch to `pydantic-settings` for product code. Repo-root detection convention (`README.md` + `docs/`) established for future experiments to reuse.

- **Source**: [`experiments/00-env-check/LEARNINGS.md`](experiments/00-env-check/LEARNINGS.md)
- **Affects**: nothing binding — confirms baseline assumptions hold.

## Format for entries

```markdown
### YYYY-MM-DD — short title

One- or two-sentence summary of the finding or decision.

- **Source**: `experiments/NN-name/LEARNINGS.md`
- **Affects**: which doc / module / decision this binds (e.g. `ARCHITECTURE.md` chunking, default embedding model, etc.)
```

## Cross-cutting decisions log

A separate, narrower table of decisions that have been made and where they're recorded canonically. Use this to find "what did we decide about X?" without reading every entry.

| Decision | Value | Recorded in |
| --- | --- | --- |
| Minimum Python version | 3.11 | `ARCHITECTURE.md`, `experiments/00-env-check/LEARNINGS.md` |
| `.env` parsing — experiments | stdlib (KEY=VALUE, comments, blanks, optional quotes) | `experiments/00-env-check/LEARNINGS.md` |
| `.env` parsing — product code | `pydantic-settings` | `experiments/00-env-check/LEARNINGS.md` |
| Repo-root detection convention | walk up looking for `README.md` + `docs/` | `experiments/00-env-check/run.py` |
| Type checker | `pyright` strict mode | `pyproject.toml`, `CLAUDE.md` |
| Lint + format | `ruff` (replaces black + isort + flake8) | `pyproject.toml`, `CLAUDE.md` |
| Test runner | `pytest` + `pytest-asyncio`, `asyncio_mode = "auto"`, `-m "not live"` default | `pyproject.toml` |
| Live-API tests | gated behind `pytest -m live`, excluded from default + CI | `pyproject.toml`, `CLAUDE.md` |
| Dev deps style | PEP 735 `[dependency-groups]` (uv-native) over `[project.optional-dependencies]` | `pyproject.toml` |
| Build backend | `hatchling` | `pyproject.toml` |
| Agent harness | Pydantic AI (`pydantic-ai-slim[openrouter]`) | `ARCHITECTURE.md`, `experiments/01-pydantic-ai-hello/LEARNINGS.md` |
| Default LLM access | OpenRouter (one key, many models) | `experiments/01-pydantic-ai-hello/LEARNINGS.md` |
| Perplexity routing | via OpenRouter (`perplexity/sonar-pro`); `PERPLEXITY_API_KEY` is opt-in | `experiments/01-pydantic-ai-hello/LEARNINGS.md`, `experiments/32-perplexity-openrouter/LEARNINGS.md` |
| Perplexity citation field on OpenRouter | `choices[0].message.annotations[*].url_citation` (OpenAI-compat), URL + title only — NOT the flat `citations` field perplexity-direct returns | `experiments/32-perplexity-openrouter/LEARNINGS.md` |
| Serper plugin shape (M2.0a) | one plugin, two modes (`/search` vs `/scholar`); `/scholar` per-result fields map cleanly to WorkCandidate; `citedBy` → seminality signal | `experiments/31-serper-search/LEARNINGS.md` |
| Canonical Sonnet 4.6 model string | `openrouter:anthropic/claude-sonnet-4.6` | `experiments/01-pydantic-ai-hello/LEARNINGS.md` |
| Experiment dependency convention | PEP 723 inline-script metadata, run via `uv run` | `experiments/01-pydantic-ai-hello/LEARNINGS.md` |
| Token field names (Pydantic AI) | `input_tokens` / `output_tokens` (not `request_/response_`) | `experiments/01-pydantic-ai-hello/run.py` |
| Tool decorator | `@agent.tool_plain` (no context) or `@agent.tool` (with `RunContext`) | `experiments/02-pydantic-ai-tool-calling/LEARNINGS.md` |
| Tool schema source | type hints + docstring `Args:` section | `experiments/02-pydantic-ai-tool-calling/LEARNINGS.md` |
| Source plugin error contract | raise `pydantic_ai.ModelRetry("reason")` for graceful degradation; plain exceptions for hard failures | `experiments/02-pydantic-ai-tool-calling/LEARNINGS.md` (to be reflected in `ARCHITECTURE.md` + `PLUGINS.md`) |
| Parallel tool calls | one `ModelResponse` can carry multiple `ToolCallPart`s, executed in parallel by the framework | `experiments/02-pydantic-ai-tool-calling/LEARNINGS.md` |
| Structured output mode | Tool Output (Pydantic AI default) — schema → synthetic `final_result` tool | `experiments/03-pydantic-ai-structured-output/LEARNINGS.md` |
| Gemini caveat for structured output | Gemini can't combine tools + structured output; provider wrapper must auto-select `NativeOutput` mode if Gemini is ever used for the judge | `experiments/03-pydantic-ai-structured-output/LEARNINGS.md` |
| Judge schema (v0) | `relevance: int(0-10)`, `seminality: int(0-10)`, `accept: bool`, `snowball_candidate: bool`, `reasoning: str`, `concerns: list[str]` | `experiments/03-pydantic-ai-structured-output/run.py` (refinement pending in M2/M3) |
| Default workhorse judge model | `openrouter:anthropic/claude-sonnet-4.6` | `experiments/04-pydantic-ai-provider-swap/LEARNINGS.md` |
| Cheap-mode judge alternative | `openrouter:meta-llama/llama-3.3-70b-instruct` (open weights, slightly more conservative scores) | `experiments/04-pydantic-ai-provider-swap/LEARNINGS.md` |
| Gemini structured-output caveat | softened — works in practice with default Tool Output mode for Gemini 2.5 Pro; only special-case if real failures observed | `experiments/04-pydantic-ai-provider-swap/LEARNINGS.md` |
| Chat interface stack | `prompt_toolkit` + `Rich` (aider pattern); inline scrolling, native scrollback preserved | `experiments/05-pydantic-ai-streaming/LEARNINGS.md`, `ARCHITECTURE.md` |
| Build dashboard stack | Textual (multi-pane, real-time hunters) | `ARCHITECTURE.md` |
| Multi-line input convention | Alt+Enter universal; Shift+Enter is terminal-dependent (CSI u protocol) | `experiments/05-pydantic-ai-streaming/LEARNINGS.md` |
| Don't shadow stdlib module names | never use `inspect.py`, `json.py`, `email.py` etc. as filenames | `experiments/05-pydantic-ai-streaming/LEARNINGS.md` |
| Sub-agent budget isolation | each sub-agent gets its own `request_limit` (don't share `usage` via `ctx.usage` unless you want one combined pool) | `experiments/06-pydantic-ai-sub-agents/LEARNINGS.md` |
| Default request_limit per hunter | 15-20 (loose for refinement, tight to fail fast on real loops) | `experiments/06-pydantic-ai-sub-agents/LEARNINGS.md` |
| Sub-agent failure pattern | catch `UsageLimitExceeded` and similar, re-raise as `ModelRetry` so parent recovers gracefully | `experiments/06-pydantic-ai-sub-agents/LEARNINGS.md` |
| Default models for discovery | hunters + orchestrator: Haiku 4.5; judge: Sonnet 4.6; synthesis: Opus 4.7 | `experiments/06-pydantic-ai-sub-agents/LEARNINGS.md` |
| Shared experiments boilerplate | `experiments/_common.py` provides env loading, Rich logging, model constants. Only allowed shared module across experiments. | `experiments/_common.py`, `experiments/README.md` |
| Embedding dimension (default) | 768 (nomic-embed-text-v1.5) — `EMBEDDING_DIM` in `storage/models.py`; changing requires rebuild of `vec_chunks` | `src/callimachus/storage/models.py` |
| Raw SQL pattern in SQLModel | `session.connection().execute(text(...), {params})` — `session.execute()` is deprecated, `session.exec()` is typed for ORM only | `src/callimachus/storage/vec.py` |
| Session ergonomics | `expire_on_commit=False` default in `make_session()` — objects usable after commit | `src/callimachus/storage/db.py` |
| Alembic autogen quirks | Add `import sqlmodel` to `script.py.mako`; exclude `**/migrations/versions/` from ruff + pyright (autogen code) | `pyproject.toml`, `src/callimachus/storage/migrations/script.py.mako` |
| `vec_chunks` virtual table | Created in `init_db()`, not Alembic — virtual tables don't fit autogenerate | `src/callimachus/storage/db.py` |
| `__tablename__` + pyright strict | Use `# type: ignore[assignment]` per assignment — SQLModel + SQLAlchemy 2.0 known mismatch | `src/callimachus/storage/models.py` |
| Plugin contract style | `typing.Protocol` + `@runtime_checkable`; plugins don't inherit | `src/callimachus/sources/protocols.py`, `docs/PLUGINS.md` |
| Resolver selection | confidence-based (per-call `confidence(candidate) -> float`), not integer priority | `src/callimachus/sources/protocols.py`, `docs/PLUGINS.md` |
| Plugin failure protocol | raise `callimachus.sources.SourceUnavailable` (recoverable) or normal `Exception` (hard fail). Agent boundary translates to `ModelRetry`. | `docs/PLUGINS.md` |
| Local plugin location | `<library_root>/plugins/` (default `~/Callimachus/plugins/`) | `src/callimachus/sources/registry.py` |
| Plugin Protocol attribute typing | export `SourceKind` / `WorkKind` from the package; plugins use them in attribute and parameter declarations to satisfy invariant Literal types | `src/callimachus/sources/protocols.py` |
