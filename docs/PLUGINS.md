# Plugins

Callimachus's discovery sources and PDF resolvers are a plugin system. The bundled sources (OpenAlex, Semantic Scholar, arXiv, Crossref, Unpaywall, Exa, Perplexity) are themselves plugins — they implement the same Protocols any third-party plugin does. The judge and the rest of the pipeline don't know or care where a candidate work came from or who fetched its bytes.

This document covers:

- The two plugin interfaces
- How plugins register and configure
- How to install, list, enable, and disable plugins
- How to write a plugin
- Bundled and known community plugins
- Trust model

## The two interfaces

A plugin can implement one or both.

### `DiscoverySource` — turns a topic into candidate works

Given a query, return candidates. Optionally expose citation-graph capabilities.

```python
from typing import Protocol, Literal
from callimachus.types import WorkCandidate, CitationContext

class DiscoverySource(Protocol):
    name: str
    kind: Literal["bibliographic", "web", "preprint", "vault", "social"]

    async def search(
        self,
        query: str,
        *,
        limit: int = 50,
        year_from: int | None = None,
        **filters,
    ) -> list[WorkCandidate]: ...

    # Optional capabilities — Callimachus checks with hasattr at runtime.
    # Sources without these still work; they just don't contribute to snowball.
    async def get_references(self, work_id: str) -> list[WorkCandidate]: ...
    async def get_citations(self, work_id: str) -> list[WorkCandidate]: ...
    async def get_citation_contexts(self, work_id: str) -> list[CitationContext]: ...
```

Every `WorkCandidate` carries `provenance: { source_name, query, raw_score }` so downstream stages can weight by source if they want.

### `Resolver` — turns a known work into bytes

Given a work (DOI, arXiv ID, URL), return a downloadable file. Resolvers are tried in priority order; the first one that returns wins.

```python
class Resolver(Protocol):
    name: str
    priority: int  # higher = tried first

    async def can_resolve(self, work: WorkCandidate) -> bool:
        """Cheap pre-check — does this resolver have a URL/access path for this work?"""

    async def resolve(self, work: WorkCandidate) -> ResolvedFile:
        """Return the file bytes, content type, and source URL.
        Raise NotResolvable if it turns out you can't after all."""
```

### How plugins should signal failures

When a plugin call hits a recoverable problem (rate limit, transient outage, source returning empty results in a way the agent should know about), raise **`pydantic_ai.ModelRetry("reason")`** from the wrapper that exposes the plugin to the agent. This is fed back to the model as a recoverable signal — the agent can try a different source, fall back, or explain the failure to the user.

For unrecoverable internal failures (DB unreachable, schema invariant violated, your code has a bug), raise a normal exception. It will propagate to the run loop and surface to the user — which is what you want for hard fail.

This convention applies uniformly across `DiscoverySource` and `Resolver` implementations. See `experiments/02-pydantic-ai-tool-calling/LEARNINGS.md` for the underlying mechanism.

Some plugins implement both — arXiv is both a discovery source and a resolver. Others are one-job — Crossref is metadata-only; Unpaywall is resolver-only.

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

Drop a `.py` file in `~/Callimachus/plugins/`:

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
| `openalex` | discovery (bibliographic) | Comprehensive academic catalogue, no key |
| `semantic_scholar` | discovery + citation graph | Citation contexts, influential-cite count |
| `arxiv` | discovery + resolver | Preprints + LaTeX source for clean extraction |
| `crossref` | discovery (metadata only) | DOI resolution, structured metadata |
| `unpaywall` | resolver | Open-access PDF discovery for any DOI |
| `exa` | discovery (web, neural) | Grey literature, blog posts, lab pages |
| `perplexity` | discovery (planning-phase synthesis) | "Lay of the land" before hunters spawn. Routes via OpenRouter (`perplexity/sonar`) by default; honours `PERPLEXITY_API_KEY` for direct API access if set. |
| `local_pdfs` | discovery + resolver | Point at any directory of PDFs you already have |

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
