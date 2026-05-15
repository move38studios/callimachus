# Plugins

Callimachus's discovery sources and PDF resolvers are a plugin system. The bundled sources (OpenAlex, arXiv, Serper, Perplexity, Unpaywall, local PDFs) are themselves plugins — they implement the same Protocols any third-party plugin does. The judge and the rest of the pipeline don't know or care where a candidate work came from or who fetched its bytes.

This document covers:

- The two plugin interfaces
- How plugins register and configure
- How to install, list, enable, and disable plugins
- How to write a plugin
- Bundled and known community plugins
- Trust model

## The interfaces

A plugin can implement one or more. All interfaces are `typing.Protocol` (PEP 544 structural typing) — plugins don't inherit anything, they just have the right shape. All methods are async (most plugins do I/O).

### `DiscoverySource` — turn a topic into candidate works

Given a query, return candidates.

```python
from typing import Protocol, Literal, runtime_checkable
from callimachus.sources import WorkCandidate

@runtime_checkable
class DiscoverySource(Protocol):
    name: str
    kind: Literal["bibliographic", "web", "preprint", "vault", "social"]
    enabled: bool

    async def search(
        self,
        query: str,
        *,
        limit: int = 50,
        year_from: int | None = None,
        year_to: int | None = None,
        kinds: list[str] | None = None,
    ) -> list[WorkCandidate]: ...
```

Common filters (`year_from`, `year_to`, `kinds`) are explicit kwargs. Source-specific configuration goes through the plugin's `config_model` at construction time, not into `search()`.

### `CitationGraph` — optional capability for sources with citation data

Sources that expose references / citations / contexts implement this *additionally*. Most don't (only Semantic Scholar does well). The registry exposes `citation_graph_sources()` for callers that need this capability.

```python
@runtime_checkable
class CitationGraph(Protocol):
    async def get_references(self, work_id: str) -> list[WorkCandidate]: ...
    async def get_citations(self, work_id: str) -> list[WorkCandidate]: ...
    async def get_citation_contexts(self, work_id: str) -> list[dict[str, str]]: ...
```

### `Resolver` — turn a known work into bytes

Given a `WorkCandidate` with metadata (doi, arxiv_id, source_url, …), produce its file bytes. Multiple resolvers may be able to handle the same candidate; the registry picks per call by **confidence**.

```python
@runtime_checkable
class Resolver(Protocol):
    name: str
    enabled: bool

    async def confidence(self, candidate: WorkCandidate) -> float:
        """Self-report 0.0-1.0 for how well this resolver can fetch THIS candidate.
        E.g. arxiv resolver returns 1.0 if arxiv_id is set, 0.0 otherwise.
        unpaywall returns 0.9 if doi is set, 0.0 otherwise.
        local_pdfs returns 1.0 if a matching file exists locally, 0.0 otherwise."""

    async def resolve(self, candidate: WorkCandidate) -> ResolvedFile: ...
```

The registry sorts resolvers by descending confidence per call and tries them in order. First success wins. No magic priority numbers — confidence is adaptive (depends on the candidate) and self-explanatory.

LLM is not in this loop. Per-resolution decisions are deterministic (cheap, predictable, reproducible). The orchestrator only re-enters when *all* resolvers fail and the work needs alternative strategy.

### Optional lifecycle: `start()` / `close()`

Plugins that own resources (HTTP clients with connection pools, long-lived database connections) should expose:

```python
async def start(self) -> None: ...   # called by registry at startup
async def close(self) -> None: ...   # called by registry at shutdown
```

Registry checks via `hasattr` and calls them if present. Stateless plugins (e.g. a thin function-only plugin) can omit both.

### How plugins should signal failures

Two kinds of failure, two kinds of behaviour:

| Failure | Raise | What happens |
| --- | --- | --- |
| Recoverable (rate limit, transient outage, source returning empty in a way the agent should know about) | `callimachus.sources.SourceUnavailable("reason")` | Caught at the agent boundary, re-raised as `pydantic_ai.ModelRetry`. Orchestrator can try a different source/angle. |
| Unrecoverable internal failure (your code has a bug, schema invariant violated, dependency completely broken) | `Exception` (any normal exception) | Propagates to the run loop, surfaces to the user. Hard fail by design. |

Plugins **don't depend on `pydantic_ai`** — they raise `callimachus.sources.SourceUnavailable` from our namespace. The wrapper that exposes the plugin to an agent translates to `ModelRetry`. This keeps plugins clean, swappable, testable.

### `WorkCandidate` ≠ `Work` (deliberately)

A `WorkCandidate` (Pydantic, in `callimachus.sources`) is what plugins return — pre-acceptance, lightweight, source-agnostic, may be incomplete:

