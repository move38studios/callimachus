# Architecture

## Goals and non-goals

**Goals**

- Be a long-lived **personal librarian**, not a one-shot build tool — a library grows, gets pruned, gets refreshed, gets cross-pollinated over time
- Produce a deep, curated, queryable library of research on any number of related topics with a single command
- Discover the seminal works *and* the recent grey literature, across both bibliographic databases and the wider web
- Snowball through citations the way a good researcher would, with LLM-driven judgment
- Output a self-contained directory — portable, inspectable, version-controllable
- Support multiple LLM providers so users aren't locked into a single vendor
- Make the agentic phase feel alive: streaming TUI with parallel hunter subagents
- Make chat the dominant interface, with CLI shortcuts as typed equivalents
- Make every library queryable from any chat agent via MCP

**Non-goals (v0.1)**

- Real-time / continuously-refreshing libraries (refresh is on-demand)
- Multi-user / collaborative libraries (single-user; explicit merging is v0.3)
- Audio/video sources (deferred to v0.2)
- Hosted / SaaS deployment

## Core concepts

| Concept | Definition |
| --- | --- |
| **Library** | A directory containing everything Callimachus needs. Default `~/Callimachus/`. One per user is the encouraged pattern; multiple are supported via `--library`. |
| **Collection** | A coherent subject within a library, with first-class identity: scope, embedding, overview, seed works, README. |
| **Work** | A research artifact: paper, essay, report (later: talk, chapter). Belongs to one or more collections with per-collection relevance scores. |
| **Bridge work** | A work scoring high in two or more collections — the cross-pollination payoff. |
| **Run** | A single mutating operation on a library (build, extend, refresh, prune, re-judge). Every work carries the run that admitted it. |
| **Callimachus** | The librarian agent — the persona you talk to, who can read, query, mutate, extend, refresh, explain. |

## The two-and-a-half-phase architecture

### Phase 1 — Discovery (agentic)

Callimachus the orchestrator plans the run, spawns parallel hunter subagents to search from different angles, judges every candidate against the collection scope, and runs a snowball loop through citation graphs until convergence or budget cap.

This is the phase the user *watches* in the TUI. It feels like a team of researchers working on your behalf.

### Phase 2 — Pipeline (deterministic)

Once discovery converges, accepted works feed a deterministic pipeline: download, extract to markdown, enrich (summaries + structured metadata), embed, index. Async with progress bars.

### Phase 2.5 — Synthesis (small agentic pass)

After the pipeline, a small agentic pass updates collection-level overview documents and (for builds that touched bridges) the cross-collection synthesis. Single-shot, cheap, optional.

### Phase 3 — Continuous (Callimachus is now your librarian)

After the build, the same Callimachus agent is available for chat, query, extend, refresh, prune, and any other mutation or read. Same agent, same primitives, longer-lived.

## Tech stack

