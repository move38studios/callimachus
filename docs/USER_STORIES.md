# User stories

The experiences `callimachus` is built around. The architecture and CLI surface are derived from these, not the other way around.

## Status legend

Each story is tagged with one of:

- ✅ **Shipped** — works today, end-to-end. Try it.
- 🔄 **Partial** — some pieces work, others are stubbed or missing. Status box explains what works and what doesn't.
- 🔜 **Next** — landing in the next milestone (M3 chat).
- 🟦 **Future** — in the plan but not started. Milestone noted.

This file is the canonical "is X actually built?" reference for product UX. For implementation status, see [`DEV_PLAN.md`](DEV_PLAN.md).

## The mental model

A **library** is a directory (default `~/Callimachus/`). It contains everything Callimachus needs to query, extend, refine, and share your research.

A library has one or more **collections**. A collection is a coherent subject ("creativity in humans and machines", "diffusion models", "music theory") with first-class identity: scope, embedding, overview document, seed works, README. Collections aren't tags. *(Today: a library has one implicit collection. Multi-collection arrives in M4.)*

A **work** is a research artifact: paper, essay, report (later: talk, chapter). A work can belong to multiple collections with per-collection relevance scores. A work that's highly relevant to two or more collections is flagged as a **bridge** — the cross-pollination payoff.

A **run** is a single Callimachus operation that mutated the library — initial build, extending with a new collection, refresh, prune, re-judge. Every work carries the run that admitted it; every change is auditable.

**Callimachus** is the librarian agent — the persona you talk to. The chat (`calli chat`) will be the dominant interface (M3). CLI subcommands (`calli init`, `calli build`, `calli query`) are typed shortcuts.

## Personas

- **The lone researcher** — building deep expertise in a topic, solo. Wants to outsource the boring discovery work and end up with a personal library they can search and read.
- **The team lead** — building a shared library their team can clone, query, and contribute back to. Cares about reproducibility and shareability.
- **The consultant** — picks up a new domain every few weeks. Needs to ramp fast on unfamiliar literature without becoming a librarian themselves.
- **The autodidact** — curious about cross-disciplinary topics, wants to find connections between fields that don't usually talk to each other.

---

## What works today

### 1. Build a fresh library on a topic — ✅ Shipped

> *As a researcher new to a topic, I want to give Callimachus a topic and have it produce a deep, well-organised library, so I can ramp up without weeks of bibliographic work.*

```bash
calli init                                   # one-time: create the library directory
calli build --topic "diffusion models"       # scout + HITL ceremony → plan.yaml
calli build --from-plan diffusion-models     # orchestrator runs hunters → judge → ingest
```

The two-step (terraform plan/apply) flow is mandatory by design — a bare topic like "creativity" can mean a dozen things; the scout asks four clarifying questions before committing to the deep build. `--auto` skips the ceremony with sensible defaults.

What you end up with: ~10-20 papers downloaded, extracted to clean markdown with YAML frontmatter (title, authors, summary, key claims, methods, datasets, keywords), embedded into a vector index, indexed in `library.db`. `calli list` shows them; `calli query "..."` runs semantic search.

### 2. One-shot semantic query — ✅ Shipped

> *As a user, I want to search my library by meaning, not just keywords.*

```bash
calli query "main approaches to scheduling in diffusion models"
calli query "Rich text input prototype" -k 5
```

Vector search via `sqlite-vec`; returns top-k matching chunks with their parent works' titles and metadata.

### 3. Inspect the library — ✅ Shipped

> *As a user, I want to know what's in my library.*

```bash
calli list                                   # all works with title, year, authors
ls ~/Callimachus/works/                       # per-work directories on disk
sqlite3 ~/Callimachus/library.db ".tables"    # the underlying schema
```

Per-work directories contain `original.pdf` (or `.tar.gz`), `paper.md` (full text + frontmatter), `summary.md`, `metadata.yaml`. The library is a transparent directory you can grep, copy, share.

### 4. Honest scope and run transparency — 🔄 Partial

> *As a user, I want to bound how big a run can get, and see honest token/model usage so I can reason about cost myself.*

