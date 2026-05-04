# Development plan

A staged build for Callimachus, structured around **small, independently-validatable experiments** before integration. Every assumption gets proven in isolation before it gets stitched into the product.

## Working principles

- **Prove components in isolation.** Each piece of the stack — agent harness, TUI, storage, embeddings, each discovery source, each pipeline step — gets a small `experiments/NN-name/` directory with a hello-world that proves the thing works the way we think it does.
- **Capture what we learn.** Every experiment has a `LEARNINGS.md` recording surprises, gotchas, defaults we landed on, and decisions that bind future work. Top-level `LEARNINGS.md` summarises the highlights.
- **Defer integration until parts are validated.** Don't build the orchestrator before the hunter agent works. Don't build the hunter before single-tool-calling works. Don't build single-tool-calling before basic agent works.
- **Decide during the work, not before.** Specific choices (chunking strategy, judge rubric, concurrency defaults, retry policy) get pinned down in the experiment that touches them, recorded in LEARNINGS, then carried forward.
- **Each experiment is small.** Aim for 1–3 hours per experiment. If it's bigger, split it.

## Repo layout while building

```
callimachus/
  experiments/                        # exploratory, prove-it-works code
    01-pydantic-ai-hello/
      README.md                       # what we're testing
      run.py                          # the experiment
      LEARNINGS.md                    # what we found
    02-pydantic-ai-tool-calling/
    ...
  src/callimachus/                    # real code, grown milestone by milestone
  tests/                              # proper test suite for src/
  docs/                               # design docs (this file, ARCHITECTURE, etc.)
  LEARNINGS.md                        # top-level summary of cross-cutting findings
  pyproject.toml
  README.md
  .env.example
```

`experiments/` lives forever as a record. They're not deleted when integration starts.

---

## Phase 0 — Repo and tooling (one-time)

Before any experiments. ~1–2 hours.

- [ ] `git init`, `pyproject.toml` with `uv`, basic `.gitignore`, `.env.example`
- [ ] Dev tooling: `ruff` (lint + format), `pytest`, `pytest-asyncio`, `mypy` (or `pyright`)
- [ ] Pre-commit hooks: ruff, basic file hygiene
- [ ] CI skeleton: GitHub Actions running ruff + pytest
- [ ] `experiments/00-env-check/` — print Python version, confirm `uv` works, confirm we can read `.env`

**Done when**: `uv sync && uv run pytest` and `uv run ruff check` both pass on an empty project.

---

## Phase 1 — Component experiments

The order is risk-first: validate the riskiest assumptions earliest. Each experiment lives in `experiments/NN-name/` with `README.md`, runnable code, and `LEARNINGS.md`.

### Agent harness (Pydantic AI)

**Goal of this group**: confirm Pydantic AI delivers the agentic ergonomics we're betting on.

#### 01 — Hello-world agent
- Single-turn chat with Claude Sonnet 4.6 via Pydantic AI
- Run from CLI: `python run.py "what is the capital of France?"`
- **Success**: model responds; we see the request/response shape and how to handle errors
- **LEARNINGS to capture**: Pydantic AI install footprint, Anthropic auth, streaming default behaviour, where the prompt template lives

#### 02 — Tool calling
- Define one tool (a Python function) the agent can call: `get_weather(city: str) -> str` returning a stub
- Verify the agent decides to call it given the right prompt, and continues with the tool result
- **Success**: full tool-use loop runs autonomously; we see the messages structure
- **LEARNINGS**: how tool definitions are declared, how outputs flow back, what error handling looks like

#### 03 — Structured output (Pydantic schema)
- Agent returns a typed Pydantic model: `Verdict { score: int, reasoning: str, accept: bool }` from a "judge this paper" prompt fed a fixture abstract
- **Success**: structured output validates; bad outputs raise a clear error
- **LEARNINGS**: how Pydantic AI handles schema retries, quality of structured output for our judge use case