| Layer | Choice | Why |
| --- | --- | --- |
| Language | Python 3.11+ | PDF/embeddings ecosystem is Python-native |
| Package manager | `uv` | Fast, reproducible, increasingly standard |
| Agent harness | **Pydantic AI** | Multi-provider, mature, agent-delegation primitives, structured outputs via Pydantic |
| LLM access (default) | OpenRouter (one key, many models). Per-role defaults: hunters + orchestrator = `anthropic/claude-haiku-4.5` (cheap, fast, plenty good for harness mechanics); judge = `anthropic/claude-sonnet-4.6` (quality matters for relevance/seminality scoring); end-of-build synthesis = `anthropic/claude-opus-4.7`. | Cost-optimized routing — Haiku for high-volume mechanics, Sonnet for nuanced judgment, Opus only for the final pass. Matches open-source positioning. |
| LLM access (alternatives) | Anthropic-direct, OpenAI-direct, Gemini-direct, local via Ollama | All supported through Pydantic AI's per-provider integrations |
| Chat interface | **prompt_toolkit + Rich** (aider pattern) | Inline scrolling chat with streaming markdown; native terminal scrollback preserved; lightweight; matches what 2026 chat-first CLIs (aider, gptme) converge on |
| Build dashboard | **Textual** | Multi-pane, async-native, real-time updates; right tool for the parallel-hunters dashboard where spatial layout matters |
| Storage | **SQLite + sqlite-vec** | One file, universal tooling, vector + structured in one place |
| ORM | **SQLModel + Alembic** | Pydantic-typed models, async support, proper migrations |
| MCP server | **FastMCP** | Decorator-based, async-native, stdio + HTTP, the de-facto standard |
| Embeddings (default) | `nomic-embed-text-v1.5` (local, sentence-transformers) | Open weights, no key, ~500MB, runs on CPU |
| Embeddings (opt-in) | Voyage AI `voyage-3` | Higher retrieval quality if user has a key |
| PDF → markdown | arXiv LaTeX → Mistral OCR → Claude vision (fallback) | LaTeX is cleanest when available; Mistral OCR is cheap+great; vision for edge cases |
| Discovery & resolvers | **Plugin system** (see [`PLUGINS.md`](PLUGINS.md)) | Bundled: OpenAlex, Semantic Scholar, arXiv, Crossref, Unpaywall, Exa, Perplexity, local PDFs. Community-extensible. |

### Why Pydantic AI over Claude Agent SDK

Claude Agent SDK has the slickest agentic ergonomics, but Anthropic's Terms prohibit third-party developers from offering Claude.ai subscription auth, and the SDK is Claude-only. For an open-source tool we want users to plug in whatever model they have access to (Claude API, OpenAI, OpenRouter, local models). Pydantic AI gives us multi-provider support, mature agent + delegation primitives, and clean Pydantic-typed structured outputs, at the cost of some Claude-specific niceties (built-in MCP client, automatic compaction, sub-agent isolation). Those gaps are well-defined and easy to fill in our own code.

### Why prompt_toolkit + Rich for chat (and not Textual)

The chat interface — the `calli` librarian you talk to over months — is conversational, not spatial. The 2026 reference for this category is aider's stack: **`prompt_toolkit` for input** (multi-line, history, completion, key bindings, editor escape) plus **`Rich` for output** (`Live` + `Markdown` for streaming-markdown rendering, syntax-highlighted code blocks). This pattern preserves native terminal scrollback — copy/paste, search, pipe — which is the single most-mentioned complaint about Textual/Ink-based chat tools that take the alt-screen and lose history on quit. Validated in experiment 05.

### Why Textual for the build dashboard

Pydantic AI streams events; Textual renders them. Built-in support for split panes, live tables, scrolling logs, keyboard shortcuts, mouse, async. The discovery dashboard — orchestrator pane, parallel hunter panes, live works list, status bar — is spatial and concurrent. Textual's sweet spot. The user watches this for the duration of a build run, not ambiently.

The two tools serve genuinely different use cases — one conversation, one dashboard — and the docs treat them as such. A future Toad-style fully-Textual chat with citation/works-list panes is plausible but not in scope.

### Why SQLite + sqlite-vec + SQLModel

A library should be **one file you can copy**. SQLite gives that. `sqlite-vec` (the successor to sqlite-vss) is mature, fast for the scale we care about (sub-100ms vector queries up to ~50k chunks), and a typical library is 200–2000 works. Universal tooling: Datasette gives a free web UI, every language has a driver, `sqlite3 library.db "SELECT ..."` works from any terminal.

SQLModel sits on top of SQLAlchemy with Pydantic models — same models double as the librarian agent's tool I/O, no duplicate definitions. Alembic handles migrations because the schema *will* evolve.

### Why FastMCP

FastMCP is the standard MCP framework for Python — decorator-based (`@server.tool()`), async-native, supports both stdio (for local hosts like Claude Code) and HTTP (for remote). ~30 lines wraps the librarian's tool surface. By the same author as Pydantic, idiomatic with the rest of our stack.

