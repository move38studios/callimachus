# User stories

This document captures the experiences `callimachus` should support. The architecture and CLI surface are derived from these, not the other way around.

## The mental model

A **library** is a directory (default `~/Callimachus/`). It contains everything Callimachus needs to query, extend, refine, and share your research.

A library has one or more **collections**. A collection is a coherent subject ("creativity in humans and machines", "diffusion models", "music theory") with first-class identity: scope, embedding, overview document, seed works, README. Collections aren't tags.

A **work** is a research artifact: paper, essay, report (later: talk, chapter). A work can belong to multiple collections with per-collection relevance scores. A work that's highly relevant to two or more collections is flagged as a **bridge** — the cross-pollination payoff.

A **run** is a single Callimachus operation that mutated the library — initial build, extending with a new collection, refresh, prune, re-judge. Every work carries the run that admitted it; every change is auditable.

**Callimachus** is the librarian agent — the persona you talk to. The chat (`calli`) is the dominant interface. CLI subcommands (`calli init`, `calli refresh`, `calli prune`, `calli query`) are typed shortcuts to librarian actions.

## Personas

- **The lone researcher** — building deep expertise in a topic, solo. Wants to outsource the boring discovery work and end up with a personal library they can search and read.
- **The team lead** — building a shared library their team can clone, query, and contribute back to. Cares about reproducibility and shareability.
- **The consultant** — picks up a new domain every few weeks. Needs to ramp fast on unfamiliar literature without becoming a librarian themselves.
- **The autodidact** — curious about cross-disciplinary topics, wants to find connections between fields that don't usually talk to each other.

## Story groups

### 1. Build a fresh library

> *As a researcher new to a topic, I want to give Callimachus a topic and have it produce a deep, well-organised library, so I can ramp up without weeks of bibliographic work.*

```bash
calli init \
  --collection "creativity in humans and machines" \
  --keywords "divergent thinking, computational creativity, generativity" \
  --notes "I care about the cognitive science foundations and the recent ML angle. Less interested in business / innovation literature."
```

Or just `calli` with no args — the chat opens, notices there's no library, walks the user through creating one.

Optionally `--auto` to skip the four interactive checkpoints. Otherwise Callimachus walks the user through plan review, seed approval, optional per-iteration review, final prune.

After the build, the library is ready to query.

---

### 2. Extend the library with a related topic (cross-pollination)

> *As a researcher, I have a library on creativity. I want to extend it with artificial intelligence so I can find works and ideas that bridge the two, without losing what I already have.*

CLI form:

```bash
calli collection add "artificial intelligence" \
  --keywords "transformers, RL, agents, generative models" \
  --notes "Especially interested in where AI work touches creativity, abstraction, and concept formation."
```

Conversational form:

```
$ calli
Welcome back. This library has 187 works in "creativity in humans and machines".
What would you like to do?

> Extend it with artificial intelligence — I want to find cross-pollination
> opportunities between the two fields.

Got it. I'll add "artificial intelligence" as a second collection. To focus on
cross-pollination, I'll weight the judging toward works that touch both, and
run a special pass over the existing library to find creativity works I should
re-tag as AI-relevant.
Estimated cost: $14. Estimated new works: ~120, plus ~20 re-tags.
Shall I plan the run?

> Yes, but bias more toward LLMs and concept formation.

[edits notes.md] Done. Want to review the plan before I start?
```

What changes inside the library:

- `collections` table gets a new row for "artificial intelligence" with its own embedding, keywords, notes
- New hunters spawn with a brief that includes the cross-pollination instruction
- The judge is given the existing library context — it knows not to re-add known works, but *will* re-tag existing works if they're relevant to the new collection
- A **bridge pass** explicitly looks for works scoring high on both collection embeddings — these get the `bridge` flag and are surfaced prominently
- The library `README.md` regenerates to reflect the dual-collection nature, with a section dedicated to bridge works

When the user later queries:

```
> What are the strongest bridges between creativity and AI in this library?

8 works score high on both collections. The most cited bridges are:
  ...
```

---

### 3. Refine and prune

> *As a researcher, I want to remove works that turned out to be off-topic or low quality, without restarting the whole library.*

CLI form:

```bash
calli prune --collection creativity --year-before 2010
calli prune --score-below 6
calli prune --tag survey
calli prune --work sohl-dickstein-2015-deep-unsupervised
```

Conversational form:

```
> Drop everything from before 2010 — I have enough foundations.

That would archive 23 works (soft-delete; recoverable via `restore`).
Proceed?

> Yes.

Done. 23 works archived. Library now has 164 active works.
```

```
> Re-judge the library with stricter criteria — only the truly seminal stuff
> and the recent state of the art.

That will re-score every work with a tighter rubric. Estimated cost: $4.
Works below the new threshold will be archived (recoverable). Proceed?
```

Pruning is always reversible — works go to `archive/` and the run log records every change. `calli restore` brings them back.

---

