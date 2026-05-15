# Development plan

A staged build for Callimachus, structured around **small, independently-validatable experiments** before integration. Every assumption gets proven in isolation before it gets stitched into the product.

## Status snapshot — May 2026

| Milestone | Status | Headline |
|-----------|--------|----------|
| **M1** Storage + plugin system + ingest pipeline | ✅ done | `calli ingest seeds.yaml` works end-to-end |
| **M2** Topic → library | ✅ done | `calli build --topic X` ships scout + HITL ceremony + parallel hunters + judge + ingest |
| **M2.6** Resilience + breadth | ✅ done | Sonnet hunter, Unpaywall, Perplexity, try-more-on-failure, browser UA, OCR + LaTeX hardening |
| **M3** Chat with your library | 🔜 next | Librarian agent + read tools + `calli chat` REPL + prune mutations |
| **M4** Snowball + multi-collection + dashboard | 🟦 future | Citation graph snowball, bridge papers, Textual TUI |
| **M5** MCP server | 🟦 future | Use library from any chat agent (Claude Code, Cursor, etc.) |
| **M6** Polish + ship v0.1 | 🟦 future | `calli log`, `calli inspect`, backup tiers, library config file |

**Tests:** ~360 unit + ~12 live, all green.
**Bundled plugins:** 6 discovery sources (arxiv, openalex, serper_scholar, serper_web, perplexity, local_pdfs) + 3 resolvers (arxiv, unpaywall, local_pdfs).
**LLM defaults:** scout = Haiku 4.5, hunter + judge + enricher = Sonnet 4.6, synthesis (M4+) = Opus 4.7. All via OpenRouter.

For the higher-level "what works today" view see [`USER_STORIES.md`](USER_STORIES.md). For the code-architecture view see [`ARCHITECTURE.md`](ARCHITECTURE.md). For onboarding see [`ONBOARDING.md`](ONBOARDING.md).

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

> **Direction change, 2026-05-05.** After completing experiments 00–06, we paused and reassessed. The agent-harness experiments (01–06) earned their keep — Pydantic AI was unfamiliar and we found real things (provider swap mechanics, sub-agent budgets, ModelRetry pattern, streaming surfaces, model defaults per role, the chat = pt+Rich / dashboard = Textual split). The remaining 24 experiments were mostly "use a well-documented library, confirm it works as advertised" — low information-per-experiment ratio.
>
> **New shape**: experiments 07–30 are **deferred and folded into the integration milestones below**. We learn faster by building M1 and bumping into real issues than by isolated probes. When we hit something genuinely uncertain during M1+ work, we'll spin a focused mini-experiment at that moment. The full original list is preserved below as record of what we considered.

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

Now that the agent harness is validated (experiments 00–06), build the real thing in milestones. Each milestone produces a working, demonstrable slice of the product.

The deferred experiments (07–30) get folded into the milestone that needs them. When we hit something genuinely uncertain, we may spin a focused mini-experiment in the moment, but the default is "build it and see."

> **Direction change, 2026-05-09.** After M1 (deterministic pipeline) shipped working end-to-end, we re-prioritised. The original plan front-loaded M1.5 (cost tracking) and put snowball before chat. New shape:
>
> 1. **Cost tracking is dropped.** Translating tokens to USD is not our business — pricing changes, varies by deployment, and isn't load-bearing for the product. We *do* keep token + model logging (it's just truthful runtime info), but no `cost.json` and no `calli cost`. Removed from M2 / M6.
> 2. **The big leap is "topic → library"** — that's the headline pitch. M2 closes it.
> 3. **Chat with your library** comes next (was M4). It reuses everything; lighter than snowball.
> 4. **Snowball + multi-collection + build TUI** moves to M4. Depth, not novelty.
> 5. M5 (MCP) and M6 (polish + ship) unchanged.
>
> Old M3 (snowball) and old M4 (multi-collection + chat) are merged + re-ordered as new M3 (chat) and new M4 (snowball + multi-collection + dashboard).

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

Folds in deferred experiments: 11/12/13 (storage), 14/15/16 (embeddings), 17/19/20 (sources: openalex, arxiv, crossref+unpaywall), 23/24/25 (extract), 26 (enrich), 27 (chunking), 29/30 (plugin loader).

Out of scope: agentic discovery, snowball, judge, chat TUI, MCP server, multi-collection.

**Demo**: `calli ingest seed.yaml` (10 manually-curated diffusion-model papers) → `calli query "what's classifier-free guidance"` returns relevant excerpts with citations.

**Tests**: `tests/` covers the pipeline end-to-end with a fixture set of 3 papers.

### M1 sub-phases (working order)

All M1 sub-phases shipped, ✅:

- **M1.0 ✅** Storage scaffold (SQLModel + sqlite-vec + Alembic). 6 tests.
- **M1.1 ✅** Plugin loader (DiscoverySource + Resolver Protocols, registry, local_pdfs). 29 tests.
- **M1.2 ✅** arxiv plugin (both interfaces, real network gated). 28 tests + 1 live.
- **M1.3a ✅** paths + download + LaTeX extract. 33 tests.
- **M1.3b ✅** OCR provider + Mistral. 18 tests.
- **M1.3c ✅** Enrich (LLM → metadata + frontmatter). 16 tests.
- **M1.3d ✅** Chunk + embed + index. 60 tests.
- **M1.4a ✅** Ingest orchestrator. 11 tests.
- **M1.4b ✅** CLI (init, ingest, query, list). 19 tests + real-network smoke test passed.
- **~~M1.5 — Cost tracking~~** dropped. Token + model logging stays as part of normal runtime info, no USD math.

End of M1: 189 unit tests + 2 live tests, all green. Real demo: `calli ingest` arxiv ID → enriched, indexed, queryable.

### M2 — Discovery (topic → library)

Goal: closes the "give Callimachus a topic, get a library" gap. A user runs `calli build --topic "..."` and Callimachus does **shallow exploration → clarifying conversation → plan → deep build → indexed library**.

**The HITL ceremony is not optional.** A bare topic like "creativity" can mean cognitive science, computational creativity, generative art, business innovation, or a dozen other things. Without clarification we'd produce noise. The product-defining UX is: agent does some real work first (shallow probe across plausible angles + related fields), comes back with what it found, asks targeted questions, only then commits to the deep build. `--auto` flag for users who really want hands-off, but it's not the default.

Two-step UX (terraform plan/apply style):
1. `calli build --topic "..."` → scout + ceremony → writes `plan.yaml` to the library (`./.callimachus/plans/{slug}.yaml`)
2. User reviews / edits the plan
3. `calli build --from-plan {slug}` → orchestrator dispatches hunters → judges → ingests

Scope:
- New OpenAlex source plugin (broader coverage than arxiv alone)
- **Scout agent**: given a topic, runs ~5–10 shallow searches across plausible angles, returns an "angle tree" with sample papers per angle + related-fields suggestions
- **Plan ceremony**: orchestrator runs scout → presents findings → asks clarifying questions (which angles matter? specific authors/keywords to anchor? foundations or recent SOTA? years? scope cap?) → produces `plan.yaml` (angles, keywords, judge weights, max works)
- Judge module: single LLM call returning structured `Verdict` (relevance, seminality, accept, reasoning) calibrated to the plan
- Hunter sub-agent: parameterised by angle, calls source plugins, returns ranked candidates
- Orchestrator: takes a plan, fans out hunters in parallel (per the experiment-06 pattern), judges aggregated candidates, calls `ingest_one` for accepted
- Run log: every build writes a `Run` row (`kind="build"`, `started_at`, `ended_at`, `works_added`, `notes`) with per-stage token + model totals in `notes` JSON. Each ingested `Work` carries `admitted_by_run_id`. **No USD math anywhere.**
- Filter accepted candidates to those with `arxiv_id` so the existing resolver chain works without adding Unpaywall yet (initially deferred to M4 — actually pulled forward in M2.6c)

Out of scope for M2 (deferred): snowball, citation contexts, Exa/Perplexity, multi-collection, full Textual dashboard.

**Demo**:
```
$ calli build --topic "creativity"
[scout] probing 7 angles for "creativity"…
  • cognitive psychology of divergent thinking (12 hits, sample: Guilford 1967)
  • computational creativity in AI (8 hits, sample: Boden 2004)
  • generative-art systems (6 hits)
  • organisational creativity & innovation (15 hits)
  • cross-domain analogy / Hofstadter
  • creative problem-solving in design
  • neuroscience of creativity

  Related fields I noticed: improvisation, play, expertise development.

  > Which angles matter most for your library? (1,2,3 or 'all')
  > 1, 2, 5

  > Any specific authors, papers, or keywords to anchor on?
  > Hofstadter, Boden, divergent thinking

  > Foundations, recent SOTA, or both?
  > foundations

  > Hard cap on works to ingest? (default 50)
  > 30

[plan] saved to .callimachus/plans/creativity.yaml
       run `calli build --from-plan creativity` to start the deep build

$ calli build --from-plan creativity --auto
[orchestrator] 3 hunters dispatched in parallel…
  ✓ 28 candidates judged, 22 accepted
[ingest] 22 works indexed in ~6 minutes
```

#### M2 sub-phases

All M2 sub-phases shipped, ✅:

- **M2.0 ✅** OpenAlex bundled DiscoverySource (~250M-work catalogue, no auth). 19 unit tests + 1 live.
- **M2.0a ✅** Serper bundled DiscoverySources (Scholar + Web). 23 unit tests + 2 live.
- **M2.1 ✅** Judge module — single LLM call → `Verdict`. 10 unit tests + 2 live.
- **M2.2 ✅** Hunter sub-agent — Pydantic AI agent, one tool per source. 9 unit tests + 1 live.
- **M2.3 ✅** Scout + ceremony — `plan.py` / `scout.py` / `ceremony.py`. Plans persist as YAML to `.callimachus/plans/<slug>.yaml`. 48 unit tests + 1 live.
- **M2.4 ✅** Orchestrator + run log — `discovery/orchestrator.py`. 11 unit tests.
- **M2.5 ✅** `calli build` CLI — two-step (`--topic` → ceremony → plan; `--from-plan` → run). `--auto` for hands-off. 6 unit tests + manual end-to-end run on "LLM ethics" topic.