## Plugin architecture (sources and resolvers)

Discovery sources and PDF resolvers are pluggable. The bundled sources implement the same Protocols any third-party plugin does — there is no privileged "core" path. Full spec in [`PLUGINS.md`](PLUGINS.md); summary here.

Two interfaces:

- **`DiscoverySource`** — `search(query, ...) -> list[WorkCandidate]`. Optional `get_references`, `get_citations`, `get_citation_contexts` for citation-graph-aware sources.
- **`Resolver`** — `can_resolve(work) -> bool`, `resolve(work) -> ResolvedFile`. Tried in priority order until one returns bytes.

Plugins register via Python entry points (for distributed `pip`-installable plugins) or by dropping `.py` files in `~/Callimachus/plugins/` (for personal, unpacked plugins). Each plugin owns its config namespace under `callimachus.yaml`, validated by a Pydantic model the plugin ships.

### Bundled plugins

**Bibliographic backbone** — the rigorous spine of the library:
- `openalex` — primary, comprehensive, free, no key
- `semantic_scholar` — citation graph + influential-citation count + **citation contexts** (the actual sentences in which papers cite each other — the unlock for seminality judging)
- `arxiv` — preprints + LaTeX source for clean extraction (also a resolver)
- `crossref` — DOI resolution and structured metadata
- `unpaywall` — open-access PDF resolver for any DOI

**Neural web discovery** — what bibliographic indexes miss:
- `exa` — semantic web search; finds grey literature, lab pages, technical reports, blog deep-dives, recent stuff that hasn't propagated
- `perplexity` — used at the planning phase only: "lay of the land" synthesis before hunters spawn. Default routing is **via OpenRouter** (`perplexity/sonar`) so users only need their existing `OPENROUTER_API_KEY`. A separate `PERPLEXITY_API_KEY` is supported as an opt-in for users who want to hit Perplexity's API directly (different rate limits / native search filters).

**Local:**
- `local_pdfs` — point at any directory of PDFs you already have; they become discoverable and resolvable

Not bundled, not in scope for core: Google Scholar (no API, scraping fragile and ToS-hostile). Anything domain-specific (PubMed, PhilPapers, IEEE) ships as community plugins. Anything the project doesn't take a position on (Sci-Hub, Anna's Archive, institutional proxies, paid databases) is also a community plugin — users decide.

### How plugins flow through the system

- The orchestrator queries a `SourceRegistry`; gets enabled discovery sources back. Briefs each hunter on which sources to weight for its angle.
- Hunters call `search()` on their assigned sources in parallel.
- Every candidate carries `provenance: { source_name, query, raw_score }`; the judge can weight by source reliability.
- The pipeline's resolve step iterates resolvers in priority order; the first to return wins.
- Plugin failures degrade gracefully: a source that times out or errors is logged and skipped for the rest of the run; a resolver that fails moves to the next in priority. The mechanism is `pydantic_ai.ModelRetry("reason")` raised from the plugin call (see `PLUGINS.md`) — the agent sees the failure as a recoverable signal rather than a crash.
- Per-run plugin metrics (candidates contributed, PDFs fetched, errors, latency) are written to the run log and surfaced in `calli plugin doctor`.

### The orchestrator

A single Pydantic AI agent (typically Claude Opus 4.7) — Callimachus himself — that plans and supervises. Tools:

- `plan_research(collection_scope) -> ResearchPlan`
- `consult_perplexity(question) -> Synthesis` *(optional, planning phase)*
- `spawn_hunter(angle, brief, sources) -> HunterReport` — runs in parallel with siblings
- `judge_and_admit(work_candidate) -> Verdict`
- `snowball_from(work_id) -> list[WorkCandidate]`
- `check_convergence() -> ConvergenceStatus`
- `update_overview(collection_id)` — regenerate collection synthesis after a phase

