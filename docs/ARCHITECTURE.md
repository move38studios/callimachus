# Architecture

This document is structured in two halves: **Part 1** describes what's actually built and how the code is organized today (M1 + M2). **Part 2** describes the planned architecture for milestones we haven't reached yet (M3 chat, M4 snowball + dashboard, M5 MCP, M6 polish).

If you're new, [`ONBOARDING.md`](ONBOARDING.md) is the right starting point. This doc is the deeper reference for *why* the code looks the way it does and *how* future pieces are intended to plug in.

---

## Goals and non-goals

**Goals (long-lived):**

- Be a long-lived **personal librarian**, not a one-shot build tool — a library grows, gets pruned, gets refreshed, gets cross-pollinated over time
- Produce a deep, curated, queryable library of research on any number of related topics with a single command
- Discover the seminal works *and* the recent grey literature, across both bibliographic databases and the wider web
- Snowball through citations the way a good researcher would, with LLM-driven judgment
- Output a self-contained directory — portable, inspectable, version-controllable
- Support multiple LLM providers so users aren't locked into a single vendor
- Make the agentic phase feel alive: streaming output, progress per paper
- Make chat the dominant interface, with CLI shortcuts as typed equivalents
- Make every library queryable from any chat agent via MCP

**Non-goals (v0.1):**

- Real-time / continuously-refreshing libraries (refresh is on-demand)
- Multi-user / collaborative libraries (single-user; explicit merging is v0.3)
- Audio/video sources (deferred to v0.2)
- Hosted / SaaS deployment

---

# Part 1: As built (M1 + M2)

## Mental model

| Concept | Today | Planned |
|---------|-------|---------|
| **Library** | A directory containing `library.db`, `works/`, `archive/`, `plugins/`, `.callimachus/`. Default `~/Callimachus/`. One per user. Multiple supported via `CALLIMACHUS_LIBRARY` env or `--library` flag. | Same. |
| **Work** | A paper (today: arxiv preprints, Unpaywall-resolvable DOIs). Lives at `works/{slug}/` with `original.{pdf,tar.gz}`, `paper.md`, `summary.md`, `metadata.yaml`. Indexed in `library.db`. | Add essays, reports (via plugins). Add talks, chapters in v0.2. |
| **Collection** | Schema exists (`collections` table). Not used yet; a library has one implicit collection. | M4 — multi-collection within one library; bridge papers (high relevance in 2+ collections). |
| **Run** | A single mutating operation. Today: only `kind="build"` runs exist. Schema supports extend, refresh, prune, rejudge, restore. Every Work carries `admitted_by_run_id`. | Other run kinds populate as M3+ mutations land. |
| **Plan** | The frozen artifact of the M2 ceremony. Persisted as YAML at `.callimachus/plans/<slug>.yaml`. Reviewable + editable before deep build. | Same. |
| **Callimachus** | The librarian agent persona. Doesn't exist as code yet — comes in M3. | M3 builds the agent + chat REPL. |

## The architecture today

```
┌─────────────────────────────────────────────────────────────────────────┐
│  calli build --topic X                                                  │
│    ─────────────────────────────────────────────────────────────────    │
│    DISCOVERY (agentic, M2)         │  INGEST (deterministic, M1)        │
│                                    │                                    │
│    scout (LLM + OpenAlex probe)    │  for each accepted candidate:      │
│      → AngleTree                   │    resolve  (arxiv | unpaywall)    │
│                                    │      → ResolvedFile                │
│    ceremony (HITL Q&A)             │    download → bytes on disk        │
│      → Plan                        │    extract  (LaTeX | OCR)          │
│                                    │      → markdown                    │
│    orchestrator                    │    enrich   (LLM)                  │
│      ├─ N hunters (parallel)       │      → metadata.yaml + summary.md  │
│      │    Pydantic AI sub-agent    │    chunk                           │
│      │    tools per source         │    embed    (nomic, local)         │
│      ├─ dedupe + filter            │    index    (Work + chunks +       │
│      ├─ judge (parallel, capped)   │             vec_chunks)            │
│      └─ ingest each accepted       │                                    │
│                                    │                                    │
│    Run row finalised               │                                    │
└─────────────────────────────────────────────────────────────────────────┘
```