#### 04 — Provider swap
- Same agent code, swap the model between: Anthropic Sonnet, OpenAI GPT-4.1, OpenRouter (any model), Ollama (local)
- Verify all four return reasonable answers to the same prompt
- **Success**: provider swap is a one-line config change as advertised
- **LEARNINGS**: which providers handle tool calling cleanly, which need workarounds, latency comparison, structured-output reliability per provider

#### 05 — Streaming
- Stream tokens from a Pydantic AI agent and print them progressively
- **Success**: smooth token-by-token output; we know the event shape
- **LEARNINGS**: event types we'll subscribe to from the TUI

#### 06 — Sub-agent / delegation
- One "orchestrator" agent that calls a "hunter" sub-agent as a tool, sub-agent has its own tools
- The hunter is told to "find papers on diffusion models" and uses a stub `search()` tool returning fake results
- **Success**: orchestrator delegates, hunter completes, results bubble up cleanly
- **LEARNINGS**: how parent context is or isn't shared, how to run multiple sub-agents in parallel via `asyncio.gather`, message provenance

#### 07 — Anthropic prompt caching
- Two-call experiment: send the same large prefix twice with `cache_control`, measure latency and confirm cost savings
- **Success**: second call is materially cheaper / faster
- **LEARNINGS**: how to thread cache_control through Pydantic AI (via the underlying model client config), what's cacheable, how to detect cache hits

### TUI (Textual)

#### 08 — Textual hello-world
- Single-screen app with a header, a text widget, a status bar
- **Success**: app runs in terminal, quits cleanly with `q`
- **LEARNINGS**: dev loop (hot reload), how to run a Textual app in tests

#### 09 — Stream agent output into Textual widget
- Combine 05 + 08: agent streams tokens; TUI renders them live in a scrolling pane; status bar shows token count
- **Success**: feels alive, not laggy
- **LEARNINGS**: async integration patterns, frame rate, how to handle very long streams without freezing the UI

#### 10 — Multi-pane TUI for parallel agents
- Split-pane layout with an orchestrator pane and N hunter sub-panes; fake "tool call" events stream into each pane
- **Success**: multiple panes update independently; layout adapts to terminal size
- **LEARNINGS**: which Textual widgets fit (DataTable for the live works list, Log for streaming, Static for status), keyboard shortcuts pattern

### Storage

#### 11 — SQLite + sqlite-vec hello-world
- Create a DB, load the vec extension, insert 100 random 768-d vectors, query nearest neighbours
- **Success**: end-to-end vector search in <50ms
- **LEARNINGS**: how to load the extension reliably across platforms, packaging implications (does the user need to install anything?)

#### 12 — SQLModel + Alembic
- Define a `Work` SQLModel, create initial migration, run a second migration that adds a column
- **Success**: migrations apply forward and roll back cleanly
- **LEARNINGS**: async session pattern, how to mix SQLModel for typed access with raw SQL for sqlite-vec MATCH queries

#### 13 — Combined: typed model + vector search
- `Work` and `Chunk` SQLModel + a `vec_chunks` virtual table; insert a few works with embeddings; query "vector search returning Works ordered by similarity"
- **Success**: one Python call returns typed `Work` objects ordered by vector distance
- **LEARNINGS**: the right way to bridge ORM + virtual table, performance at small scale

### Embeddings

#### 14 — Local nomic-embed
- Install `sentence-transformers`, load `nomic-ai/nomic-embed-text-v1.5`, embed 50 short academic abstracts
- **Success**: model downloads on first run, embeds in reasonable time on CPU
- **LEARNINGS**: cold-start time, RAM/disk usage, batch size sweet spot, how to ship the model (auto-download vs ask user)

#### 15 — Voyage API embeddings (opt-in)
- Embed the same 50 abstracts via Voyage `voyage-3`
- **Success**: API works, latency reasonable
- **LEARNINGS**: rate limits, how to detect "user has Voyage key" gracefully, fallback chain

#### 16 — Embedding quality smoke test
- Index the 50 abstracts twice (local + Voyage); query with 10 hand-written research questions; compare top-5 retrieved
- **Success**: both surface relevant papers; we see where they diverge
- **LEARNINGS**: whether the local default is good enough or whether Voyage should be the recommended setup