### The hunters

Pydantic AI sub-agents (Sonnet 4.6 to keep cost reasonable) spawned in parallel for different angles. Each hunter has:

```
search_openalex(query, year_from?, venue?)
search_semantic_scholar(query, year_from?)
search_arxiv(query, category?)
search_exa(query, kind="academic" | "general")
get_citation_contexts(work_id)
get_work_metadata(doi_or_id)
```

A hunter is briefed with a focused angle ("foundations of score-based generative modelling, late 2010s") and which sources to lean on (a "recent state-of-the-art" hunter weights Exa + arXiv; a "foundations" hunter weights citation graph). Returns a ranked list of candidates with reasoning.

### The judge

A focused single-shot LLM call (Sonnet 4.6) with a Pydantic structured output. It scores each candidate on:

1. **Relevance** to the collection scope (0–10)
2. **Seminality** — judged from citation contexts ("the seminal work of X" vs "see also [12]"), influential-citation count, cross-bibliography frequency in the current library
3. **Novelty within library** — does it add a perspective not already covered? Diversity bonus.
4. **Recency vs foundationality** — weighted by user's `prefer_recent` / `prefer_foundational` setting
5. **Cross-collection relevance** — if the library has multiple collections, does this work also score on others? If yes, flag as `bridge`.

Output: `Verdict { score, reasoning, accept, snowball_candidate, bridge_collections }`. Only works above a snowball threshold get promoted as new seeds.

The judge is **kind-aware**: a paper is scored against different criteria than an essay. For essays/reports, peer review isn't a signal; author reputation and citation-by-papers are weighted higher.

### Snowball loop

```
seeds = orchestrator.initial_top_n(plan, n=15)

while budget_remains and not_converged:
    candidates = pool from refs(seeds) ∪ forward_cites(seeds)
    candidates = enrich_with_citation_contexts(candidates, current_library)
    candidates = dedupe(candidates)

    verdicts = [judge(c, collection_context) for c in candidates]  # batched
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
- **Topic drift detector** — periodically embed newly accepted works, compare to the collection embedding. Drift over threshold → prune the branch and tell the orchestrator.

### Citation context — the unlock

Semantic Scholar's API exposes `citationContexts`: the literal sentence from each citing paper that mentions a given citation. "Building on the seminal work of [Smith 2018]…" carries different signal from "see also [12]". The judge reads these contexts when available. No other free source provides this consistently.

## Pipeline in detail

After discovery converges, accepted works feed a deterministic pipeline. All async, parallelised, with progress bars.

1. **Resolve** — find a downloadable URL (Unpaywall first, then arXiv, then publisher OA)
2. **Download** — fetch PDF (or LaTeX archive when arXiv has source)
3. **Extract**
   - arXiv with LaTeX source → render to markdown directly (cleanest, math intact)
   - Web essays/reports → readability extraction → markdown
   - Otherwise → Mistral OCR API
   - Edge cases (encrypted, weird scans) → Claude vision fallback
4. **Enrich** — single LLM call per work produces:
   - Structured metadata into YAML frontmatter (title, authors, year, venue, DOI, ...)
   - 1–2 paragraph summary
   - Bullet list of key claims and contributions
   - Tagged methods, datasets, entities
5. **Embed** — chunk into ~500-token windows with 100-token overlap; embed each chunk; store with work FK
6. **Index** — write metadata, chunks, embeddings, citations, collection memberships into `library.db`

Each step is idempotent and per-work checkpointed in `.callimachus/state.json`. Resuming picks up where it left off.

## Storage schema

A single SQLite file (`library.db`) with `sqlite-vec` loaded on connection.

```sql
-- Collections: first-class subjects within a library
CREATE TABLE collections (
  id              TEXT PRIMARY KEY,        -- slug
  name            TEXT NOT NULL,
  keywords        JSON,
  notes           TEXT,
  embedding       BLOB,                    -- topic vector for drift + bridges
  overview_path   TEXT,                    -- collections/{slug}/overview.md
  added_at        TIMESTAMP,
  added_by_run_id INTEGER REFERENCES runs(id)
);

