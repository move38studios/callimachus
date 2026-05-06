"""Library and per-work path helpers.

Single source of truth for where things live on disk:
    <library_root>/
        works/{slug}/
            original.{ext}    # the raw downloaded artifact
            paper.md          # extracted markdown
            summary.md        # enrichment output (M1.3c)
            metadata.yaml     # frontmatter (M1.3c)
        index/library.db
        ...

The library root resolves from `$CALLIMACHUS_LIBRARY` if set, else
`~/Callimachus/`.
"""

from __future__ import annotations

import os
from pathlib import Path

DEFAULT_LIBRARY_ROOT = Path.home() / "Callimachus"


def get_library_root(override: Path | None = None) -> Path:
    """Resolve the library root.

    Resolution order: explicit `override` arg, `$CALLIMACHUS_LIBRARY`,
    then `~/Callimachus/`.
    """
    if override is not None:
        return override.expanduser().resolve()
    env_path = os.environ.get("CALLIMACHUS_LIBRARY")
    if env_path:
        return Path(env_path).expanduser().resolve()
    return DEFAULT_LIBRARY_ROOT


def work_dir(library_root: Path, work_id: str) -> Path:
    """`<library_root>/works/<work_id>/`."""
    return library_root / "works" / work_id


# Map common content types to file extensions for the original.{ext} file.
# Anything not listed falls back to .bin.
_CONTENT_TYPE_EXT: dict[str, str] = {
    "application/pdf": ".pdf",
    "application/x-tar": ".tar.gz",
    "application/gzip": ".tar.gz",
    "application/x-gzip": ".tar.gz",
    "application/x-eprint-tar": ".tar.gz",
    "application/x-eprint": ".tar.gz",
    "application/x-tex": ".tex",
    "text/x-tex": ".tex",
    "text/html": ".html",
    "text/plain": ".txt",
}


def extension_for_content_type(content_type: str) -> str:
    """File extension (incl. leading dot) for a Content-Type header value."""
    # Strip parameters like '; charset=utf-8'
    main = content_type.split(";", 1)[0].strip().lower()
    return _CONTENT_TYPE_EXT.get(main, ".bin")


def original_path(library_root: Path, work_id: str, content_type: str) -> Path:
    """Path for the originally-resolved file: `works/{slug}/original.{ext}`."""
    return work_dir(library_root, work_id) / f"original{extension_for_content_type(content_type)}"


def markdown_path(library_root: Path, work_id: str) -> Path:
    """Path for the extracted markdown: `works/{slug}/paper.md`."""
    return work_dir(library_root, work_id) / "paper.md"