### 4. Refresh — pick up new work

> *As a researcher, I built this library 6 months ago. I want to find anything important published since then without re-doing the whole build.*

```bash
calli refresh
calli refresh --since 2026-01-01
calli refresh --collection diffusion-models
```

Callimachus:

1. Re-runs hunters with the existing collection plan, scoped to the cutoff date
2. Filters out anything already in the library (by DOI / arXiv ID / title fingerprint / source URL)
3. Judges new candidates with the same criteria as the original build
4. Optionally also re-runs forward-citation snowball from the most-cited works in the library, since their citation networks have grown
5. Reports what was added in a short changelog

---

### 5. Query and use

> *As a researcher, I want to interrogate my library — semantically, structurally, and conversationally.*

Three surfaces, same underlying agent:

**Interactive TUI chat (the dominant interface):**

```bash
calli
```

```
> Summarise the foundational works on score-based generative modelling.
> Show me the citation graph around Ho 2020.
> Find works connecting AI and information theory.
> Generate a literature review section on classifier-free guidance, with
> citations.
> What works contradict Karras 2022?
```

**One-shot CLI:**

```bash
calli query "what are the main approaches to scheduling in diffusion models?"
```

**MCP server (any chat agent can use the library):**

```bash
calli serve --mcp
```

Then Claude Code, Cursor, Claude Desktop, or any MCP host can call `search_library`, `get_work`, `find_related`, `summarise_collection`, `cite`, etc. Mutation tools (`add_collection`, `prune`, `refresh`) are gated by default — opt in with `--allow-mutations` if you want a remote agent able to modify your library.

---

### 6. Steer mid-flight

> *As a researcher, I started a build and realised partway through that I want it to pay more attention to a particular angle. I don't want to wait until it finishes or restart from scratch.*

Callimachus re-reads `.callimachus/notes.md` at the start of each snowball iteration. Edit it in any editor while the build runs:

```markdown
# Steering notes (auto-read each snowball iteration)

- Pay more attention to RL-based approaches.
- Less pre-2015 work — we have enough foundations.
- Include the recent diffusion-policy literature even if cited rarely.
```

Or in chat (works across terminals — open another `calli` while a run is in progress):

```
> While that's running, here's a note: include more on how creativity is
> measured in cognitive psychology.

Added to notes.md. The next snowball iteration will pick it up.
```

---

### 7. Reproduce, share, and back up

> *As a team lead, I want to share my library with collaborators. As any user, I want to back up my library reliably.*

Three tiers, in order of how most users will want to do it:

**Tier 1 — git-friendly default.** A `.gitignore` excludes `works/*/original.pdf` and `.callimachus/state.json`. Everything else commits cleanly to plain git: extracted markdown, metadata, the SQLite database, overviews. Typical committed size for a 500-work library: ~500MB. Fits any git host without LFS. To restore PDFs after cloning:

```bash
calli rehydrate
```

This re-downloads PDFs from the source URLs stored in each work's metadata. The library's *intelligence* (markdown, summaries, embeddings, citation graph, judge reasoning) is what got version-controlled — that's the part that took compute to produce.

**Tier 2 — full snapshot.** `calli export` produces a tarball of the entire library including PDFs. Restorable with `calli import`. Per-collection export is supported:

```bash
calli export ~/snapshot.tar.gz                        # full library
calli export --collection ai ~/ai-collection.tar.gz   # one collection
calli import ~/snapshot.tar.gz ./new-library
```

**Tier 3 — git LFS.** For users who want versioned PDFs. Setup documented in `docs/BACKUP.md`. Not the default.

A teammate who clones a library can query it as-is, extend it (`calli collection add ...`) — their additions are tagged with their identity in the run log. Explicit multi-contributor merging is v0.3.

---

### 8. Cross-library exploration

> *As a researcher, I have separate libraries on creativity and on artificial intelligence (e.g. one personal, one for work). I want Callimachus to look across them and surface intersection ideas.*

```bash
calli bridge ~/Callimachus ~/work-library --output cross-pollination.md
```

Callimachus:

1. Computes collection embeddings across both libraries
2. Finds works in each that score high on the *other* library's collection embeddings
3. Identifies citation links across the two libraries
4. Writes a markdown report: shared concepts, bridge works, candidate research directions, open questions

Read-only over both libraries; produces a notes document, not a new library. The user can then `calli init` a new library seeded from those notes if they want to dive in.

---

### 9. Scope control + run transparency

> *As a user, I want to bound how big a run can get, and see honest token/model usage so I can reason about cost myself.*

