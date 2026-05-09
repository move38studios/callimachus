# Callimachus

> Your personal librarian. Build, grow, and query a deep library of the best research on any topic — autonomously, in a few hours.

`callimachus` is an open-source autonomous librarian. You give it a topic; it plans a research strategy, hunts for the most relevant and seminal works across the academic literature *and* the wider web in parallel, follows citation trails the way a good researcher does, downloads what it can find, converts each work to clean markdown with structured metadata, summarises it, embeds it, and folds it into your personal library.

Discovery sources and PDF resolvers are a **plugin system**. Bundled plugins cover the open-access bibliographic web (OpenAlex, Semantic Scholar, arXiv, Crossref, Unpaywall) plus the wider web (Exa, Perplexity). Anything else — your Zotero library as a source, your institutional proxy, a domain-specific database, your Obsidian vault — is a `pip install` away.

Over time, your library grows. Add a new collection on a related topic and Callimachus finds the bridges. Refresh it months later and Callimachus pulls in the new work. Prune it when something turns out to be off-topic. Talk to it whenever you want to know what's in there.

By the end of your first run you have:

- The original PDFs of every accepted paper
- Clean markdown of every work with YAML frontmatter (title, authors, year, venue, methods, key claims, summary)
- A SQLite database with vector search and the full citation graph
- A TUI chat interface to ask questions of your library
- An MCP server so any chat agent (Claude Code, Cursor, Claude Desktop, Hermes) can query it too

The whole library is a single directory you can copy, share, version, or commit to git.

The chat persona is named after the man who invented bibliographic catalogues at the Library of Alexandria in the 3rd century BC. The CLI command is `calli`.

## The mental model

A **library** is a directory (default `~/Callimachus/`). It contains everything Callimachus needs to query, extend, refine, and share your research.

A library has one or more **collections**. A collection is a coherent subject — "creativity in humans and machines", "diffusion models", "music theory" — with its own scope, embedding, overview document, and seed works. Collections aren't just tags: they have first-class identity.

A **work** can belong to multiple collections with per-collection relevance scores. A paper on "computational creativity in transformer language models" is a first-class member of *both* the creativity collection and the AI collection. Works that are highly relevant to two or more collections are flagged as **bridges** — these are where the cross-pollination magic lives.

A work has a `kind`: `paper`, `essay`, `report` (and later `talk`, `chapter`). Callimachus admits high-quality blog posts and technical reports alongside peer-reviewed papers — Lilian Weng's deep-dives belong next to the papers they cite.

A **run** is a single Callimachus operation that mutated the library — initial build, extending with a new collection, refresh, prune, re-judge. Every work carries the run that admitted it; every change is auditable.

## The experience

```bash
# Install once
git clone https://github.com/move38studios/callimachus
cd callimachus && uv sync
cp .env.example .env       # add API keys
```

```bash
# Talk to your library (this is the dominant interface)
calli
```

```
Welcome back. Your library has 247 works across 2 collections:
  • creativity in humans and machines (187 works)
  • artificial intelligence (78 works)
  18 works bridge both collections.
  Last refreshed 2026-04-30.

What would you like to do?

> Extend it with cognitive science. I want to find more bridges to creativity.
```

```bash
# Or use the CLI directly
calli init                                       # create your library
calli collection add "diffusion models" \
  --keywords "DDPM, score-based, latent diffusion" \
  --notes "I care about foundations and lineage."
calli refresh                                    # find new work since last build
calli prune --score-below 6                      # archive low-scoring works
calli query "main approaches to scheduling"      # one-shot query
calli serve --mcp                                # expose as MCP server
calli export --collection diffusion-models       # share one collection
```

`calli` with no arguments opens the chat TUI in your default library. Every CLI subcommand is also a tool Callimachus can use in chat — the CLI is just typed shortcuts.

## What you get on disk

```
~/Callimachus/                       # your default library
  callimachus.yaml                   # global config
  README.md                          # auto-generated, regenerated on changes
  collections/
    creativity/
      collection.yaml                # name, scope, keywords, notes, embedding
      overview.md                    # synthesis of this collection
      seeds.yaml                     # the seed works that anchored it
    artificial-intelligence/
      ...
  works/
    ho-2020-denoising-diffusion/
      original.pdf
      paper.md                       # full text + YAML frontmatter
      summary.md
      metadata.yaml                  # collections, scores, judge reasoning, source URL
  index/
    library.db                       # SQLite + sqlite-vec
  archive/                           # soft-deleted works (recoverable)
  .callimachus/
    state.json                       # checkpointing
    notes.md                         # editable mid-run, agents re-read each iteration
    runs/{iso-timestamp}.jsonl       # full event log per run (tokens, models, timings)
```

## Installation