End of M2: 358 unit tests + ~12 live tests, all green.

**Lessons from the first real build (LLM ethics, 2026-05-13):**
- The `[a-z]+/\d+` arxiv ID regex was way too permissive — matched "org/10" out of `doi.org/10.x/y` URLs. Tightened to require either an arxiv URL prefix or a whole-string bare ID. 6 regression cases added.
- Hunter `tool_retries=1` was too tight — two consecutive arxiv 503s killed entire angles. Raised to 4.
- Build summary hid post-cap vs pre-cap accept counts. Fixed: shows both ("judge accepted N, capped to plan.max_works").

#### M2.6 — post-build resilience and source breadth

After the LLM-ethics smoke, several improvements made the build more honest and more capable:

- **M2.6a ✅** Resilience top-3: per-paper progress lines during ingest, auto-restrict to bibliographic sources for academic builds, hunter token totals in summary panel.
- **M2.6b ✅** Hunter on Sonnet 4.6 (was Haiku 4.5). `--hunter-model` CLI flag for override.
- **M2.6c ✅** Unpaywall resolver — DOI → OA PDF. 13 unit tests + 1 live. Pulled the M4-deferred plugin forward because the arxiv-only constraint was leaving too much value on the table.
- **M2.6d ✅** Drop arxiv-only constraint: filter renamed `require_resolvable_id` (arxiv_id OR doi). Roughly doubles the addressable corpus on non-arxiv-heavy topics.
- **M2.6e ✅** Perplexity discovery source via OpenRouter. 22 unit tests + 1 live. Lets the hunter run natural-language queries for topics where keyword search underperforms.

End of M2.6: hunter has 4 discovery tools (arxiv, openalex, serper_scholar, perplexity), resolver chain handles arxiv_id and doi, build streams progress, summary is honest about capping.

### M3 — Chat (talk to your library)

Goal: closes the "talk to my library" gap. Once you have a library (manual or topic-built), `calli chat` opens an aider-style REPL with the librarian — Callimachus the persona.

Scope:
- Librarian agent (the Callimachus persona) — Pydantic AI agent, multi-turn, streaming output
- **Read tools**: `search_library(query, k)`, `get_work(id)`, `find_related(id, k)`, `summarise_topic(query)`, `cite(query)`, `library_summary()`, `inspect_work(id)`
- **Mutation tools** (gated, off by default): `prune(filter)`, `restore(filter)`. Full extend/refresh/rejudge wait for M4 (they need the discovery agent + collection schema).
- `calli chat` — prompt_toolkit + Rich (the experiment-05 pattern, validated). Streaming markdown rendering, slash commands (`/help`, `/clear`, `/save`, `/exit`), persistent history, native scrollback preserved
- Welcome screen shows library summary (work count, last-build date)

Out of scope for M3 (deferred): MCP server (M5), Textual dashboard (M4), mutation tools beyond prune/restore.

**Demo**: `calli build` a library on creativity (M2) → `calli chat` → "summarise the foundational works on divergent thinking" → librarian answers with citations.

#### M3 sub-phases

- **M3.0 — Librarian agent.** `src/callimachus/librarian/` with the agent + read tools wired to the existing storage/query layer. Tests with stub LLM. ~2 hours.
- **M3.1 — `calli chat` REPL.** Lift the prompt_toolkit + Rich pattern from `experiments/05/chat.py`, replace the toy agent with the librarian, add library-summary welcome screen. ~2 hours.
- **M3.2 — Mutation tools (prune, restore).** Soft-delete via `archived_at` (already in schema), gated behind `--allow-mutations` for MCP/remote use. ~1 hour.

### M4 — Snowball + multi-collection + dashboard

Goal: depth. Snowball makes libraries deep; multi-collection makes one Callimachus support many subjects; the build dashboard makes the agentic feel land.

Scope:
- Snowball loop with citation contexts (Semantic Scholar plugin), selective seed promotion, topic-drift detection, convergence/budget caps
- Add Crossref source plugin (DOI metadata for non-arxiv works at scale; Unpaywall resolver already shipped in M2.6)
- Multi-collection: `calli collection add "name" --keywords ...` extends an existing library; bridge-paper detection (high relevance in 2+ collections); per-collection overview docs
- Build dashboard: Textual TUI with orchestrator pane + parallel hunter panes + live works list + status bar (the experiment-09/10 design). Replaces the M2 Rich progress for `calli build`
- Refresh + rejudge: librarian mutation tools added in M3 are now extended with `refresh` (find work since last build) and `rejudge` (re-score with new criteria)
- `notes.md` mid-flight steering

**Demo**: build creativity collection → `calli collection add "artificial intelligence"` → bridges discovered → user watches TUI in real time during a snowball run.

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
- Live smoke tests gated by `pytest -m live`: a small-but-real run end-to-end (already in place, just keep healthy)
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
| LLM nondeterminism makes integration tests flaky | All `tests/` use mocked LLM responses; the only real-LLM tests are gated behind `pytest -m live` and excluded from default CI |
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
