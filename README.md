# Callimachus

> Give Callimachus a topic, get a library. Then talk to it.

`callimachus` is an open-source autonomous research librarian. You give it a topic; it scouts the field, asks you a few clarifying questions, then sends agentic hunters out across academic catalogues and the wider web in parallel. An LLM judge decides what's worth keeping. Accepted papers are downloaded, extracted to clean markdown with structured metadata, summarised, embedded, and indexed. The output is a self-contained library directory you can copy, share, version, or query.

The chat persona is named after the man who invented bibliographic catalogues at the Library of Alexandria in the 3rd century BC. The CLI command is `calli`.

---

## Status — May 2026

This is **active development**. We have a working topic→library pipeline; the chat layer and snowball loop are next.

| Phase | Status | What it does |
|-------|--------|--------------|
| **M1** ✅ | Done | Storage + plugin system + ingest pipeline (arXiv → markdown + summary + embeddings → SQLite) |
| **M2** ✅ | Done | Topic → library: scout, HITL plan ceremony, parallel hunters, judge, orchestrator, `calli build` CLI |
| **M3** 🔜 | Next | Chat with your library: librarian agent, `calli chat` REPL |
| **M4** | Later | Snowball through citations, multi-collection, build dashboard |
| **M5** | Later | MCP server so any chat agent can query the library |
| **M6** | Later | Polish + ship v0.1 |

**Today you can:** run `calli build --topic "X"`, answer four questions, watch ~30-100 papers get downloaded, summarised, and indexed, then `calli query "..."` to do semantic search across them.

**You cannot yet:** chat with your library, snowball through citations, or run multiple collections in one library. Those land in M3-M5.

Detailed roadmap: [`docs/DEV_PLAN.md`](docs/DEV_PLAN.md).

---

## Try it

```bash
git clone https://github.com/move38studios/callimachus
cd callimachus
uv sync
cp .env.example .env       # add OPENROUTER_API_KEY at minimum
uv run calli init          # creates ~/Callimachus/ (configurable)

# Two-step build (terraform plan/apply pattern)
uv run calli build --topic "diffusion models for image generation"
# → scout probes 5-8 angles, you answer 4 questions, plan saved to .yaml

uv run calli build --from-plan diffusion-models-for-image-generation
# → hunters search in parallel, judge filters, accepted papers ingested

# Or skip the ceremony entirely
uv run calli build --topic "..." --auto

# Search the library
uv run calli query "main approaches to scheduling"
uv run calli list
```

The build typically runs 5-30 minutes depending on `max_works`, source latency, and how many papers need OCR. You watch streaming progress for each angle and each ingested paper.

`uv run calli` because the venv-installed `calli` script isn't on your shell PATH by default. Activate the venv (`source .venv/bin/activate`) if you'd rather type plain `calli`.

---

## What you get on disk

```
~/Callimachus/                        # your library (configurable via CALLIMACHUS_LIBRARY)
  library.db                          # SQLite + sqlite-vec — everything queryable
  works/
    arxiv-2006-11239/
      original.pdf                    # source artifact (or .tar.gz for arxiv LaTeX)
      paper.md                        # full text + YAML frontmatter (title, authors, etc)
      summary.md                      # 2-3 sentence judge-grade summary
      metadata.yaml                   # full enrichment + judge reasoning
  collections/                        # M4: per-subject folders
  archive/                            # M3+: soft-deleted works
  plugins/                            # local plugin .py files (auto-loaded)
  .callimachus/
    plans/<slug>.yaml                 # M2 plans you can review/edit before running
```

Plans persist as YAML so you can review the angles + keywords + scope cap before committing the slow + expensive deep build.

---

## Architecture at a glance

The current build pipeline:

```
calli build --topic X
  │
  ├─ scout (LLM + OpenAlex probe)         → AngleTree { 5-8 angles, sample papers per angle }
  ├─ ceremony (4 HITL questions)          → Plan { angles, keywords, orientation, max_works }
  └─ orchestrator (calli build --from-plan)
        │
        ├─ N hunters (parallel) ──→ candidates
        │      • each is a Pydantic AI agent (Sonnet 4.6)
        │      • tools: arxiv, openalex, serper_scholar, perplexity
        │
        ├─ dedupe + filter (arxiv_id OR doi)
        │
        ├─ judge (parallel, Sonnet 4.6)   → Verdict per candidate
        │
        ├─ ingest accepted (serial)       → Work rows
        │      • resolve  (arxiv → LaTeX or PDF; doi → Unpaywall)
        │      • extract  (LaTeX render or Mistral OCR)
        │      • enrich   (LLM → title/authors/summary/key claims)
        │      • chunk + embed (nomic-embed-text-v1.5, local)
        │      • index    (Work + chunks + vec_chunks)
        │
        └─ Run row finalised with token totals
```

The discovery sources and PDF resolvers are a **plugin system** — bundled plugins implement the same `Protocol`s any third-party plugin would. See [`docs/PLUGINS.md`](docs/PLUGINS.md).

Deep dive: [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md).

---

## API keys

The only required key is `OPENROUTER_API_KEY` — Callimachus routes most LLM calls through OpenRouter (one key for many models). Add others to `.env` as you want their features:

| Key | What it unlocks |
|-----|-----------------|
| `OPENROUTER_API_KEY` | **Required.** All LLM calls (scout, hunters, judge, enricher) + the Perplexity discovery source |
| `MISTRAL_API_KEY` | OCR for image-only / scanned PDFs that don't have LaTeX source. Without this, only arxiv-LaTeX papers extract cleanly. |
| `SERPER_API_KEY` | Google Scholar discovery via Serper. ~free for 2,500 queries on signup. |
| `OPENALEX_MAILTO` | Polite-pool etiquette for OpenAlex. Optional but recommended. |
| `UNPAYWALL_EMAIL` | Polite-pool etiquette for Unpaywall. Optional but recommended. |