Today:
- ✅ `--max-works N` cap (set during the ceremony or by editing `plan.yaml` before `--from-plan`)
- ✅ Hunter token totals + request counts surfaced in the build summary panel
- ✅ Run row written to `runs` table with `started_at`, `ended_at`, `works_added`, and a JSON `notes` blob containing per-stage stats
- 🟦 `calli log` to read run history
- 🟦 Judge token tracking (only hunter tokens are currently summed — judge runs in parallel and isn't instrumented yet)
- 🟦 `--max-hours N` and `--budget-tokens N` caps

No USD math by design — pricing changes too often, varies by deployment (OpenRouter / direct / Bedrock), and isn't load-bearing for the product. Multiply tokens × your provider's per-token price if you want a number.

### 5. Manual ingest from a seed YAML — ✅ Shipped (M1 path)

> *As a user, I have a list of arxiv IDs / DOIs / URLs I already curated. I want Callimachus to extract, summarise, embed, and index them.*

```bash
calli ingest seeds.yaml
```

Where `seeds.yaml` is a list of entries shaped like `{arxiv: "2006.11239"}`, `{doi: "10.x/y"}`, `{url: "https://..."}`, or full custom (`{title, source_url, authors, year, venue}`). This skips discovery entirely — useful when you know exactly what you want.

### 6. Plug in local PDFs you already have — ✅ Shipped

> *As a researcher, I have a folder of PDFs I've collected over the years. I want Callimachus to treat those as a discovery + resolver source.*

The `local_pdfs` plugin ships bundled. Configure via constructor (yaml-based config is 🟦 M6). When a hunter searches, local PDFs that match by title fingerprint are returned. When the resolver needs bytes, local files are served before any download happens.

---

## What's next (M3 — chat with your library)

### 7. Chat with the librarian — 🔜 M3

> *As a researcher, I want to talk to my library — ask questions, get summaries, find related works, generate citations.*

```bash
calli chat                                   # opens prompt_toolkit + Rich REPL
```

The librarian is a Pydantic AI agent with read tools: `search_library`, `get_work`, `find_related`, `summarise_topic`, `cite`, `library_summary`, `inspect_work`. The chat surface uses the aider-style pattern (validated in `experiments/05`): streaming markdown via Rich `Live`, multi-line input via prompt_toolkit, native terminal scrollback preserved.

Welcome screen on `calli chat`:

```
Welcome back. Your library has 87 works on "diffusion models".
Last build: 2026-05-15 (added 11 works).

What would you like to do?

> Summarise the foundational works on score-based generative modelling.
> Show me the citation graph around Ho 2020.
> Find works connecting diffusion and information theory.
```

### 8. Prune (gated mutations) — 🔜 M3

> *As a researcher, I want to remove works that turned out to be off-topic without restarting the whole library.*

Soft-delete via `archived_at` (the column already exists in the schema). Behind `--allow-mutations` for MCP/remote use; on by default in local chat.

```bash
calli chat
> Drop everything from before 2010 — I have enough foundations.
That would archive 23 works (recoverable via `restore`). Proceed?
> yes
```

Pruning is always reversible. Works go to `archive/` and the run log records every change.

---

## Future stories

### 9. Multi-collection within a library — 🟦 M4

> *As a researcher, I have a library on creativity. I want to extend it with artificial intelligence so I can find works that bridge the two.*

```bash
calli collection add "artificial intelligence" --keywords "transformers, RL, agents"
```

Adds a new collection within the same library. Hunters get a "look for cross-collection bridges" instruction. The judge gets the existing library context — knows not to re-add known works, *will* re-tag existing works for the new collection. Works scoring high on both collections get the `bridge` flag.

### 10. Snowball through citations — 🟦 M4

> *As a researcher, I want Callimachus to follow citation trails the way a good researcher would, finding the works that the works I have keep citing.*

Snowball loop with citation contexts (the actual sentences each citation appears in, via Semantic Scholar). Selective seed promotion (not every accepted work becomes a seed — only seminal ones), topic-drift detection, convergence + budget caps.

### 11. Refresh — pick up new work — 🟦 M4

> *As a researcher, I built this library 6 months ago. I want to find anything important published since then without re-doing the whole build.*

```bash
calli refresh                                # find work added since last build
calli refresh --since 2026-01-01
```

Re-runs hunters with the existing plan scoped to the cutoff date; filters out what's already in the library; judges and admits the new candidates.

### 12. Build dashboard with parallel hunter view — 🟦 M4

> *As a user, I want to watch the agentic build phase live — see hunters firing in parallel, candidates streaming in, the judge accepting / rejecting.*

Textual TUI with split panes: orchestrator, parallel hunter panes, live works list, status bar. Replaces today's streaming-log Rich progress for `calli build`.

### 13. Cross-library bridge — 🟦 M5

> *As a researcher with two separate libraries (e.g. one personal, one for work), I want Callimachus to look across them and surface intersection ideas.*

```bash
calli bridge ~/Callimachus ~/work-library --output cross-pollination.md
```

Read-only over both libraries; produces a markdown report of shared concepts, bridge works, candidate research directions.

### 14. MCP server (use the library from any chat agent) — 🟦 M5

> *As a Claude Code / Cursor user, I want my library to be a tool my chat agent can call.*

```bash
calli serve --mcp                            # stdio MCP server for local agents
calli serve --mcp --http :8000               # HTTP transport for remote
```

FastMCP server exposing the read tools by default. Mutation tools (prune, restore, refresh) opt in via `--allow-mutations`.

### 15. Mid-flight steering — 🟦 M4

> *As a researcher, I started a build and partway through realised I want a different emphasis. I don't want to wait or restart.*

Callimachus re-reads `.callimachus/notes.md` at the start of each snowball iteration. Edit it in any editor while the build is running; the next iteration picks up the steering.

### 16. Reproduce, share, back up — 🟦 M6

> *As a team lead, I want to share my library with collaborators reliably.*

Three tiers planned:
- **Git-friendly default** — `.gitignore` excludes PDFs + state.json; everything else commits cleanly. `calli rehydrate` re-downloads PDFs from source URLs after a clone.
- **Full snapshot** — `calli export` produces a tarball; `calli import` restores it. Per-collection export supported.
- **Git LFS** — for full PDF version history; documented in `docs/BACKUP.md` (also future).

### 17. Resume after crash or pause — 🟦 not planned for v0.1

> *As a user with an unreliable laptop, I want a long run to survive a crash, a sleep, or a manual pause.*

Per-stage idempotency exists today (you can re-run `calli build --from-plan` and stages skip what's already done), but there's no first-class "resume" command, no live state.json, no clean-pause via `q` in a TUI. Defer until users actually hit this — most builds finish in 5-15 minutes.

### 18. Observability and trust — 🔄 Partial

> *As a researcher, I want to inspect why a work was admitted, by which run, and how to find similar judgments.*

Today, every Work row in `library.db` includes:
- ✅ `judge_score` (0.0-1.0)
- ✅ `judge_reasoning` (the LLM's full reasoning)
- ✅ `admitted_by_run_id`
- ✅ `summary`, `key_claims`, `methods`, `datasets` (from enrichment)
- 🟦 `collections: [{slug, score, is_seed}]` — only meaningful with multi-collection (M4)
- 🟦 `bridge` flag — same
- 🟦 `seed_origin` (which hunter, angle, source) — `provenance` is captured on the candidate but not persisted on the Work

Querying these is currently `sqlite3 library.db "SELECT ..."`. `calli log` and `calli inspect` are 🟦 M6.

### 19. Explain itself — 🔜 M3

> *As a user new to the tool, I want Callimachus to be able to explain what's in my library and what it can do for me.*

The chat REPL's welcome screen will show a library summary (work count, last build date, top collections). The librarian agent's read tools cover the "what's in here" and "what can I ask?" affordances.

### 20. Plug in private or institutional access — 🟦 (plugin system supports it; nothing built)

> *As a university researcher, I have access to ACM Digital Library through my institution's proxy. I want Callimachus to use it for resolution when bundled OA sources can't find a PDF.*

The `Resolver` Protocol supports this today — you can write `callimachus-oclc-proxy` as an external plugin and it'll register at lower confidence than Unpaywall (so OA is still preferred). Nothing built; the contract is ready.

### 21. Domain-specific sources — 🟦 (plugin system supports it; nothing built)

> *As a contributor, I work in a domain (philosophy / climate / law) where the bundled sources don't cover the most important databases. I want to write a plugin for my domain and share it.*

Plugin contract is in [`docs/PLUGINS.md`](PLUGINS.md). A plugin is a small Python package implementing `DiscoverySource` and/or `Resolver` Protocols. Publish to PyPI; users install via `pip install callimachus-yourdomain`. The bundled plugins (`arxiv`, `openalex`, etc.) implement the same Protocols a third-party plugin would.

---

## Edge cases and failure modes worth thinking through

These are things that will eventually come up. Most are not addressed today.

- **Wildly disparate collections in one library** ("creativity" + "Roman aqueducts") — should Callimachus warn and suggest two libraries with a bridge instead? Or just go with it? *(M4 design decision.)*
- **Library size cap** — at what point does sqlite-vec performance degrade enough to suggest a migration to LanceDB? Surface a warning at ~50k chunks. *(M6.)*
- **Stale judges** — old works were judged with the old prompt; new ones with the new one. Does Callimachus offer a `rejudge` automatically when prompts change? *(M4 with `rejudge` mutation tool.)*
- **PDF source rot** — `rehydrate` finds a 404 on a source URL. Try alternative URLs? Surface unrecoverable rot to the user. *(M6.)*
- **Publisher 403s** — ACM, MDPI, Cell sometimes block scrapers. Today: try-more-on-failure logic falls through to the next judge-accepted candidate. The publisher just doesn't get ingested. Acceptable for v0.1.
- **arxiv rate limit** — 1 req/3s. Today: hunters share an arxiv plugin with a rate-limit lock. They cooperate but block each other. Acceptable; consider adaptive concurrency in M4.