### Discovery sources

Each source gets a tiny experiment proving we can call it and parse the response. These are independent and can be done in any order.

#### 17 — OpenAlex hello-world
- Search "diffusion models", get top 20 with metadata
- **LEARNINGS**: rate limits, response shape, how to extract abstract + DOI + authors

#### 18 — Semantic Scholar + citation contexts
- Search a topic, then for one paper fetch references AND citation contexts
- **Success**: we see the actual sentences in which papers are cited
- **LEARNINGS**: rate limits with vs without API key, response shape, coverage gaps

#### 19 — arXiv search + LaTeX download
- Search arXiv, download a paper's LaTeX source archive, extract `main.tex`
- **LEARNINGS**: how reliable LaTeX source availability is, what fraction of papers have it

#### 20 — Crossref + Unpaywall
- Resolve 10 DOIs to open-access PDFs via Unpaywall
- **LEARNINGS**: hit rate, what fraction we can fetch legally for free

#### 21 — Exa neural search
- Same query as 17; compare results to OpenAlex; check how much grey literature appears
- **LEARNINGS**: cost per query, whether Exa surfaces things bibliographic sources don't

#### 22 — Perplexity Sonar synthesis
- Ask Perplexity "what are the main approaches to diffusion model scheduling in 2026?" and inspect the synthesised answer + citations
- **LEARNINGS**: cost, quality of synthesis, how to use it at the planning phase

### Pipeline

#### 23 — LaTeX → markdown
- Take the `main.tex` from experiment 19; convert to clean markdown preserving math, tables, sections
- **Success**: output is readable, math renders if dropped into a markdown viewer
- **LEARNINGS**: which library to use (`pylatexenc`? custom?), edge cases (custom macros, includes)

#### 24 — Mistral OCR API
- Take a non-arXiv PDF (a fixture); call Mistral OCR; compare output to manual reading
- **LEARNINGS**: cost per page, quality, how to chunk large PDFs

#### 25 — Claude vision fallback
- Take a tricky PDF (scanned, tables, figures); have Claude extract structured markdown from it
- **LEARNINGS**: when this is needed vs when Mistral OCR suffices, cost difference

#### 26 — Enrichment LLM call
- Feed a paper's full markdown to a single LLM call; get back YAML frontmatter (metadata, summary, key claims, methods)
- **Success**: output is structured, accurate, useful
- **LEARNINGS**: prompt design, output token budget, how often it gets things wrong

#### 27 — Chunking strategy
- Take 5 papers; try 3 chunking strategies (fixed-window, sliding-window, section-aware); embed each strategy; query with 10 questions; compare retrieval quality
- **Success**: pick a default with confidence
- **LEARNINGS**: the chunking decision, recorded in `docs/PROMPTS.md` once it exists

### MCP

#### 28 — FastMCP hello-world server
- Expose one tool (`echo(text: str) -> str`); connect to it from Claude Code via stdio MCP
- **Success**: end-to-end MCP call from another agent
- **LEARNINGS**: registration syntax, how to ship the server, debugging MCP

### Plugin system

#### 29 — Entry-point plugin loader
- Two packages: a fake "core" that loads plugins, a fake "plugin" that registers via entry points; install the plugin via `uv pip install -e ./plugin/`; verify core sees it
- **Success**: drop-in extensibility works
- **LEARNINGS**: any gotchas with entry-point discovery, hot-reload during dev

#### 30 — Local-file plugin loader
- Drop a `.py` file in a known directory; loader finds and imports it; satisfies the same Protocol as entry-point plugins
- **Success**: both registration paths converge to the same registry
- **LEARNINGS**: error handling when a local plugin is broken, how to surface this to the user

---

## Phase 2 — Integration milestones

Once the experiments are green, build the real thing in milestones. Each milestone produces a working, demonstrable slice of the product.

### M1 — Foundations (deterministic pipeline only, no agents)

Goal: a user can hand a YAML list of paper identifiers (DOIs / arXiv IDs / URLs) to a CLI and get a queryable library at the end. **No discovery agent yet.** This proves the storage + pipeline + plugin system stack.