Embeddings run **locally** by default (`nomic-embed-text-v1.5`, ~500MB downloaded on first run, runs on CPU). No key.

OpenAlex, arXiv, and Unpaywall all work without keys — just slower on the polite pool when you don't identify yourself.

---

## Bundled plugins (today)

| Plugin | Type | Notes |
|--------|------|-------|
| `arxiv` | discovery + resolver | LaTeX source preferred (cleanest extraction), PDF fallback |
| `openalex` | discovery (bibliographic) | Free, no key, ~250M-work catalogue. Also the scout's probe source. |
| `serper_scholar` | discovery (bibliographic) | Google Scholar via Serper API |
| `serper_web` | discovery (web) | General Google search; auto-disabled for academic builds |
| `perplexity` | discovery (bibliographic) | Natural-language queries via OpenRouter (`perplexity/sonar-pro`) |
| `unpaywall` | resolver | Open-access PDFs for any DOI |
| `local_pdfs` | discovery + resolver | Point at any directory of PDFs you already have |

Plugins register via Python entry points (for distributed plugins) or by dropping `.py` files in `<library>/plugins/` (for personal extensions). Full contract in [`docs/PLUGINS.md`](docs/PLUGINS.md).

---

## Development

The project is structured with **proven-in-experiment, then production-coded** discipline. Every non-obvious choice was first validated in `experiments/NN-name/` with a `LEARNINGS.md` capturing what we found.

```
src/callimachus/
  cli.py                    # Typer entry point: init, ingest, query, list, build
  llm.py                    # MODEL_FAST / MODEL_SMART / MODEL_DEEP constants
  storage/                  # SQLModel + sqlite-vec + Alembic
  sources/                  # plugin contracts + bundled plugins
    bundled/
      arxiv.py
      openalex.py
      serper.py
      perplexity.py
      unpaywall.py
      local_pdfs.py
  pipeline/                 # deterministic ingest stages
    download.py
    extract.py              # LaTeX or OCR → markdown
    enrich.py               # LLM → metadata + frontmatter
    chunk.py
    embed.py
    index.py
    ingest.py               # orchestrates the above per-paper
    ocr/                    # OCR provider abstraction (Mistral default)
  discovery/                # M2: topic → library
    plan.py                 # Angle / AngleTree / Plan models + YAML I/O
    scout.py                # LLM hypothesis + OpenAlex probe → AngleTree
    ceremony.py             # HITL questions → Plan
    judge.py                # single-shot Verdict per candidate
    hunter.py               # Pydantic AI sub-agent per angle
    orchestrator.py         # Plan → run hunters → judge → ingest

experiments/                # exploratory probes, kept as evidence
  NN-name/
    README.md
    run.py
    LEARNINGS.md

tests/                      # mirrors src/, ~360 unit + ~12 live tests
```

### Running checks

```bash
uv run pytest               # unit tests (fast, no network)
uv run pytest -m live       # live tests (real APIs — needs keys)
uv run pyright              # strict type checking
uv run ruff check           # lint
uv run ruff format          # format
uv run pre-commit run --all-files   # full hygiene pass
```

CI runs `pyright + ruff + pytest` on every push. Live tests are gated behind `pytest -m live` and excluded from default CI.

### Working norms

The standing brief for every coding session: [`CLAUDE.md`](CLAUDE.md). Highlights:

- Type everything, strict pyright, modern syntax (`X | None`, `list[X]`)
- Pydantic for system boundaries (LLM I/O, plugin contracts, config). Plain dataclasses for internals.
- `uv` for everything (no raw `pip`)
- Don't commit comments that explain *what* code does — let names do that. Comment *why*.
- New behaviour → update the doc that owns it in the same change. Doc/code drift is the bug we hate most.

### Architecture documents

- [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) — design and rationale
- [`docs/PLUGINS.md`](docs/PLUGINS.md) — plugin contract, bundled and community
- [`docs/USER_STORIES.md`](docs/USER_STORIES.md) — the experiences this is built around
- [`docs/DEV_PLAN.md`](docs/DEV_PLAN.md) — milestones, what's done, what's next
- [`LEARNINGS.md`](LEARNINGS.md) — cross-cutting findings from experiments

---

## Roadmap (concrete next steps)

**M3 — Chat with your library** *(next)*
- Librarian Pydantic AI agent with read tools (`search_library`, `get_work`, `find_related`, `summarise_topic`, `cite`)
- `calli chat` REPL using the prompt_toolkit + Rich pattern (validated in experiment 05)
- Mutation tools (`prune`, `restore`) gated behind `--allow-mutations`

**M4 — Depth + breadth**
- Snowball through citation graphs (Semantic Scholar plugin for citation contexts)
- Multi-collection within a library; bridge-paper detection
- Refresh + rejudge mutation tools
- Textual build dashboard (multi-pane, parallel hunter view)

**M5 — MCP**
- FastMCP server exposing read tools to Claude Code, Cursor, Claude Desktop
- Mutation tools opt-in
- Cross-library bridges (`calli bridge LIB_A LIB_B`)

**M6 — Polish + ship v0.1**

---

## Contributing

Open source under MIT. Issues and PRs welcome.

If you're new to the project: read [`CLAUDE.md`](CLAUDE.md), then [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md), then poke through `experiments/` to see how we validate ideas before committing them to production code. The `experiments/00-env-check/` directory is a good first PR template — small, self-contained, with a `LEARNINGS.md`.

Pre-commit hooks enforce ruff + pyright + tests. Set them up once with `uv run pre-commit install`.

For substantive changes: open an issue first to discuss the approach. We're small enough that a quick design conversation saves rework.