-- Works: papers, essays, reports, etc.
CREATE TABLE works (
  id              TEXT PRIMARY KEY,        -- canonical slug
  kind            TEXT NOT NULL,           -- paper | essay | report | talk | chapter
  doi             TEXT UNIQUE,
  arxiv_id        TEXT,
  title           TEXT NOT NULL,
  authors         JSON NOT NULL,
  year            INTEGER,
  venue           TEXT,
  abstract        TEXT,
  summary         TEXT,                    -- LLM summary
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
  bridge          BOOLEAN DEFAULT 0,
  metadata        JSON
);

-- Many-to-many: a work can belong to multiple collections
CREATE TABLE work_collections (
  work_id         TEXT REFERENCES works(id),
  collection_id   TEXT REFERENCES collections(id),
  score           REAL,                    -- per-collection relevance 0-10
  is_seed         BOOLEAN DEFAULT 0,
  PRIMARY KEY (work_id, collection_id)
);

-- Chunks for vector search
CREATE TABLE chunks (
  id              INTEGER PRIMARY KEY,
  work_id         TEXT REFERENCES works(id),
  ord             INTEGER,
  text            TEXT,
  section         TEXT
);

CREATE VIRTUAL TABLE vec_chunks USING vec0(
  chunk_id        INTEGER PRIMARY KEY,
  embedding       FLOAT[768]
);

-- Citation graph
CREATE TABLE citations (
  citing_work     TEXT REFERENCES works(id),
  cited_work      TEXT REFERENCES works(id),
  context         TEXT,                    -- the citing sentence
  PRIMARY KEY (citing_work, cited_work)
);

-- Run history (every mutation is a run)
CREATE TABLE runs (
  id              INTEGER PRIMARY KEY,
  kind            TEXT,                    -- build | extend | refresh | prune | rejudge | restore
  collection_id   TEXT REFERENCES collections(id),
  started_at      TIMESTAMP,
  ended_at        TIMESTAMP,
  config          JSON,
  cost_usd        REAL,
  works_added     INTEGER,
  works_archived  INTEGER,
  works_retagged  INTEGER,
  notes           TEXT
);

CREATE TABLE run_log (
  id              INTEGER PRIMARY KEY,
  run_id          INTEGER REFERENCES runs(id),
  ts              TIMESTAMP,
  phase           TEXT,
  event           TEXT,
  payload         JSON
);
```

Vector search:

```sql
SELECT works.title, works.summary, distance
FROM vec_chunks
JOIN chunks ON chunks.id = vec_chunks.chunk_id
JOIN works ON works.id = chunks.work_id
WHERE embedding MATCH ? AND k = 20 AND works.archived_at IS NULL
ORDER BY distance;
```

Collection-scoped vector search:

```sql
SELECT works.title FROM vec_chunks
JOIN chunks ON ...
JOIN works ON ...
JOIN work_collections wc ON wc.work_id = works.id
WHERE embedding MATCH ? AND k = 20
  AND wc.collection_id = ?
  AND works.archived_at IS NULL