The split is intentional: **discovery is agentic** (LLMs make decisions about what to search and what to keep), **ingest is deterministic** (a fixed pipeline of stages, each idempotent, each testable in isolation). The orchestrator stitches them together.

## Tech stack

| Layer | Choice | Why |
|-------|--------|-----|
| Language | Python 3.11+ | PDF/embeddings ecosystem is Python-native |
| Package manager | `uv` | Fast, reproducible, no `requirements.txt`/`venv` dance |
| Agent harness | **Pydantic AI** | Multi-provider, mature, agent-delegation primitives, structured outputs via Pydantic, `TestModel` for unit tests |
| LLM access | OpenRouter (one key, many models) | Per-role defaults: scout = Haiku 4.5 (one-shot generation); hunter + judge + enricher = Sonnet 4.6 (decision quality); end-of-build synthesis (M4+) = Opus 4.7. `--hunter-model` flag overrides |
| Storage | **SQLite + sqlite-vec** | One file you can copy. Vector + structured in one place. Sub-100ms queries up to ~50k chunks |
| ORM | **SQLModel + Alembic** | Pydantic-typed models double as agent tool I/O. Real migrations |
| Embeddings (default) | `nomic-embed-text-v1.5` (local, sentence-transformers) | Open weights, no key, ~500MB, runs on CPU |
| PDF → markdown | LaTeX (pylatexenc, with crude regex fallback) → Mistral OCR | LaTeX is cleanest when arxiv has source. Mistral OCR is cheap+good for the rest. Vision fallback deferred |
| CLI | Typer | Modern, type-driven, decent help generation |
| Output rendering | Rich | Streaming text, panels, tables. Used during build progress |
| Discovery & resolvers | **Plugin system** (see [`PLUGINS.md`](PLUGINS.md)) | Bundled plugins use the same Protocols a third-party plugin would |

### Why Pydantic AI over the Anthropic SDK directly

Pydantic AI gives us multi-provider support, mature agent + sub-agent primitives, structured-output-as-Pydantic-models, and `TestModel` for unit tests — all in a tested framework we don't maintain. The Anthropic SDK would force us to roll our own retry, structured output, and test infrastructure, and lock us to one vendor. Pydantic AI's overhead (~100ms per agent run startup, slightly thicker stack traces) is worth it.

If you've never used Pydantic AI before, the ONBOARDING doc has a primer. The short version: an `Agent` wraps a model + tools + structured output type; you call `await agent.run(prompt, deps=…)` and get a typed `result.output` back.

### Why SQLite + sqlite-vec + SQLModel

A library should be **one file you can copy**. SQLite gives that. `sqlite-vec` (the successor to sqlite-vss) is mature and fast at our scale. Universal tooling: Datasette gives a free web UI, every language has a driver.

SQLModel sits on top of SQLAlchemy with Pydantic models — the same models double as the librarian agent's tool I/O when M3 lands. Alembic handles migrations because the schema *will* evolve.

### Why the deterministic / agentic split

Every step that can be deterministic is deterministic — download, extract, enrich (single LLM call per paper), chunk, embed, index. This makes ingest cheap to reason about, fast to test (mock the LLM, the rest runs end-to-end on disk in <1s), and re-runnable.

The agentic part is concentrated in discovery: the scout decides what angles to probe, the hunter decides what queries to issue across what sources, the judge decides what to keep. That's where the variance lives. The orchestrator coordinates but doesn't itself use an LLM.

## The bundled plugin set

Six discovery sources, three resolvers, all entry-point-registered in `pyproject.toml` and loaded by `src/callimachus/sources/registry.py`.

**Discovery sources:**