```python
class WorkCandidate(BaseModel):
    title: str
    source_url: str
    provenance: Provenance              # {source_name, query, raw_score, retrieved_at}
    doi: str | None = None
    arxiv_id: str | None = None
    authors: list[str] = Field(default_factory=list)
    year: int | None = None
    abstract: str | None = None
    venue: str | None = None
    pdf_url: str | None = None
    kind: Literal["paper", "essay", "report", "talk", "chapter"] = "paper"
    extras: dict[str, object] = Field(default_factory=dict)
```

A `Work` (SQLModel, in `callimachus.storage`) is what's stored in the library — has DB lifecycle (`added_at`, `archived_at`, `judge_score`, `markdown_path`, …). Conversion happens at admission time. Plugins never touch `Work`.

### `ResolvedFile`

```python
class ResolvedFile(BaseModel):
    candidate_id: str          # the candidate this was resolved for
    bytes_: bytes              # the file content
    content_type: str          # 'application/pdf', 'application/x-tex', 'text/html'
    source_url: str            # where the bytes came from (may differ from candidate.source_url)
    resolved_by: str           # plugin name
```

v0.1 ships with `bytes_: bytes`. If we hit a memory wall on large artifacts (book chapters, multi-volume reports), we'll add a `Path`-based variant later.

Some plugins implement both `DiscoverySource` and `Resolver` — arXiv is both. Others are one-job — Crossref is metadata-only; Unpaywall is resolver-only.

## Registration

Two paths, both supported.

### Entry points (for distributed plugins via pip)

The standard Python plugin pattern. Plugins declare themselves in `pyproject.toml`:

```toml
[project.entry-points."callimachus.discovery_sources"]
pubmed = "callimachus_pubmed:PubMedSource"

[project.entry-points."callimachus.resolvers"]
my_uni_proxy = "callimachus_pubmed:OCLCProxy"
```

Callimachus enumerates these at startup with `importlib.metadata.entry_points()` and registers what's installed. No code changes in core to add a new plugin.

### Local files (for personal plugins, no packaging needed)

Drop a `.py` file in your library's `plugins/` directory — by default `~/Callimachus/plugins/`, or `<library_root>/plugins/` if you've configured `CALLIMACHUS_LIBRARY` elsewhere. Each library has its own plugin directory; the plugins are scoped to that library.

```python
# ~/Callimachus/plugins/my_lab_pages.py
from callimachus.sources import DiscoverySource, WorkCandidate

class MyLabPagesSource:
    name = "my_lab_pages"
    kind = "web"

    async def search(self, query, *, limit=50, **kw):
        # scrape your favourite lab pages, return candidates
        ...
```

Auto-loaded on startup. Useful for personal/private extensions you don't want to package and publish.

## Configuration

Each plugin gets a namespace under `callimachus.yaml`. Plugins ship a Pydantic settings model that validates user config:

```yaml
sources:
  openalex:
    enabled: true
    rate_limit_per_second: 10
  exa:
    enabled: true
    api_key: $EXA_API_KEY
  my_uni_proxy:
    enabled: true
    base_url: https://yoursubdomain.idm.oclc.org
    session_token: $UNI_TOKEN
  zotero:
    enabled: true
    library_id: 12345
    api_key: $ZOTERO_KEY
```

Per-collection overrides are supported under `collections/<slug>/collection.yaml`:

```yaml
sources:
  arxiv: { enabled: false }     # this is a humanities collection
  philpapers: { enabled: true }
```

`$VAR` syntax expands from the environment, so secrets stay in `.env` and out of committed yaml.

## CLI

```bash
calli plugin list                       # show installed plugins, status, version
calli plugin search <query>             # search PyPI for callimachus-* packages
calli plugin install <name>             # pip install + register
calli plugin enable <name>
calli plugin disable <name>             # disable without uninstalling
calli plugin configure <name>           # interactive config wizard
calli plugin doctor                     # validate every plugin's config
```

`calli plugin install` is a thin wrapper over `pip install` (or `uv pip install`) that also runs the plugin's post-install hook if it has one (e.g. fetch a one-time index).

## Writing a plugin

A minimal discovery source plugin, top to bottom:

```python
# callimachus_pubmed/__init__.py
import httpx
from callimachus.sources import WorkCandidate
from pydantic import BaseModel, Field

class PubMedConfig(BaseModel):
    api_key: str | None = None
    rate_limit_per_second: int = 3

class PubMedSource:
    name = "pubmed"
    kind = "bibliographic"
    config_model = PubMedConfig

    def __init__(self, config: PubMedConfig):
        self.config = config
        self.client = httpx.AsyncClient(...)

    async def search(self, query, *, limit=50, year_from=None, **kw):
        # call NCBI E-utilities, parse, return WorkCandidate list
        ...

    async def get_references(self, work_id):
        # PubMed's link service
        ...
```

```toml
# pyproject.toml
[project]
name = "callimachus-pubmed"
dependencies = ["httpx", "callimachus>=0.1"]

[project.entry-points."callimachus.discovery_sources"]
pubmed = "callimachus_pubmed:PubMedSource"
```