ORDER BY distance;
```

Bridge works:

```sql
SELECT w.* FROM works w
WHERE w.bridge = 1 AND w.archived_at IS NULL
ORDER BY w.judge_score DESC;
```

## The librarian — Callimachus the agent

A long-lived Pydantic AI agent that owns the library. The chat interface (`calli`), the one-shot CLI (`calli query`), the MCP server (`calli serve --mcp`), and the build/extend/refresh CLI subcommands are all invocations of this agent or its tools.

### Tool surface

**Read tools** (always exposed, including over MCP):

| Tool | Purpose |
| --- | --- |
| `search_library(query, k=10, filters?)` | Semantic search; filters by collection, year, venue, kind, bridge |
| `get_work(id_or_slug)` | Full metadata + summary |
| `get_work_full(id_or_slug)` | Full markdown |
| `find_related(id_or_slug, k=10)` | Citation- and embedding-based related works |
| `summarise_collection(id)` | Synthesis of one collection |
| `summarise_topic(query)` | Topic-scoped synthesis across the whole library |
| `bridges(collection_a, collection_b)` | List bridge works between two collections |
| `cite(query)` | BibTeX entries for top-k matches |
| `library_summary()` | Library-level overview (used at chat startup) |
| `inspect_paper(id)` | Show full metadata + judge reasoning + run history |

**Mutation tools** (gated for MCP — opt in to expose):

| Tool | Purpose |
| --- | --- |
| `add_collection(name, keywords, notes)` | Add a new collection (triggers a discovery run) |
| `prune(filters, archive=True)` | Soft-delete works matching a filter |
| `restore(filter)` | Bring archived works back |
| `refresh(collection?, since?)` | Find work since the last build |
| `rejudge(criteria)` | Re-score the library with new criteria |
| `bridge_libraries(other_library_path)` | Cross-library intersection report (read-only on the other) |
| `add_note(text)` | Append to `notes.md` for mid-run steering |

### CLI as shortcuts

| CLI | Librarian action |
| --- | --- |
| `calli` | Open chat in default library |
| `calli init [name]` | Create new library + first collection |
| `calli collection add ...` | `add_collection(...)` |
| `calli collection list` | List collections |
| `calli refresh [--collection X]` | `refresh(...)` |
| `calli prune ...` | `prune(...)` |
| `calli restore ...` | `restore(...)` |
| `calli query "..."` | One-shot read |
| `calli bridge LIB_A LIB_B` | `bridge_libraries(...)` |
| `calli serve --mcp` | Expose librarian as MCP server |
| `calli serve --web` | Local web UI |
| `calli export ...` | Tarball export |
| `calli import ...` | Tarball import |
| `calli rehydrate` | Re-download missing PDFs from source URLs |
| `calli log` | Read `runs` and event log |
| `calli cost` | Aggregate `runs.cost_usd` |
| `calli doctor` | Check API keys, dependencies, library integrity |

The CLI exists for users who prefer commands or want to script. The chat is the dominant interface.

## Human in the loop

Four checkpoints during a discovery run, each skippable independently or globally with `--auto`:

1. **Plan review** — after `plan_research`, before any hunters spawn. Shows angles, queries, criteria, estimated scope, estimated cost. User edits or accepts.
2. **Seed approval** — after first discovery + judging pass. Top ~30 candidates with one-line summaries. User: include / exclude / mark-as-seed (deeper snowball).
3. **Per-iteration review** *(optional, off by default)* — after each snowball pass.
4. **Final prune** — before the pipeline phase. Full work list with one-line summaries. User drops duds.

### `notes.md` mid-flight steering

Callimachus re-reads `.callimachus/notes.md` at the start of each snowball iteration. The user edits it in any editor while the run is in progress to nudge direction without restarting. Lighter weight than a checkpoint, more flexible than restarting.

### Notifications

Optional desktop notification (or webhook) when a checkpoint is reached, so users don't have to babysit the TUI for hours. Configured in `.env`.

## Cost transparency

- Plan review estimates cost based on planned angle count and expected work count
- Live running cost shown in the TUI status bar at all times
- Hard `--budget-usd` cap; orchestrator stops cleanly when reached and reports what it has
- Per-phase cost breakdown written to `.callimachus/cost.json`
- `calli cost` aggregates spend across runs

## Resumability

- Per-work checkpoint after each pipeline step (download → extract → enrich → embed → index)
- Discovery state checkpointed at the end of each snowball iteration
- `calli` notices an in-progress run on startup and offers to resume
- A crash mid-work is recovered by re-running that work's incomplete step (idempotent)

## Backup and sharing

### Tier 1 — git-friendly default

`.gitignore` excludes `works/*/original.pdf` and `.callimachus/state.json` (also `.callimachus/runs/` if user wants minimal repo). Everything else commits to plain git. Typical committed size for a 500-work library: ~500MB.

`calli rehydrate` re-downloads PDFs from `works.source_url`. The library's intelligence (markdown, summaries, embeddings, citation graph, judge reasoning) is what version-controls; PDFs rehydrate.

### Tier 2 — full snapshot

`calli export` produces a tarball of the entire library including PDFs. `calli import` restores anywhere. Per-collection export is supported for selective sharing.

### Tier 3 — git LFS

Documented in `docs/BACKUP.md` for users who want versioned PDFs. Not the default; we don't push everyone into LFS quotas.

## Provider abstraction

LLM calls go through a thin internal interface:

```python
class LLMProvider(Protocol):
    async def complete(self, ...): ...
    async def complete_structured(self, ...) -> BaseModel: ...
    async def stream(self, ...) -> AsyncIterator[Event]: ...
```

Pydantic AI implements this for all providers it supports. Switching is a config change. Provider-specific perks (e.g. Anthropic prompt caching) activate when available, transparently.

**Provider-specific caveats the wrapper must handle:**

- **Gemini + structured output**: Pydantic AI's docs warn that Gemini can't combine tools and structured output. In practice (experiment 04) Gemini 2.5 Pro routed via OpenRouter returned a valid structured `Verdict` with default `ToolOutput` mode, so the warning may not apply to current Gemini versions or may be auto-handled. **Don't pre-emptively code around it.** If we see real failures when routing the judge through Gemini, the wrapper can switch that path to `NativeOutput` or `PromptedOutput` mode at that point.

## MCP server

`calli serve --mcp` exposes the librarian's read tools (and optionally mutation tools) over the FastMCP stdio transport. Once registered with Claude Code / Cursor / Claude Desktop / any MCP host, the library becomes a first-class tool the host's chat agent can call.

```python
# sketch
from fastmcp import FastMCP

mcp = FastMCP("callimachus")

@mcp.tool()
async def search_library(query: str, k: int = 10, collection: str | None = None) -> list[Work]:
    ...

@mcp.tool()
async def find_related(work_id: str, k: int = 10) -> list[Work]:
    ...

# ... etc
```

Mutation tools default to off over MCP. `calli serve --mcp --allow-mutations` opts in.

## Folder layout

### Library on disk

```
~/Callimachus/                       # default library path
  callimachus.yaml                   # global config + per-library settings
  README.md                          # auto-generated, regenerated on changes
  collections/
    {collection-slug}/
      collection.yaml                # name, scope, keywords, notes, embedding ref
      overview.md                    # synthesis, regenerated as collection grows
      seeds.yaml                     # the seed works that anchored it
  works/
    {work-slug}/                     # canonical: {firstauthor}-{year}-{shorttitle}
      original.pdf                   # gitignored by default
      paper.md                       # full text + YAML frontmatter
      summary.md
      metadata.yaml                  # collections, scores, judge reasoning, source URL
  index/
    library.db                       # SQLite + sqlite-vec, the queryable index
  archive/                           # soft-deleted works (recoverable)
    {work-slug}/...
  plugins/                           # local user plugins (drop-in .py files)
  .callimachus/
    state.json                       # checkpointing
    cost.json                        # spend log
    notes.md                         # editable mid-run, agents re-read each iteration
    runs/{iso-timestamp}.jsonl       # full event log per run
    cache/                           # API response cache
```

### Repository layout (planned)

```
callimachus/
  src/callimachus/
    cli.py                           # entrypoints, all subcommands
    chat/
      app.py                         # the prompt_toolkit + Rich chat for the librarian
      keybindings.py                 # Enter/Alt+Enter, Shift+Enter via CSI u, etc.
      slash_commands.py              # /help /clear /save /history etc.
      kitty_protocol.py              # enable/disable CSI u disambiguation mode
    tui/
      build_app.py                   # the Textual dashboard for discovery + pipeline runs
    librarian/
      agent.py                       # the Callimachus agent definition
      tools/
        read.py                      # search, get, find_related, summarise, cite
        mutate.py                    # extend, prune, refresh, rejudge
        meta.py                      # library_summary, inspect, log, cost
    discovery/
      orchestrator.py                # the orchestrator agent
      hunters.py                     # hunter subagent factory
      judge.py                       # judge prompt + Pydantic schema
      snowball.py                    # the snowball loop
      drift.py                       # topic drift detector
    sources/
      protocols.py                   # DiscoverySource, Resolver, WorkCandidate types
      registry.py                    # plugin discovery and loading (entry points + local files)
      bundled/                       # the built-in plugins; same protocols as third-party
        openalex.py
        semantic_scholar.py
        arxiv.py
        crossref.py
        unpaywall.py
        exa.py
        perplexity.py
        local_pdfs.py
    pipeline/
      download.py
      extract/
        latex.py
        mistral_ocr.py
        readability.py               # for essays/reports
        claude_vision.py
      enrich.py
      embed.py
      index.py
      synthesis.py                   # phase 2.5 overview generation
    storage/
      models.py                      # SQLModel classes
      db.py                          # connection, vec extension loading
      migrations/                    # Alembic
      schema.sql                     # canonical DDL (generated from models)
    query/
      vector.py                      # sqlite-vec query helpers
      sql.py
    mcp/
      server.py                      # FastMCP wrapper
    providers/
      __init__.py                    # the LLMProvider protocol
      anthropic.py                   # caching-aware
      openai.py
      gemini.py
      openrouter.py
      ollama.py
    backup/
      export.py
      import_.py
      rehydrate.py
    config.py
    cost.py
    state.py
  docs/
    ARCHITECTURE.md
    USER_STORIES.md
    PLUGINS.md
    PROMPTS.md                       # all system prompts, versioned
    DATA_SCHEMA.md                   # detailed schema docs
    BACKUP.md                        # tiers, LFS setup
  examples/
    example-plugin/                  # reference implementation: tests, config, docs
  tests/
  pyproject.toml
  README.md
  .gitignore
  .env.example
```

## Phase 2 — talks and book chapters (deferred)

Same shape as papers, different ingestion. Both become new `kind` values for `works`.

**Talks (YouTube, conference recordings):**
1. YouTube Data API search per angle (or direct URL drop)
2. Quality scoring rubric (channel reputation, view/like ratio, length thresholds, transcript availability)
3. yt-dlp to fetch audio
4. Whisper (Groq Whisper API for speed, local for free) for transcription
5. Same enrichment + embedding + index pipeline
6. Stored under `works/{video-id}/` like papers, with `kind: talk`

**Book chapters:**
1. User points at a PDF (or a directory of PDFs); chapter detection via TOC parsing or LLM
2. Same extract → enrich → embed pipeline
3. `kind: chapter`, with `parent_work` linking chapters back to their book

## Open questions to revisit during build

- Default snowball depth and convergence thresholds — needs tuning against real topics
- How aggressively to dedupe arXiv preprint vs published version (DOI mapping is imperfect)
- Whether to support multiple topic embeddings *per* collection (e.g. allow two parallel themes within one collection)
- Best chunking strategy for academic papers (semantic vs sliding-window vs section-aware)
- How to expose the citation graph in the chat (text-based vs terminal graphics; chat is inline-scrolling so we lose alt-screen rendering options)
- Whether to ship a Hermes Agent skill alongside the MCP server for the multi-platform messaging crowd
- Per-collection model overrides (e.g. use Opus for "creativity", Sonnet for everything else)
- When library scale demands migration off sqlite-vec (suggest LanceDB at ~50k chunks)
