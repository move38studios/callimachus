"""Extract stage — turn a downloaded artifact into clean markdown.

M1.3a: handles LaTeX source (`.tex` directly, or `.tar.gz` containing `.tex`
files) via pylatexenc's `LatexNodes2Text`. PDF and HTML paths are
intentionally not implemented yet — they raise `ExtractError` so the
caller can route to M1.3b's OCR path when that lands.
"""

from __future__ import annotations

import gzip
import io
import logging
import tarfile
from pathlib import Path
from typing import cast

from pylatexenc.latex2text import LatexNodes2Text

from callimachus.pipeline.paths import markdown_path

log = logging.getLogger(__name__)


class ExtractError(Exception):
    """Raised when an artifact's content type isn't supported (yet) by extract."""


def _is_latex_archive(content_type: str) -> bool:
    main = content_type.split(";", 1)[0].strip().lower()
    return main in {
        "application/x-tar",
        "application/gzip",
        "application/x-gzip",
        "application/x-eprint-tar",
        "application/x-eprint",
    }


def _is_latex_source(content_type: str) -> bool:
    main = content_type.split(";", 1)[0].strip().lower()
    return main in {"application/x-tex", "text/x-tex"}


def _pick_main_tex(tar: tarfile.TarFile) -> tuple[str, str] | None:
    """Pick the most likely main .tex file from a tar archive.

    Heuristic: the largest .tex file that contains `\\documentclass` wins.
    Falls back to the largest .tex file overall.
    """
    tex_members = [m for m in tar.getmembers() if m.isfile() and m.name.lower().endswith(".tex")]
    if not tex_members:
        return None

    candidates: list[tuple[int, str, str]] = []
    for member in tex_members:
        f = tar.extractfile(member)
        if f is None:
            continue
        try:
            text = f.read().decode("utf-8", errors="replace")
        finally:
            f.close()
        candidates.append((len(text), member.name, text))

    if not candidates:
        return None

    # Prefer ones with \documentclass, then by descending size
    with_docclass = [c for c in candidates if "\\documentclass" in c[2]]
    pool = with_docclass or candidates
    pool.sort(key=lambda c: -c[0])
    _, name, text = pool[0]
    return name, text


def _read_latex_source(artifact_bytes: bytes, content_type: str) -> str:
    """Pull the main LaTeX source out of a tarball, gzip, or raw .tex."""
    if _is_latex_source(content_type):
        return artifact_bytes.decode("utf-8", errors="replace")

    # arxiv's e-print is most often a gzipped tar; sometimes plain gzip
    # over a single .tex (though rarer these days).
    bio = io.BytesIO(artifact_bytes)
    try:
        with tarfile.open(fileobj=bio, mode="r:*") as tar:
            picked = _pick_main_tex(tar)
            if picked is None:
                raise ExtractError("extract: archive contains no .tex files we can use")
            name, text = picked
            log.debug("extract: picked main TeX file %r (%d chars)", name, len(text))
            return text
    except tarfile.TarError:
        # Not a tar — try plain gzip wrapping a .tex
        try:
            inner = gzip.decompress(artifact_bytes)
            return inner.decode("utf-8", errors="replace")
        except (OSError, EOFError) as exc:
            raise ExtractError(
                f"extract: artifact is not a valid tar or gzip archive: {exc}"
            ) from exc


def latex_to_markdown(latex_text: str) -> str:
    """Convert a LaTeX document body to plain-text-ish markdown.

    pylatexenc gives plain text with reasonable structure preservation
    (paragraphs, sections, math via Unicode). We treat that as "good
    enough markdown" for v0.1 — enrichment + embedding can work with it.
    """
    converter = LatexNodes2Text(
        keep_comments=False,
        math_mode="text",  # render math as Unicode where possible
    )
    # pylatexenc has no type stubs; everything coming out of it is `Unknown`
    # so cast through `object` to a guaranteed `str`.
    raw_text: object = converter.latex_to_text(latex_text)  # pyright: ignore[reportUnknownMemberType, reportUnknownVariableType]
    text = cast("str", raw_text)
    # Normalise multiple blank lines down to two
    out_lines: list[str] = []
    blank_streak = 0
    for line in text.splitlines():
        if not line.strip():
            blank_streak += 1
            if blank_streak <= 1:
                out_lines.append("")
        else:
            blank_streak = 0
            out_lines.append(line.rstrip())
    # Strip leading/trailing blank lines
    while out_lines and not out_lines[0]:
        out_lines.pop(0)
    while out_lines and not out_lines[-1]:
        out_lines.pop()
    return "\n".join(out_lines) + "\n"


def extract_to_markdown(
    library_root: Path, work_id: str, artifact_path: Path, content_type: str
) -> Path:
    """Read the downloaded artifact, extract markdown, write `paper.md`.

    Returns the path to the written markdown file. Idempotent: if
    `paper.md` already exists, skip and return the existing path.
    """
    dest = markdown_path(library_root, work_id)
    if dest.exists():
        log.debug("extract_to_markdown: %s already exists, skipping", dest)
        return dest

    if not (_is_latex_archive(content_type) or _is_latex_source(content_type)):
        raise ExtractError(
            f"extract: content type {content_type!r} not supported in M1.3a "
            f"(PDF + HTML support comes in M1.3b)"
        )

    artifact_bytes = artifact_path.read_bytes()
    latex_text = _read_latex_source(artifact_bytes, content_type)
    markdown = latex_to_markdown(latex_text)

    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(markdown)
    log.debug("extract_to_markdown: wrote %d chars of markdown to %s", len(markdown), dest)
    return dest
