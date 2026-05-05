"""local_pdfs — discover and resolve PDFs already on disk.

Simplest possible bundled plugin. No network. Implements both
`DiscoverySource` (list PDFs in a configured directory, return as
`WorkCandidate`s) and `Resolver` (return bytes for a candidate that
matches a local file).

Configuration (via constructor or callimachus.yaml):
    paths: list of directories to scan (default: empty — disabled until
        the user points it at a directory).
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from callimachus.sources.protocols import (
    Provenance,
    ResolvedFile,
    SourceKind,
    SourceUnavailable,
    WorkCandidate,
    WorkKind,
)

log = logging.getLogger(__name__)


def _slugify(text: str) -> str:
    """Token-friendly version of a string for matching titles → filenames."""
    out: list[str] = []
    for ch in text.lower():
        if ch.isalnum():
            out.append(ch)
        elif ch in (" ", "-", "_", ".", "/"):
            out.append(" ")
    return " ".join("".join(out).split())


class LocalPdfsPlugin:
    """Both a DiscoverySource and a Resolver for local PDFs.

    Stem-only matching: a candidate matches a file if a normalised version
    of the candidate's title appears in the normalised filename. Crude on
    purpose — local_pdfs is a "what do I already have" tool, not a
    bibliographic engine.
    """

    name: str = "local_pdfs"
    kind: SourceKind = "vault"
    enabled: bool = True

    def __init__(self, paths: list[Path] | None = None) -> None:
        self.paths: list[Path] = list(paths or [])

    def _all_pdfs(self) -> list[Path]:
        """Every PDF under any configured path. Sorted, deduped."""
        seen: set[Path] = set()
        result: list[Path] = []
        for root in self.paths:
            if not root.is_dir():
                continue
            for p in root.rglob("*.pdf"):
                resolved = p.resolve()
                if resolved in seen:
                    continue
                seen.add(resolved)
                result.append(resolved)
        return sorted(result)

    def _candidate_from_path(self, path: Path, query: str) -> WorkCandidate:
        title = path.stem.replace("_", " ").replace("-", " ").strip()
        return WorkCandidate(
            title=title,
            source_url=path.as_uri(),
            provenance=Provenance(source_name=self.name, query=query),
            extras={"local_path": str(path)},
        )

    # ---------- DiscoverySource ----------

    async def search(
        self,
        query: str,
        *,
        limit: int = 50,
        year_from: int | None = None,
        year_to: int | None = None,
        kinds: list[WorkKind] | None = None,
    ) -> list[WorkCandidate]:
        # year_from / year_to / kinds are accepted for protocol conformance but
        # ignored — local_pdfs has no year metadata and treats every match as
        # `kind="paper"` regardless of filter.
        del year_from, year_to, kinds
        """Crude title-substring match against the stems of local PDF filenames."""

        def _do_search() -> list[WorkCandidate]:
            q_norm = _slugify(query)
            terms = q_norm.split()
            hits: list[WorkCandidate] = []
            for path in self._all_pdfs():
                stem_norm = _slugify(path.stem)
                # Match if any query term appears in the normalised filename.
                # If query is empty, return everything (up to limit).
                if not terms or any(t in stem_norm for t in terms):
                    hits.append(self._candidate_from_path(path, query))
                if len(hits) >= limit:
                    break
            return hits

        return await asyncio.to_thread(_do_search)

    # ---------- Resolver ----------

    async def confidence(self, candidate: WorkCandidate) -> float:
        """1.0 if a local file matches the candidate's title; else 0.0."""

        def _do_check() -> float:
            local_path = candidate.extras.get("local_path")
            if isinstance(local_path, str) and Path(local_path).is_file():
                return 1.0
            # Fall back to title matching across all configured paths
            title_norm = _slugify(candidate.title)
            if not title_norm:
                return 0.0
            for path in self._all_pdfs():
                if title_norm in _slugify(path.stem) or _slugify(path.stem) in title_norm:
                    return 1.0
            return 0.0

        return await asyncio.to_thread(_do_check)

    async def resolve(self, candidate: WorkCandidate) -> ResolvedFile:
        def _do_resolve() -> ResolvedFile:
            local_path_str = candidate.extras.get("local_path")
            if isinstance(local_path_str, str):
                path = Path(local_path_str)
                if path.is_file():
                    return ResolvedFile(
                        candidate_id=candidate.candidate_id,
                        bytes_=path.read_bytes(),
                        content_type="application/pdf",
                        source_url=path.as_uri(),
                        resolved_by=self.name,
                    )
            # Fall back: scan
            title_norm = _slugify(candidate.title)
            for path in self._all_pdfs():
                if title_norm and (
                    title_norm in _slugify(path.stem) or _slugify(path.stem) in title_norm
                ):
                    return ResolvedFile(
                        candidate_id=candidate.candidate_id,
                        bytes_=path.read_bytes(),
                        content_type="application/pdf",
                        source_url=path.as_uri(),
                        resolved_by=self.name,
                    )
            raise SourceUnavailable(f"local_pdfs: no file matches {candidate.candidate_id!r}")

        return await asyncio.to_thread(_do_resolve)