| Plugin | Kind | Notes |
|--------|------|-------|
| `arxiv` | preprint | Atom API. 1 req/3s rate-limit lock per plugin instance. Doubles as resolver. |
| `openalex` | bibliographic | ~250M-work catalogue, no auth. Polite-pool email recommended (`OPENALEX_MAILTO`). The scout's probe source for evidence-backing each angle. |
| `serper_scholar` | bibliographic | Google Scholar via Serper API. Needs `SERPER_API_KEY`. |
| `serper_web` | web | General Google search. Auto-disabled by `calli build` for academic libraries (the `require_resolvable_id` filter would drop blog posts anyway). |
| `perplexity` | bibliographic | Natural-language queries via OpenRouter (`perplexity/sonar-pro`). Citations come back as `(url, title)` pairs; we extract arxiv_id or DOI per URL. Reuses `OPENROUTER_API_KEY`. |
| `local_pdfs` | vault | Configure with paths to scan. Doubles as resolver. |

**Resolvers:**

| Plugin | Confidence | Notes |
|--------|-----------|-------|
| `arxiv` | 1.0 if `arxiv_id` set, else 0.0 | LaTeX source preferred (cleanest extraction), PDF fallback. |
| `unpaywall` | 0.7 if `doi` set, else 0.0 | Lower than arxiv so arxiv wins on overlap. Browser-like User-Agent for the PDF fetch step (some publishers 403 our polite-pool UA). |
| `local_pdfs` | 1.0 if a matching local file exists, else 0.0 | Title-fingerprint matching. |

The registry sorts resolvers by descending confidence per call and tries them in order; first success wins. `SourceUnavailable` from one resolver moves on to the next; if all return confidence 0 or fail, the candidate is dropped from this run.

## M2 components in detail

`src/callimachus/discovery/` has six modules, each ~200 lines.

### `plan.py` — the build-plan artifact

Pydantic models: `Angle`, `AngleTree`, `Plan`. YAML serialization. `slugify()` makes filename-safe identifiers from topic strings. Plans persist at `<library>/.callimachus/plans/<slug>.yaml` so users can review/edit before kicking off the deep build (terraform plan/apply pattern).

### `scout.py` — topic → AngleTree

Two-stage. Stage 1: one Haiku call generates 5-8 angle hypotheses + adjacent-field suggestions. Stage 2: parallel OpenAlex probes attach real evidence (sample titles + hit counts) per angle. The scout never decides what to keep; it shows the user what exists so the ceremony can lock in a Plan.

Probe failures per angle are swallowed (logged, returned with no sample evidence). Hypothesis-stage failure propagates.

### `ceremony.py` — HITL Q&A → Plan

Four questions: which angles matter, anchor keywords/authors, orientation (foundations / recent / both), max-works cap. The `Prompter` Protocol lets the CLI use `CliPrompter` (input/print) and tests use `QueuedPrompter` (canned answers). `auto_plan()` short-circuits the whole ceremony for hands-off mode.

`parse_*` helpers (`parse_angle_selection`, `parse_keywords`, `parse_orientation`, `parse_max_works`) are pure and parameterised-tested.

### `judge.py` — single LLM call, structured Verdict

`Verdict { accept: bool, score: 0-1, reasoning: str, notes: str | None }`. One Sonnet call per candidate. Auto-rejects candidates with no title or no source URL before calling the LLM. The `JudgeFn` callable abstraction lets tests pass a stub.

### `hunter.py` — Pydantic AI sub-agent per angle

The hunter is built per-call by `make_hunter_agent(enabled_sources=…)`. It registers one `search_<source_name>` tool per discovery source. Tool returns are compact text (`"openalex['x'] → 18 hits, 12 new"`); full WorkCandidate objects accumulate in deps-scoped state keyed by `candidate_id` so duplicates collapse for free.

`SourceUnavailable` from any tool is wrapped to `pydantic_ai.ModelRetry` so the agent can recover by switching sources. Per-hunter `UsageLimits(request_limit=20)`. Tool retry budget is 4 (raised from default 1 after seeing arxiv 503s eat whole hunters in early runs).

The hunter does **no LLM judgment** — it gathers, dedupes, and applies a deterministic rank (pdf > abstract > year > authors, citation count breaks ties). The judge module decides accept/reject downstream.

### `orchestrator.py` — Plan → indexed library

`run_build(plan, *, session, judge_fn, hunt_fn, ingest_fn, …)` is the entry point. Flow:

1. Create `Run` row (`kind="build"`)
2. Fan out one hunter per angle in parallel via `asyncio.gather`
3. Aggregate + dedupe candidates by `candidate_id`
4. Filter to candidates the resolver chain can fetch (`require_resolvable_id`: arxiv_id OR doi)
5. Judge with bounded concurrency (default 5 parallel calls)
6. Sort accepted by score desc; iterate down the list until we hit `plan.max_works` *successes* (not attempts), with a max-attempts cap (default 2× max_works) so a high-failure-rate run doesn't go forever
7. After each successful ingest, patch the `Work` row with `judge_score`, `judge_reasoning`, `admitted_by_run_id`
8. Finalize the `Run` row with `ended_at`, `works_added`, and a JSON `notes` blob containing per-stage stats

`hunt_fn`, `judge_fn`, `ingest_fn` are injected callables — `make_hunt_fn`, `make_default_judge`, `make_ingest_fn` wire the real defaults; tests pass stubs that hit a real SQLite + sqlite-vec session without touching LLMs or disk.

## The pipeline (M1 deterministic stages)

`src/callimachus/pipeline/`. Each stage is a pure function (or async fn for I/O); each is idempotent on its own; the per-paper `ingest_one` orchestrates them sequentially.

| Stage | Module | Inputs → Outputs |
|-------|--------|------------------|
| Resolve | `sources/registry.py::SourceRegistry.resolve` | `WorkCandidate` → `ResolvedFile` (bytes + content_type) |
| Download | `pipeline/download.py` | `ResolvedFile` → bytes on disk under `works/{id}/` |
| Extract | `pipeline/extract.py` | LaTeX archive or PDF → `paper.md` (markdown) |
| Enrich | `pipeline/enrich.py` | markdown → `Enrichment` (Pydantic) → `metadata.yaml` + frontmatter prepended to `paper.md` + `summary.md` |
| Chunk | `pipeline/chunk.py` | markdown → `list[MarkdownChunk]` (~2000 chars, paragraph-aware, section-tracked) |
| Embed | `pipeline/embed.py` | chunks → 768-d vectors (`Embedder` Protocol; `NomicEmbedder` is the default) |
| Index | `pipeline/index.py` | candidate + enrichment + chunks + embeddings → `Work` row + `Chunk` rows + `vec_chunks` virtual-table entries |

**Extract notes:**
- arxiv LaTeX: pylatexenc preferred. Falls back to a crude regex stripper if pylatexenc crashes (seen on certain `\href` patterns) — lossy but never crashes the build.
- PDF: routed to the configured `OcrProvider`. `MistralOcr` is the bundled implementation (uploads via signed URL → `ocr.process` → returns markdown + base64 images).
- Images extracted by OCR are written under `works/{id}/images/` with markdown refs rewritten.

**Enrichment** is one LLM call per paper (Sonnet 4.6 default). Returns title, authors, year, venue, summary, key_claims, methods, datasets, keywords. Renders as YAML frontmatter that gets prepended to `paper.md` (Jekyll/Obsidian compatible).

**Chunking** is paragraph-aware with sliding overlap. We prepend a Contextual Retrieval lite header (`[Paper: title] [Section: section]\n\n`) at embed-time only — the prompt context steers the embedding without bloating storage.

**Embeddings** prefix is `search_document:` for indexed text, `search_query:` for queries (nomic convention, mandatory).

## Storage schema

Single SQLite file (`library.db`) with `sqlite-vec` loaded on connection. SQLModel classes in `src/callimachus/storage/models.py`. Alembic migrations in `src/callimachus/storage/migrations/`.

Tables actually used today:

```sql
-- Works: papers, essays, reports
CREATE TABLE works (
  id              TEXT PRIMARY KEY,        -- canonical slug, e.g. arxiv-2006-11239
  kind            TEXT NOT NULL,           -- paper | essay | report (talk + chapter in v0.2)
  doi             TEXT UNIQUE,
  arxiv_id        TEXT,
  title           TEXT NOT NULL,
  authors         JSON NOT NULL,           -- [{name, orcid?, affiliation?}, ...]
  year            INTEGER,
  venue           TEXT,
  abstract        TEXT,
  summary         TEXT,
  key_claims      JSON,
  methods         JSON,
  datasets        JSON,
  source_url      TEXT NOT NULL,           -- for rehydration
  pdf_path        TEXT,                    -- relative to library root, NULL if rehydrated-out
  markdown_path   TEXT NOT NULL,
  judge_score     REAL,
  judge_reasoning TEXT,
  added_at        TIMESTAMP,
  admitted_by_run_id INTEGER REFERENCES runs(id),
  archived_at     TIMESTAMP,               -- soft-delete; NULL means active
  bridge          BOOLEAN DEFAULT 0,       -- M4: high relevance in 2+ collections
  extra           JSON                     -- catch-all
);

-- Chunks for vector search
CREATE TABLE chunks (
  id       INTEGER PRIMARY KEY,
  work_id  TEXT REFERENCES works(id),
  ord      INTEGER,
  text     TEXT,
  section  TEXT
);

CREATE VIRTUAL TABLE vec_chunks USING vec0(
  chunk_id   INTEGER PRIMARY KEY,
  embedding  FLOAT[768]
);

-- Run history (every mutation is a Run)
CREATE TABLE runs (
  id              INTEGER PRIMARY KEY,
  kind            TEXT,                    -- build | extend | refresh | prune | rejudge | restore
  collection_id   TEXT REFERENCES collections(id),
  started_at      TIMESTAMP,
  ended_at        TIMESTAMP,
  config          JSON,
  cost_usd        REAL DEFAULT 0,          -- vestigial column; not populated (no USD math)
  works_added     INTEGER,
  works_archived  INTEGER,
  works_retagged  INTEGER,
  notes           TEXT                     -- JSON blob: per-stage stats, errors
);
```

Tables that exist but aren't used yet (M4):

```sql
CREATE TABLE collections (...)             -- multi-collection
CREATE TABLE work_collections (...)        -- many-to-many works ↔ collections
```

