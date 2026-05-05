"""Source plugins — discovery sources and resolvers.

Bundled plugins live in `bundled/`. Third-party plugins register via
Python entry points or by being dropped into `<library_root>/plugins/`.

See `docs/PLUGINS.md` for the contract.
"""

from __future__ import annotations

from callimachus.sources.protocols import (
    CitationGraph,
    DiscoverySource,
    Provenance,
    ResolvedFile,
    Resolver,
    SourceKind,
    SourceUnavailable,
    WorkCandidate,
    WorkKind,
)
from callimachus.sources.registry import SourceRegistry, default_registry

__all__ = [
    "CitationGraph",
    "DiscoverySource",
    "Provenance",
    "ResolvedFile",
    "Resolver",
    "SourceKind",
    "SourceRegistry",
    "SourceUnavailable",
    "WorkCandidate",
    "WorkKind",
    "default_registry",
]