- Plan review shows expected work count and angles before kicking off
- TUI status bar shows live token + model usage during the run (no USD translation — pricing isn't Callimachus's concern; users should consult their LLM provider's billing)
- `--max-works N` hard cap; Callimachus stops cleanly and reports what it has when reached
- `--max-hours N` and convergence settings act as additional caps
- `calli log` shows historic runs with per-run token + model totals; you can do the cost math against current OpenRouter prices yourself if you want it

---

### 10. Resume after crash or pause

> *As a user with an unreliable laptop, I want a long run to survive a crash, a sleep, or a manual pause.*

- Per-work checkpointing in the pipeline phase (download, extract, enrich, embed, index are all idempotent and resume-safe)
- Per-iteration checkpointing in the discovery phase
- `calli` notices an in-progress run on startup and offers to resume
- Pressing `q` in the build TUI does a clean pause

---

### 11. Observability and trust

> *As a researcher, I want to be able to inspect why a work was admitted, by which run, and how to find similar judgments.*

Every work's `metadata.yaml` includes:

- `judge_score`
- `judge_reasoning` (the LLM's full reasoning for admission)
- `admitted_by_run_id`
- `collections: [{slug, score, is_seed}, ...]`
- `bridge: true/false`
- `seed_origin` (which hunter found it, from which angle, via which source)
- `source_url`

`calli log` shows the full event log of every run — what was searched, what was judged, what was admitted, what was archived. `calli inspect <work>` shows everything Callimachus knows about a single work.

---

### 12. Explain itself

> *As a user new to the tool, I want Callimachus to be able to explain what's in my library and what it can do for me.*

```
$ calli
Welcome back. This library has 247 works across two collections:
  • creativity in humans and machines (187 works)
  • artificial intelligence (78 works)
18 works bridge both collections.
Last build: 2026-04-12. Last refresh: 2026-04-30 (added 14 works).
Total spend across all runs: $42.18.

You can ask me to:
  • Query the library ("summarise foundational works on X")
  • Add a new collection
  • Refresh (find work since the last build)
  • Prune or re-judge
  • Bridge to another library

What would you like to do?
```

---

## Edge cases and failure modes worth thinking through

- **Wildly disparate collections in one library** ("creativity" + "Roman aqueducts") — should Callimachus warn and suggest two libraries with a bridge instead? Or just go with it?
- **Collection name collision** — what if `collection add` is given a topic effectively the same as one already there? Suggest extending the existing instead.
- **Library size cap** — at what point does sqlite-vec performance degrade enough to suggest a migration to LanceDB? Surface a warning at ~50k chunks.
- **Stale judges** — old works were judged with the old prompt; new ones with the new one. Does Callimachus offer a `rejudge` automatically when prompts change significantly?
- **Conflict on refresh** — a work archived in a prune is re-discovered in a refresh. Ignore by default? Ask?
- **Rate limits and source outages** — graceful degradation when one of the discovery APIs is down. Run continues with the remaining sources.
- **PDF source rot** — `rehydrate` finds a 404 on a source URL. Try alternative URLs (DOI → Unpaywall → archive.org). Surface unrecoverable rot to the user.
- **User wants to plug in a non-standard source** — e.g. an institutional repository, a personal notes folder, a private blog. Sources should be a plugin interface, not a closed list.

## Source extensibility

Discovery sources and PDF resolvers are a **plugin system** — see [`PLUGINS.md`](PLUGINS.md). The bundled sources cover the open-access bibliographic web and the wider web. Anything else is a plugin away.

### 13. Plug in your existing knowledge as a source

> *As a researcher, I already have a Zotero library / an Obsidian vault / a folder of PDFs I've collected over the years. I want Callimachus to treat those as a source — both for discovery (when planning a new collection, consider what I already have) and as a resolver (if I already own the PDF, don't re-download).*

```bash
calli plugin install callimachus-zotero
calli plugin configure zotero
calli refresh                           # zotero contributions now flow in
```

When the user adds a new collection, hunters now query Zotero alongside OpenAlex and Exa. When the pipeline tries to resolve a PDF, the Zotero resolver checks the user's existing library first — no re-download for things they already own.

### 14. Plug in private or institutional access

> *As a university researcher, I have access to ACM Digital Library and IEEE Xplore through my institution's proxy. I want Callimachus to use those for resolution when bundled OA sources can't find a PDF.*

```bash
calli plugin install callimachus-oclc-proxy
calli plugin configure oclc-proxy       # base URL, session token
```

The OCLC proxy resolver registers at lower priority than Unpaywall (so OA is still preferred when available) but higher than failure (so it's tried before the work is marked unresolvable). Whatever bundled sources can't resolve, the proxy picks up.

### 15. Write a plugin for a niche source

> *As a contributor, I work in a domain (philosophy / climate / law) where the bundled sources don't cover the most important databases. I want to write a plugin for my domain and share it.*

A plugin is a small Python package implementing the `DiscoverySource` and/or `Resolver` Protocol. A reference implementation lives at `examples/example-plugin/` in the main repo. Publish to PyPI; open a PR to add it to `docs/PLUGINS.md`'s known-community list.

The bundled plugins implement the same interfaces — there's no privileged "core" path. If a community plugin earns enough adoption, we can absorb it into the bundle in a future release with the maintainer's blessing.
