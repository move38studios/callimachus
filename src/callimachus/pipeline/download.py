"""Download stage — write a `ResolvedFile`'s bytes to the library on disk."""

from __future__ import annotations

import logging
from pathlib import Path

from callimachus.pipeline.paths import original_path
from callimachus.sources import ResolvedFile

log = logging.getLogger(__name__)


def download_to_library(library_root: Path, work_id: str, resolved: ResolvedFile) -> Path:
    """Write `resolved.bytes_` to `<library_root>/works/<work_id>/original.{ext}`.

    Idempotent: if the destination file already exists with the same size,
    we skip the write and return the path. (Size is a cheap proxy; a stronger
    check would hash the bytes, but for the deterministic pipeline this is
    enough — re-resolving the same source returns the same bytes.)
    """
    dest = original_path(library_root, work_id, resolved.content_type)
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists() and dest.stat().st_size == len(resolved.bytes_):
        log.debug("download_to_library: %s already exists, skipping", dest)
        return dest
    dest.write_bytes(resolved.bytes_)
    log.debug("download_to_library: wrote %d bytes to %s", len(resolved.bytes_), dest)
    return dest