Vector search (used by `calli query` and the librarian's `search_library` tool):

```sql
SELECT works.title, works.summary, distance
FROM vec_chunks
JOIN chunks ON chunks.id = vec_chunks.chunk_id
JOIN works ON works.id = chunks.work_id
WHERE embedding MATCH ? AND k = 20 AND works.archived_at IS NULL
ORDER BY distance;
```

## Folder layout — what's on disk today

```
~/Callimachus/                       # default library, configurable via CALLIMACHUS_LIBRARY
  library.db                         # SQLite + sqlite-vec
  works/
    arxiv-2006-11239/
      original.tar.gz                # or original.pdf
      paper.md                       # full text + YAML frontmatter
      summary.md
      metadata.yaml                  # full enrichment
      images/                        # only when OCR extracted images
  collections/                       # M4: per-collection folders
  archive/                           # M3+: soft-deleted works
  plugins/                           # local plugin .py files (auto-loaded by registry)
  .callimachus/
    plans/<slug>.yaml                # M2: build plans, reviewable + editable
```

## CLI commands today

```
calli init [path]                    # create library + DB
calli ingest <seed.yaml>             # M1: manual ingest from a YAML list of identifiers
calli build --topic X                # M2: scout + ceremony → plan.yaml
calli build --from-plan <slug>       # M2: orchestrator runs the plan
calli build --topic X --auto         # M2: skip ceremony, run with sensible defaults
calli build --hunter-model <id>      # override hunter LLM (default: openrouter:anthropic/claude-sonnet-4.6)
calli query "..."                    # vector search; -k N for top-k, -L PATH for library
calli list                           # all works in library
```

Helper flags on most commands: `-L PATH` / `--library PATH`, `-v` / `--verbose`.

## Logging and run transparency

Standard `logging` throughout. The CLI configures a Rich handler at INFO (default) or DEBUG (`-v`). Noisy third-party libraries (httpx, openai, anthropic) are quieted to WARNING unless verbose.

What's instrumented today:
- Per-paper progress lines during ingest (`[i/N] ingesting (score=0.92) <title>`)
- Per-hunter start/done lines with token + request counts
- Final summary panel: works added, attempts, judge-accept count, hunter token totals
- Run row in `library.db` with `notes` JSON containing all of the above

What's not instrumented yet:
- Judge token usage (only hunter tokens are summed)
- `calli log` command for run history
- Per-source candidate-contribution metrics

---

# Part 2: Future architecture (M3+)

These sections describe how planned milestones will plug into the architecture above. Treat them as design intent — implementation may diverge as we hit reality.

## M3 — Chat with your library

The librarian is a long-lived Pydantic AI agent that owns the library and exposes a tool surface. The chat REPL (`calli chat`), the existing one-shot `calli query`, and (M5) the MCP server are all invocations of this agent.

### Tool surface (planned)

**Read tools** (always exposed):

| Tool | Purpose |
|------|---------|
| `search_library(query, k=10, filters?)` | Semantic search; filters by year, venue, kind |
| `get_work(id)` | Full metadata + summary |
| `get_work_full(id)` | Full markdown |
| `find_related(id, k=10)` | Embedding-based related works |
| `summarise_topic(query)` | Topic-scoped synthesis across the whole library |
| `cite(query)` | BibTeX entries for top-k matches |
| `library_summary()` | Library-level overview (used at chat startup) |
| `inspect_work(id)` | Metadata + judge reasoning + run history |

**Mutation tools** (gated, off by default for MCP; on for local chat):

| Tool | Purpose |
|------|---------|
| `prune(filter)` | Soft-delete via `archived_at` |
| `restore(filter)` | Undo prune |

Full extend / refresh / rejudge tools wait for M4 (they need the discovery agent + collection schema).

### Chat REPL

`prompt_toolkit` for input (multi-line, history, completion, key bindings, editor escape) + `Rich` for output (`Live` + `Markdown` for streaming-markdown rendering). The aider stack — validated in `experiments/05`. Native terminal scrollback preserved (the dominant complaint about Textual/Ink-based chat tools that take the alt-screen).

Welcome screen on `calli chat` shows the `library_summary()` output: work count, last build date, top topics. Slash commands `/help`, `/clear`, `/save`, `/exit`.

## M4 — Snowball + multi-collection + dashboard

### Snowball loop

```python
seeds = top_n_by_score(library, n=15)

while budget_remains and not_converged:
    candidates = pool from refs(seeds) ∪ forward_cites(seeds)
    candidates = enrich_with_citation_contexts(candidates, current_library)
    candidates = dedupe(candidates)

    verdicts = batch_judge(candidates, collection_context)
    accepted = [c for c, v in verdicts if v.accept]
    new_seeds = [c for c, v in verdicts if v.snowball_candidate]

    library.add(accepted, run_id=current_run)
    seeds = new_seeds[:max_new_seeds_per_iteration]

    convergence = (accept_rate < 15%) for 2 consecutive iterations
    drift = topic_drift_check(accepted, collection.embedding)
    if drift > threshold:
        prune_drifting_branch(accepted)
```

Two important guards:

- **Selective seed promotion** — not every accepted work becomes a seed. Only those scoring high on seminality. Otherwise snowball explodes into noise.
- **Topic drift detector** — periodically embed newly accepted works, compare to the collection embedding. Drift over threshold → prune the branch.

Requires the **`semantic_scholar`** plugin (citation contexts — the literal sentences each citation appears in, the unlock for seminality judging) and **`crossref`** (DOI metadata at scale). Both deferred from M2.

### Multi-collection

A library has one or more collections. A work can belong to multiple collections with per-collection relevance scores. **Bridge works** score high in two or more collections.

`calli collection add "name" --keywords "..."` extends an existing library. The discovery run reads the existing library context, refuses to re-add known works, *will* re-tag existing works for the new collection. A bridge pass explicitly looks for works scoring high on two collection embeddings.

### Build dashboard (Textual)

Multi-pane TUI: orchestrator pane + parallel hunter panes + live works list + status bar. Replaces today's streaming-log Rich progress for `calli build`. The `experiments/09` and `experiments/10` slots in the dev plan are reserved for this.

The chat (M3) and the dashboard (M4) are deliberately different tools: chat is conversational, dashboard is spatial + concurrent. Both are valid Python TUI; they don't share a framework.

## M5 — MCP server

`calli serve --mcp` exposes the librarian's read tools (and optionally mutation tools) over the FastMCP stdio transport. Once registered with Claude Code / Cursor / Claude Desktop / any MCP host, the library becomes a first-class tool the host's chat agent can call.

```python
# sketch
from fastmcp import FastMCP

mcp = FastMCP("callimachus")

@mcp.tool()
async def search_library(query: str, k: int = 10) -> list[Work]:
    ...

@mcp.tool()
async def find_related(work_id: str, k: int = 10) -> list[Work]:
    ...
```

Mutation tools default to off over MCP. `calli serve --mcp --allow-mutations` opts in.

Cross-library bridge (`calli bridge LIB_A LIB_B`) is also M5 — read-only over both libraries, produces a markdown report of intersection ideas.

## M6 — Polish + ship v0.1

- **`calli log`** + **`calli inspect <work>`** for first-class run + work introspection
- **Backup / sharing**:
  - Tier 1 (default): git-friendly — `.gitignore` excludes PDFs + state.json; `calli rehydrate` re-downloads from `source_url`
  - Tier 2: full snapshot via `calli export` / `calli import`
  - Tier 3: git LFS, documented in `docs/BACKUP.md`
- **Library config file** (`callimachus.yaml`) for per-library plugin enables/disables, source-specific config, model overrides
- **`calli plugin {list,install,enable,disable,doctor}`** CLI
- **Resume after crash** — surface in-progress runs at startup, offer to resume

## Future phases (v0.2+)

**v0.2: Talks + book chapters as new work kinds**
- YouTube via yt-dlp + Whisper for transcription
- Book chapters via TOC parsing + chapter-aware extraction
- Same enrichment + embedding + index pipeline
- New `kind` values: `talk`, `chapter` with `parent_work` for chapters

**v0.3+: Collaborative libraries, library-of-libraries, in-place reading UI**

## Provider abstraction (notes for when we generalize beyond OpenRouter)

LLM calls today route through Pydantic AI's OpenRouter provider. To add Anthropic-direct, OpenAI-direct, Gemini-direct, etc., it's a config change — Pydantic AI implements all of them.

Provider-specific caveats the wrapper would need to handle:
- **Gemini + structured output**: Pydantic AI's docs warn that Gemini can't combine tools and structured output. In practice (experiment 04) Gemini 2.5 Pro routed via OpenRouter returned a valid structured `Verdict` with default `ToolOutput` mode, so the warning may not apply to current Gemini versions. **Don't pre-emptively code around it** — if real failures show up when routing the judge through Gemini, the wrapper switches that path to `NativeOutput` or `PromptedOutput` mode at that point.
- **Anthropic prompt caching**: applies transparently when routing direct; not exposed via OpenRouter as of this writing. Worth revisiting if costs become a concern.

---

## Open questions to revisit during build

These are things we're aware of but haven't decided yet. Some surface in `LEARNINGS.md` entries as we hit them.

- **Default snowball depth and convergence thresholds** — needs tuning against real topics in M4
- **Dedupe across arXiv preprint vs published version** — DOI mapping is imperfect
- **Best chunking strategy for academic papers** — semantic vs sliding-window vs section-aware (we have section-aware now; bake-off deferred)
- **Citation graph rendering in chat** — text-based vs terminal graphics
- **Per-collection model overrides** (e.g. use Opus for "creativity", Sonnet for everything else)
- **Library size cap** — when does sqlite-vec performance demand a migration to LanceDB? (~50k chunks suspected)
- **Judge calibration** — current Sonnet judge has ~55% accept rate, probably too lenient. Could be tighter.
- **Per-publisher resolver tactics** — ACM/Elsevier/MDPI 403 the Unpaywall fetch even with browser UA. Worth pursuing?
- **Token budget caps** — `--budget-tokens N` would be a useful guard before users get a surprise bill