Requires Python 3.11+ and [uv](https://github.com/astral-sh/uv) (or pip).

```bash
git clone https://github.com/move38studios/callimachus
cd callimachus
uv sync
cp .env.example .env
```

Then edit `.env` to add keys.

## API keys

| Key | Required? | Purpose |
| --- | --- | --- |
| `OPENROUTER_API_KEY` | recommended default | LLM access via OpenRouter — one key for many models (Claude, GPT, Gemini, open weights). Default model: `anthropic/claude-sonnet-4.6`. |
| `ANTHROPIC_API_KEY` | alternative | Skip OpenRouter and call Anthropic directly. Set `CALLIMACHUS_LLM_PROVIDER=anthropic`. |
| `OPENAI_API_KEY` | alternative | Direct OpenAI. Set `CALLIMACHUS_LLM_PROVIDER=openai`. |
| `GEMINI_API_KEY` | alternative | Direct Gemini. Set `CALLIMACHUS_LLM_PROVIDER=gemini`. |
| `MISTRAL_API_KEY` | recommended | OCR for scanned/image-only PDFs (~$1/1000 pages) |
| `EXA_API_KEY` | recommended | Neural web discovery (grey literature, blog posts, lab reports) |
| `SEMANTIC_SCHOLAR_API_KEY` | optional | Higher rate limits on the citation graph |
| `VOYAGE_API_KEY` | optional | Higher-quality embeddings (`--embeddings voyage`) |
| `PERPLEXITY_API_KEY` | optional | Only if you want to call Perplexity directly. By default, Perplexity (`perplexity/sonar` etc.) is reached via OpenRouter — no separate key needed. |

By default, embeddings run **locally** with `nomic-embed-text-v1.5` (no key, ~500MB downloaded on first run, runs on CPU). You only need Voyage for a quality bump.

OpenAlex, arXiv, Crossref, Unpaywall need no keys.

Without Exa, discovery falls back to bibliographic sources only — still works but misses grey literature and recent web-native discussion.

Other sources are added by installing plugins:

```bash
calli plugin search zotero               # search PyPI
calli plugin install callimachus-zotero  # install + register
calli plugin configure zotero            # interactive config
```

See [`docs/PLUGINS.md`](docs/PLUGINS.md) for the plugin model, bundled and known community plugins, and how to write your own.

## Cost (you do the math)

Callimachus reports honest token + model usage during runs and in the run log (`calli log`). It does **not** translate tokens to dollars — pricing changes too often, varies by deployment (OpenRouter vs direct vs Bedrock vs Vertex), and isn't load-bearing for the product. If you want a budget number, multiply your run's tokens by your provider's current per-token price.

To bound run size:

- `--max-works N` — hard cap on works ingested
- `--max-hours N` — hard cap on wall time
- Convergence settings stop snowball when it stops finding good candidates

Embeddings run locally (free), arXiv + OpenAlex are free, Mistral OCR is fixed per-page (~$1/1000 pages), Claude calls via OpenRouter are the variable cost. A typical 200-work build is in the single-to-low-double-digit dollars.

## Configuration

The most useful flags on `calli init`:

```bash
calli init \
  --library ~/Callimachus \         # path to library (default ~/Callimachus)
  --collection "diffusion models" \
  --keywords "..." \
  --notes "..." \
  --auto                            # skip all interactive checkpoints
  --max-works 200                   # hard cap on works ingested
  --max-hours 6                     # hard cap on wall time
  --snowball-depth 2                # citation hops from seed works
  --since 2015                      # year filter
  --languages en                    # included languages
  --llm-provider anthropic          # or openai, gemini, openrouter
  --embeddings local                # or voyage
```

By default, Callimachus pauses for your input at four checkpoints:

1. **Plan review** — confirm the search strategy, scope, and expected work count
2. **Seed approval** — pick the seed works that drive snowballing
3. **Per-iteration review** *(optional, off by default)* — approve newly accepted works each pass
4. **Final prune** — drop duds before the index is built

`--auto` skips all of them. You can also edit `.callimachus/notes.md` *while a run is in progress* to steer the agents mid-flight (e.g. "more reinforcement learning angles", "less pre-2015 stuff").

## Talking to Callimachus

```bash
calli                                    # interactive TUI chat (default)
calli query "..."                        # one-shot query
calli serve --mcp                        # MCP server on stdio
calli serve --web                        # local web UI on :8000
```

The MCP server exposes `search_library`, `get_work`, `find_related`, `summarise_collection`, `cite`, etc. as MCP tools. Plug it into Claude Code, Cursor, Claude Desktop, or any MCP host. Mutation tools (extend, prune, refresh) are gated by default for remote use — you opt in if you want a remote agent able to modify your library.

## Sharing and backup

Three tiers, in order of how most users will want to do it:

### Tier 1 — git-friendly (recommended default)

A `.gitignore` excludes `works/*/original.pdf` and `.callimachus/state.json`. Everything else commits cleanly to plain git: extracted markdown, metadata, the SQLite database, overviews. Typical committed size for a 500-work library: ~500MB. Fits any git host without LFS.

To restore the PDFs after cloning:

```bash
calli rehydrate
```

This re-downloads PDFs from the source URLs stored in each work's metadata. The library's *intelligence* (markdown, summaries, embeddings, citation graph, judge reasoning) is what got version-controlled — that's the part that took compute to produce.

### Tier 2 — full snapshot

```bash
calli export ~/snapshot.tar.gz                   # everything including PDFs
calli export --collection diffusion-models ~/snap.tar.gz   # one collection only
calli import ~/snapshot.tar.gz ./new-library     # restore anywhere
```

Use case: gift someone a complete library, archive a frozen state, share a single collection without exposing the rest.

### Tier 3 — git LFS for power users

If you want full version history of PDFs, `docs/BACKUP.md` documents the LFS setup. Not the default.

## Roadmap

- **v0.1** — papers + essays + reports, the experience above
- **v0.2** — `talk` and `chapter` as new work kinds: YouTube via `yt-dlp` + Whisper, book chapters via dedicated extractors
- **v0.3** — explicit multi-contributor merging (the "PR" workflow for shared libraries)
- **v0.4** — scheduled refresh as a daemon
- **future** — collaborative libraries, library-of-libraries, in-place reading UI

## Architecture and design

- [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) — design and rationale behind every choice
- [`docs/USER_STORIES.md`](docs/USER_STORIES.md) — the experiences this is built around
- [`docs/PLUGINS.md`](docs/PLUGINS.md) — the plugin system, bundled and community plugins, how to write your own

## Contributing

Open source under MIT. Issues and PRs welcome. Please read the architecture doc first so we agree on the shape of contributions.
