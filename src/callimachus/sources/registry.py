"""Plugin registry — load entry-point + local-file plugins, expose by capability."""

from __future__ import annotations

import importlib.util
import inspect
import logging
from collections.abc import Callable
from importlib.metadata import entry_points
from pathlib import Path

from callimachus.sources.protocols import (
    CitationGraph,
    DiscoverySource,
    ResolvedFile,
    Resolver,
    SourceUnavailable,
    WorkCandidate,
)

log = logging.getLogger(__name__)

DISCOVERY_GROUP = "callimachus.discovery_sources"
RESOLVER_GROUP = "callimachus.resolvers"


class SourceRegistry:
    """Holds the loaded discovery sources and resolvers; tries to resolve."""

    def __init__(self) -> None:
        self._discovery: dict[str, DiscoverySource] = {}
        self._resolvers: dict[str, Resolver] = {}

    # ----- registration -----

    def register_discovery(self, source: DiscoverySource) -> None:
        self._discovery[source.name] = source

    def register_resolver(self, resolver: Resolver) -> None:
        self._resolvers[resolver.name] = resolver

    def load_entry_points(self) -> None:
        """Discover plugins published via Python entry points (pip-installed).

        A single class registered under both `discovery_sources` and `resolvers`
        groups is instantiated **once** and registered under whichever Protocols
        it satisfies (so plugins like `local_pdfs` that are both share state).
        """
        instance_cache: dict[str, object] = {}

        def load_or_get(ep_value: str, ep_load: Callable[[], object]) -> object:
            if ep_value in instance_cache:
                return instance_cache[ep_value]
            cls = ep_load()
            instance: object = cls() if isinstance(cls, type) else cls
            instance_cache[ep_value] = instance
            return instance

        for ep in entry_points(group=DISCOVERY_GROUP):
            try:
                instance = load_or_get(ep.value, ep.load)
            except Exception as exc:
                log.warning(
                    "failed to load discovery source %r from entry point: %s: %s",
                    ep.name,
                    type(exc).__name__,
                    exc,
                )
                continue
            if not isinstance(instance, DiscoverySource):
                log.warning("entry-point %r does not satisfy DiscoverySource Protocol", ep.name)
                continue
            self.register_discovery(instance)
            log.debug("loaded discovery source: %s", instance.name)

        for ep in entry_points(group=RESOLVER_GROUP):
            try:
                instance = load_or_get(ep.value, ep.load)
            except Exception as exc:
                log.warning(
                    "failed to load resolver %r from entry point: %s: %s",
                    ep.name,
                    type(exc).__name__,
                    exc,
                )
                continue
            if not isinstance(instance, Resolver):
                log.warning("entry-point %r does not satisfy Resolver Protocol", ep.name)
                continue
            self.register_resolver(instance)
            log.debug("loaded resolver: %s", instance.name)

    def load_local_directory(self, plugins_dir: Path) -> None:
        """Discover plugins from `*.py` files in `plugins_dir`.

        Each file is imported; any module-level instance that satisfies
        `DiscoverySource` or `Resolver` is registered. Files starting with
        `_` are skipped.
        """
        if not plugins_dir.is_dir():
            return
        for path in sorted(plugins_dir.glob("*.py")):
            if path.name.startswith("_"):
                continue
            try:
                spec = importlib.util.spec_from_file_location(
                    f"_callimachus_local_plugin_{path.stem}", path
                )
                if spec is None or spec.loader is None:
                    log.warning("could not build import spec for %s", path)
                    continue
                module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(module)
            except Exception as exc:
                log.warning(
                    "failed to import local plugin %s: %s: %s",
                    path,
                    type(exc).__name__,
                    exc,
                )
                continue

            for attr_name in dir(module):
                if attr_name.startswith("_"):
                    continue
                obj = getattr(module, attr_name)
                if isinstance(obj, type):
                    try:
                        obj = obj()
                    except Exception:
                        continue
                if isinstance(obj, DiscoverySource):
                    self.register_discovery(obj)
                    log.debug("loaded local discovery source: %s (%s)", obj.name, path)
                if isinstance(obj, Resolver):
                    self.register_resolver(obj)
                    log.debug("loaded local resolver: %s (%s)", obj.name, path)

    # ----- queries -----

    def discovery_sources(self, *, enabled_only: bool = True) -> list[DiscoverySource]:
        sources = list(self._discovery.values())
        if enabled_only:
            sources = [s for s in sources if s.enabled]
        return sources

    def citation_graph_sources(self, *, enabled_only: bool = True) -> list[DiscoverySource]:
        """Discovery sources that *also* satisfy the CitationGraph Protocol."""
        return [
            s
            for s in self.discovery_sources(enabled_only=enabled_only)
            if isinstance(s, CitationGraph)
        ]

    def resolvers(self, *, enabled_only: bool = True) -> list[Resolver]:
        resolvers = list(self._resolvers.values())
        if enabled_only:
            resolvers = [r for r in resolvers if r.enabled]
        return resolvers

    def get_discovery(self, name: str) -> DiscoverySource | None:
        return self._discovery.get(name)

    def get_resolver(self, name: str) -> Resolver | None:
        return self._resolvers.get(name)

    # ----- the resolve loop -----

    async def resolve(self, candidate: WorkCandidate) -> ResolvedFile:
        """Try resolvers in descending-confidence order; return first success.

        Raises `SourceUnavailable` if every enabled resolver returns
        confidence == 0 or fails with `SourceUnavailable`.
        """
        scored: list[tuple[float, Resolver]] = []
        for r in self.resolvers():
            conf = await r.confidence(candidate)
            if conf > 0:
                scored.append((conf, r))
        scored.sort(key=lambda x: -x[0])

        if not scored:
            raise SourceUnavailable(
                f"no enabled resolver claims confidence > 0 for {candidate.candidate_id}"
            )

        last_failure: SourceUnavailable | None = None
        for conf, resolver in scored:
            log.debug(
                "trying resolver %s (confidence=%.2f) for %s",
                resolver.name,
                conf,
                candidate.candidate_id,
            )
            try:
                return await resolver.resolve(candidate)
            except SourceUnavailable as exc:
                log.debug("resolver %s declined: %s", resolver.name, exc)
                last_failure = exc
                continue

        raise SourceUnavailable(
            f"all resolvers failed for {candidate.candidate_id}: {last_failure}"
        )

    # ----- lifecycle -----

    @staticmethod
    async def _maybe_call(plugin: object, method_name: str) -> None:
        """Invoke an optional async hook (`start` / `close`) if the plugin has one."""
        method = getattr(plugin, method_name, None)
        if not callable(method):
            return
        result = method()
        if inspect.isawaitable(result):
            await result

    async def start_all(self) -> None:
        """Call optional `start()` on every plugin that has one."""
        for plugin in [*self._discovery.values(), *self._resolvers.values()]:
            await self._maybe_call(plugin, "start")

    async def close_all(self) -> None:
        """Call optional `close()` on every plugin that has one."""
        for plugin in [*self._discovery.values(), *self._resolvers.values()]:
            try:
                await self._maybe_call(plugin, "close")
            except Exception as exc:
                log.warning(
                    "plugin %r close() raised: %s: %s",
                    getattr(plugin, "name", "?"),
                    type(exc).__name__,
                    exc,
                )


def default_registry(library_root: Path | None = None) -> SourceRegistry:
    """Build a registry with entry-point + local-directory plugins loaded.

    `library_root` defaults to `~/Callimachus/`. Local plugins are read
    from `<library_root>/plugins/`.
    """
    registry = SourceRegistry()
    registry.load_entry_points()

    root = library_root or (Path.home() / "Callimachus")
    registry.load_local_directory(root / "plugins")

    return registry