Scope:
- Storage: `library.db` with the schema, SQLModel models, Alembic baseline
- Plugin loader (entry-points + local files), registry
- Bundled plugins (minimal): `openalex` (for metadata enrichment), `arxiv`, `crossref`, `unpaywall`, `local_pdfs`
- Pipeline: resolve → download → extract (LaTeX or Mistral OCR) → enrich → embed (local nomic) → index
- Per-work checkpointing
- CLI: `calli ingest <yaml-file>`, `calli query "<question>"` (one-shot, no chat yet)
- Cost tracking per run

Out of scope: agentic discovery, snowball, judge, chat TUI, MCP server, multi-collection.

**Demo**: `calli ingest seed.yaml` (10 manually-curated diffusion-model papers) → `calli query "what's classifier-free guidance"` returns relevant excerpts with citations.

**Tests**: `tests/` covers the pipeline end-to-end with a fixture set of 3 papers.

### M2 — Discovery agent (single collection, no snowball)

Goal: a user can give a topic and Callimachus discovers, judges, and ingests works without a manual list. Single-collection, no snowball yet — just plan → 1 hunter → judge → ingest.

Scope:
- Orchestrator agent (Pydantic AI) with `plan_research` and `spawn_hunter` tools
- One hunter sub-agent type, parameterised by angle
- Judge: structured-output LLM call with a v0 rubric
- Plan/seed checkpoints (interactive); `--auto` skip
- Build TUI v0: orchestrator pane + hunter pane + live works list (no per-hunter parallelism yet — one at a time)
- CLI: `calli init --collection <name> --keywords <...> --notes <...>`

**Demo**: `calli init --collection "diffusion models" --keywords "DDPM, score-based" --auto` → 30 papers indexed in ~10 minutes, queryable.

### M3 — Snowball + parallel hunters

Goal: real discovery with citation-driven snowball and parallel hunter execution. This is where the "agentic feel" lands.

Scope:
- Snowball loop with citation contexts, selective seed promotion, drift detection
- Multiple hunters spawned in parallel, each on a different angle
- Bridge-paper detection within a single collection (placeholder, since we still have only one collection)
- Build TUI v1: multi-pane layout with live hunter panes, status bar with cost/papers/elapsed
- Convergence and budget-cap stop conditions
- Plan-review checkpoint with cost estimate before kicking off

**Demo**: full `calli init` on diffusion models hits ~150 papers in a few hours; user watches the TUI; final library queryable.

### M4 — Multi-collection + librarian (chat)

Goal: lifecycle complete. Add collections to an existing library; cross-pollination via bridge works; chat with the librarian about your library.

Scope:
- `collections` table + `work_collections` many-to-many; soft-delete via `archived_at`
- `calli collection add` (extend) — uses the same discovery agent, with library context fed to judges so duplicates aren't re-added
- Bridge-pass: re-tag existing works that score on the new collection
- Librarian agent (the "Callimachus" persona) with read tools (search, get, find_related, summarise, cite, library_summary, bridges) and mutation tools (extend, prune, restore, refresh, rejudge)
- Chat TUI: `calli` with no args opens the librarian; supports multi-turn, streaming
- CLI subcommands as shortcuts: `prune`, `restore`, `refresh`, `rejudge`
- `notes.md` mid-flight steering
- Soft-delete plumbing throughout

**Demo**: build a library on creativity → `calli collection add "artificial intelligence"` → chat: "show me bridges between creativity and AI in this library" → returns annotated list.

### M5 — MCP server + cross-library bridge

Goal: the library is usable from any chat agent, and two libraries can be bridged.

Scope:
- FastMCP server exposing read tools by default; mutation tools behind `--allow-mutations`
- Stdio + HTTP transports
- `calli bridge LIB_A LIB_B` cross-library report
- Per-collection export/import: `calli export --collection X`
- `calli rehydrate` for git-cloned libraries

**Demo**: register the MCP server in Claude Code, ask "what does my library say about diffusion model schedules?" — Claude Code calls the tools, answers from the library.