Publish to PyPI. Users `calli plugin install callimachus-pubmed`. Done.

A reference plugin with full structure (tests, config, docs) lives at `examples/example-plugin/` in the main repo.

## Bundled plugins

These ship with `callimachus` itself and are enabled by default:

| Plugin | Type | Purpose |
| --- | --- | --- |
| `arxiv` | discovery + resolver | Preprints + LaTeX source for clean extraction. PDF fallback. Confidence 1.0 when `arxiv_id` is set. |
| `openalex` | discovery (bibliographic) | Comprehensive ~250M-work academic catalogue. No key needed (polite-pool email recommended via `OPENALEX_MAILTO`). Also the scout's probe source. |
| `serper_scholar` | discovery (bibliographic) | Google Scholar via Serper API. Needs `SERPER_API_KEY` (free tier: 2,500 queries). Lazy-checked at search time. |
| `serper_web` | discovery (web) | General Google search via Serper. Auto-disabled by `calli build` for academic libraries since web hits don't carry an arxiv_id or DOI for the resolver chain. |
| `perplexity` | discovery (bibliographic) | Natural-language queries via OpenRouter (`perplexity/sonar-pro`). Citations come back with URL+title; we extract arxiv_id or DOI per URL. Reuses `OPENROUTER_API_KEY`. |
| `unpaywall` | resolver | Open-access PDF discovery for any DOI. Confidence 0.7 when `doi` is set. Polite-pool email via `UNPAYWALL_EMAIL`. |
| `local_pdfs` | discovery + resolver | Point at any directory of PDFs you already have. Currently scope-restricted: configure via constructor, not yaml. |

**Not yet built** (referenced in older parts of the docs):
- `semantic_scholar` — planned for M4 (the citation-graph snowball loop needs `citationContexts`)
- `crossref` — planned for M4 alongside Semantic Scholar
- `exa` — deferred; Perplexity covers the natural-language web-search role for now

## Known community plugins

This list is maintained in the main repo. PRs welcome to add yours.

*(Empty at v0.1. Examples we hope to see — none of these exist yet.)*

**Personal knowledge as a source:**
- `callimachus-zotero` — your Zotero library as a discovery source and resolver
- `callimachus-obsidian` — your Obsidian vault as essays
- `callimachus-readwise` — your Readwise highlights
- `callimachus-pocket` / `callimachus-instapaper` — your read-later queue

**Domain-specific bibliographic:**
- `callimachus-pubmed` — biomedical literature
- `callimachus-philpapers` — philosophy
- `callimachus-ssrn` — social science working papers
- `callimachus-acm` — ACM Digital Library
- `callimachus-ieee` — IEEE Xplore

**Access plugins:**
- `callimachus-oclc-proxy` — generic institutional proxy resolver
- `callimachus-shibboleth` — SAML-authed library access

**Specialised resolvers:**
- `callimachus-archive-org` — fallback fetcher via the Internet Archive

The idea: Callimachus core stays clean and minimal. Anything else is a `pip install` away. The project does not take a position on what users should or shouldn't index; the plugin system makes that the user's choice.

## Trust model

Plugins run in-process and have full Python access. The same trust model applies as for any other Python package you `pip install`: vet at install time, prefer plugins from authors and orgs you trust, read the source if you're unsure.

We do not sandbox plugins and we do not sign them. Sandboxing in-process Python plugins is impractical without a major architecture change (subprocess isolation, IPC overhead, lost ergonomics) and signing introduces a curation bottleneck we don't want to own. This matches every other Python plugin ecosystem (pytest, FastAPI middleware, click extensions).

If you write a plugin and want it linked from the main repo's plugin list, open a PR — we'll do a basic review (it is what it claims to be, doesn't obviously misbehave) before adding the link, but we don't endorse plugins beyond that.

## How the rest of the system uses plugins

For completeness, here's how plugins flow into the architecture:

- **Orchestrator** queries the `SourceRegistry`, gets enabled discovery sources back. Briefs each hunter on which sources to weight for its angle.
- **Hunters** call `search()` on their assigned sources in parallel. Candidates aggregate to the orchestrator with `provenance` attached.
- **Judge** reads candidates and scores them. May weight by source reliability (configurable per source).
- **Pipeline `resolve` step** iterates resolvers in priority order until one returns a `ResolvedFile`. Each resolver gets a chance via `can_resolve()` first to skip cheaply.
- **Plugin failures degrade gracefully.** A source that times out or errors is logged and skipped for the rest of the run; the run continues with the remaining sources. A resolver that fails moves to the next in priority.
- **Per-run plugin metrics** are written to the run log: which source contributed how many accepted candidates, which resolver fetched how many PDFs, error rates, average latency. Surfaces in `calli plugin doctor` and per-run reports.