### M6 — Polish, examples, ship

Goal: ready for users.

Scope:
- `examples/example-plugin/` — reference plugin with tests, config, docs
- `docs/PROMPTS.md` — every system prompt versioned and explained
- `docs/DATA_SCHEMA.md` — full schema reference
- `docs/BACKUP.md` — LFS setup
- End-to-end golden tests: a frozen mini-library that gets rebuilt and asserted in CI (mocked LLM responses)
- Cost smoke tests: small-but-real run that asserts budget cap behaves
- README walkthrough video / GIF
- v0.1 release tag, PyPI publish

---

## Decisions to make along the way

These get pinned down during the experiments that touch them. Recording them here so they don't get forgotten.

| Decision | Decided in | Captured in |
| --- | --- | --- |
| Default chunking strategy | Experiment 27 | `LEARNINGS.md`, then `PROMPTS.md` |
| Default judge rubric (the prompt) | Experiments 03 + 26, refined in M2 | `PROMPTS.md` |
| Concurrency defaults (max parallel hunters, max parallel pipeline workers) | M2 + M3 | `ARCHITECTURE.md` config section |
| Retry/backoff per source | Experiments 17–22 | Each plugin's `LEARNINGS.md` |
| Default LLM model per task (planner / hunter / judge / synthesiser / chat) | Experiments 01–07, refined throughout | `ARCHITECTURE.md` tech-stack table |
| When to use Mistral OCR vs Claude vision | Experiments 24 + 25 | `LEARNINGS.md` |
| Chunk size + overlap | Experiment 27 | `LEARNINGS.md` |
| Snowball convergence threshold (default) | M3 | `ARCHITECTURE.md` discovery section |
| Drift threshold (default) | M3 | `ARCHITECTURE.md` |
| Whether to bundle Voyage as default if user has key, or always opt-in | Experiment 16 | `LEARNINGS.md` |
| Whether `local_pdfs` is bundled or a separate plugin | M1 | `PLUGINS.md` |

## Risks and mitigations

| Risk | Mitigation |
| --- | --- |
| Pydantic AI's sub-agent model is awkward for parallel hunters | Experiment 06 catches this early; fallback is plain `asyncio.gather` over independent agents |
| Local nomic embedding is too slow on CPU for big libraries | Experiment 14 surfaces this; fallback is recommend Voyage in the README, document the perf wall |
| sqlite-vec performance degrades at scale | Document the wall (~50k chunks); migration path to LanceDB later |
| Mistral OCR cost or quality disappoints | Claude vision fallback is already in the design; Marker is the offline escape hatch |
| Source rate limits make the hunter loop slow | Rate-limited per-source clients with adaptive backoff; results cached in `.callimachus/cache/` |
| Long agentic runs hit context limits | Pydantic AI doesn't compact automatically; we add a manual compaction tool the orchestrator can call between snowball iterations |
| LLM nondeterminism makes integration tests flaky | All `tests/` use mocked LLM responses; the only "real LLM" tests are cost smoke tests in CI gated by an env var |
| User on Windows can't install some dep | Document supported platforms (Linux + macOS first); Windows via WSL2; verify cleanly in CI |

## Out of scope for v0.1 (deferred to v0.2+)

Recording these so they don't sneak in during build:

- Talks (`kind: talk`) — YouTube ingestion, Whisper transcription
- Book chapters (`kind: chapter`) — chapter-level ingestion with `parent_work` links
- Web UI (`calli serve --web`) — TUI is sufficient for v0.1
- Scheduled refresh as a daemon
- Explicit multi-contributor merging (PR workflow)
- Per-collection model overrides
- LFS-by-default
- Library-of-libraries
- Library scale beyond ~10k works (sqlite-vec wall)

## Cadence and reviews

- After each experiment: 10-minute writeup in its `LEARNINGS.md`
- After each milestone: review session — does the demo work end-to-end? What did we discover? What needs to change in the docs?
- Architecture doc kept living: when an experiment surfaces a decision, update `ARCHITECTURE.md` so it stays the source of truth
